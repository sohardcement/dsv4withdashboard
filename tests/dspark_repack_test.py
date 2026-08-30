#!/usr/bin/env python3
"""DSpark dflash GGUF -> DS4 support GGUF integration test."""

import argparse
import pathlib
import struct
import subprocess
import tempfile


ALIGNMENT = 32
GGUF_STRING = 8
GGUF_UINT32 = 4
F32 = 0
F16 = 1
Q8_0 = 8
Q4_K = 12
BF16 = 30
MXFP4 = 39


def packed_string(value: str) -> bytes:
    raw = value.encode()
    return struct.pack("<Q", len(raw)) + raw


def pad(data: bytearray, alignment: int = ALIGNMENT) -> None:
    data.extend(b"\0" * (-len(data) % alignment))


def q8_row(seed: int) -> bytes:
    values = bytes(((seed + i) % 17 for i in range(32)))
    return struct.pack("<H", 0x3C00) + values


def mxfp4_row() -> bytes:
    block = bytes([127]) + bytes((((15 - i) << 4) | i for i in range(16)))
    return block * 8


def build_fixture(path: pathlib.Path) -> dict[str, bytes]:
    tensors = [
        ("blk.0.ffn_gate_exps.weight", [256, 1, 1], MXFP4, mxfp4_row()),
        ("fc.weight", [32, 1], Q8_0, q8_row(1)),
        ("enc.output_norm.weight", [4], F32, struct.pack("<4f", 1, 2, 3, 4)),
        ("conf_proj.weight", [32, 1], Q8_0, q8_row(2)),
        ("output_hc_base.weight", [4], F32, struct.pack("<4f", 5, 6, 7, 8)),
        ("output_hc_fn.weight", [4], BF16, struct.pack("<4H", 0x3F80, 0xC000, 0x3F00, 0)),
        ("output_hc_scale.weight", [4], F32, struct.pack("<4f", 9, 10, 11, 12)),
        ("markov_w1.weight", [32, 1], Q8_0, q8_row(3)),
        ("markov_w2.weight", [32, 1], Q8_0, q8_row(4)),
        ("output_norm.weight", [4], F32, struct.pack("<4f", 13, 14, 15, 16)),
    ]
    kv = bytearray()
    kv += packed_string("general.architecture") + struct.pack("<I", GGUF_STRING) + packed_string("dflash")
    kv += packed_string("general.alignment") + struct.pack("<II", GGUF_UINT32, ALIGNMENT)

    infos = bytearray()
    offset = 0
    payload = bytearray()
    expected = {}
    for name, dims, tensor_type, raw in tensors:
        infos += packed_string(name)
        infos += struct.pack("<I", len(dims))
        infos += struct.pack(f"<{len(dims)}Q", *dims)
        infos += struct.pack("<IQ", tensor_type, offset)
        payload += raw
        pad(payload)
        offset = len(payload)
        expected[name] = raw

    header = bytearray(b"GGUF")
    header += struct.pack("<IQQ", 3, len(tensors), 2)
    header += kv + infos
    pad(header)
    path.write_bytes(header + payload)
    return expected


def read_string(data: bytes, pos: int) -> tuple[str, int]:
    length = struct.unpack_from("<Q", data, pos)[0]
    pos += 8
    return data[pos : pos + length].decode(), pos + length


def parse_output(path: pathlib.Path):
    data = path.read_bytes()
    assert data[:4] == b"GGUF"
    version, tensor_count, kv_count = struct.unpack_from("<IQQ", data, 4)
    assert version == 3
    pos = 24
    kv = {}
    for _ in range(kv_count):
        key, pos = read_string(data, pos)
        value_type = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        if value_type == GGUF_STRING:
            value, pos = read_string(data, pos)
        elif value_type == GGUF_UINT32:
            value = struct.unpack_from("<I", data, pos)[0]
            pos += 4
        elif value_type == 9:
            elem_type, count = struct.unpack_from("<IQ", data, pos)
            pos += 12
            assert elem_type == GGUF_UINT32
            value = list(struct.unpack_from(f"<{count}I", data, pos))
            pos += count * 4
        else:
            raise AssertionError(f"unexpected KV type {value_type}")
        kv[key] = value

    tensors = {}
    for _ in range(tensor_count):
        name, pos = read_string(data, pos)
        rank = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        dims = struct.unpack_from(f"<{rank}Q", data, pos)
        pos += rank * 8
        tensor_type, offset = struct.unpack_from("<IQ", data, pos)
        pos += 12
        tensors[name] = (dims, tensor_type, offset)
    data_offset = (pos + ALIGNMENT - 1) // ALIGNMENT * ALIGNMENT
    return data, data_offset, kv, tensors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("quantizer", type=pathlib.Path)
    args = parser.parse_args()
    quantizer = args.quantizer.resolve()

    with tempfile.TemporaryDirectory(prefix="dspark-repack-") as tmp:
        source = pathlib.Path(tmp) / "dflash.gguf"
        output = pathlib.Path(tmp) / "support.gguf"
        expected = build_fixture(source)
        subprocess.run(
            [str(quantizer), "--dspark-gguf", str(source), "--out", str(output)],
            check=True,
            capture_output=True,
            text=True,
        )
        data, data_offset, kv, tensors = parse_output(output)

        assert kv["general.architecture"] == "deepseek4-dspark"
        assert kv["dspark.stage_count"] == 3
        assert kv["dspark.target_layer_ids"] == [40, 41, 42]
        assert tensors["mtp.0.ffn_gate_exps.weight"][1] == Q4_K
        assert tensors["mtp.2.hc_head_fn.weight"][1] == F16
        assert tensors["mtp.0.main_norm.weight"][1] == F32
        assert tensors["mtp.0.main_proj.weight"][1] == Q8_0

        _, _, fc_offset = tensors["mtp.0.main_proj.weight"]
        assert data[data_offset + fc_offset : data_offset + fc_offset + 34] == expected["fc.weight"]
        _, _, fn_offset = tensors["mtp.2.hc_head_fn.weight"]
        assert data[data_offset + fn_offset : data_offset + fn_offset + 8] == bytes.fromhex(
            "003c00c000380000"
        )
        _, _, expert_offset = tensors["mtp.0.ffn_gate_exps.weight"]
        expert = data[data_offset + expert_offset : data_offset + expert_offset + 144]
        assert len(expert) == 144 and any(expert)


if __name__ == "__main__":
    main()
