# Huihui 0731 DSpark 长上下文基准

日期：2026-08-05

## 测试对象

- 主模型：`DeepSeek-V4-Flash-Q2-0731.gguf`
- 主模型大小：86,720,111,488 字节
- DSpark 来源：`huihui-ai/Huihui-DeepSeek-V4-Flash-0731-abliterated-GGUF`
- 固定 revision：`a8dfba9c1e43bdf324ee2c7787ed01c70975ffb4`
- 源文件：`dspark-abliterated/dspark-DeepSeek-V4-Flash-0731-Q8_0.gguf`
- 源文件 SHA-256：`6575853d1c3736c160101bc7cd117c8edd39ca847cfdf2273d9a344108edfaf8`
- DS4 support：`gguf/DeepSeek-V4-Flash-0731-DSpark-abliterated-Q4K-support.gguf`
- support 大小：11,424,932,256 字节
- support SHA-256：`95f1b9e46b702e956f4033ea3a99e66d14bd2f4a7793fe0af3980288e0b571ae`

Huihui 文件使用 `general.architecture=dflash`，并包含 DS4 尚不能直接加载的
MXFP4 routed-expert tensor。使用
`gguf-tools/deepseek4-quantize --dspark-gguf` 流式重打包后，输出包含 81 个
tensor、3 个 DSpark stage，其中 34 个 F32、7 个 F16、31 个 Q8_0 和 9 个
Q4_K routed-expert tensor。

## 测试口径

- 机器：Apple M3 Max，128 GiB RAM，Metal backend
- Context allocation：110,592 tokens
- Frontier：30k、50k、75k、100k
- 输出：128 tokens，`temperature=0`，thinking disabled
- 每档两轮，baseline/DSpark 采用 AB/BA 交替顺序
- 每档共用相同的磁盘 KV 前缀缓存
- 速度取 server 日志中的平均 decode tokens/s
- 正确性以同一轮 baseline/DSpark 的完整输出 SHA-256 是否一致为准

原始结果位于：
`.gstack/benchmark-reports/2026-08-05-dspark-huihui-long-context/results.json`。

## 结果

| Frontier | Baseline 均值 | DSpark 均值 | 提升 | Acceptance | 输出一致 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 30k | 14.270 t/s | 14.515 t/s | +1.72% | 97.14% | 2/2 |
| 50k | 15.390 t/s | 14.790 t/s | -3.90% | 100.00% | 0/2 |
| 75k | 13.160 t/s | 13.135 t/s | -0.19% | 100.00% | 0/2 |
| 100k | 13.525 t/s | 13.580 t/s | +0.41% | 88.89% | 2/2 |

四档等权平均为 baseline 14.086 t/s、DSpark 14.005 t/s，整体约
`-0.58%`。所有 DSpark run 均为 `errors=0`，support 加载检查为
`missing=0 invalid=0 metadata_errors=0`。

Acceptance 高不代表与 target-only greedy 输出严格等价。50k 两轮的输出在
第 299 个字符开始分叉；75k 两轮在第 95 个字符开始分叉。两档的 DSpark
输出在各自重复运行之间保持一致，因此不是随机采样噪声。旧 support 的
2026-08-03 基准也恰好在 50k 和 75k 分叉、30k 和 100k 一致，说明主要问题
更可能位于 speculative greedy 的数值或调度路径，而不是单纯由旧 draft
权重不匹配造成。

## 结论

- 新 Huihui support 可被 DS4/Metal 正常加载和运行，且 Q4_K expert 版本通过
  结构检查、短上下文烟测和 30k–100k 完整测试。
- 当前工作负载没有稳定的长上下文吞吐提升；50k 明确回退，整体均值略慢。
- 50k/75k 未保持 target-only greedy 的精确输出，因此不能作为要求严格复现
  或 correctness-first 的默认路径。
- `agent` profile 应继续保持 DSpark 关闭；新 support 仅通过显式
  `DS4_PROFILE=greedy` 启用，供实验和后续 runtime 修正验证。
