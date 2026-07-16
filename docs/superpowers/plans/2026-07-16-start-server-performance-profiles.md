# Start Server Performance Profiles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the local launcher use the measured M3 Max prefill setting and avoid loading MTP for sampled agent traffic while preserving an explicit greedy-MTP profile.

**Architecture:** Keep the machine-specific model and cache policy in the existing shell profile switch. Share the agent settings between `agent` and `greedy`, then select the MTP default from the profile while retaining every existing environment override.

**Tech Stack:** Bash, C99 server unit tests, Make.

---

### Task 1: Lock and implement the performance profiles

**Files:**
- Modify: `ds4_server.c:14940-14980`
- Modify: `start-server.sh:6-76`
- Modify: `docs/agent-kv-cache-tuning.md:9-35,140-175`

- [x] **Step 1: Write the failing dry-run regression test**

Add a server unit test that runs `start-server.sh` with an isolated `HOME`, an
empty model override, and no saved launcher overrides. Assert that the default
profile resolves `--ctx 51200 --prefill-chunk 5120` without `--mtp`, while
`DS4_PROFILE=greedy` resolves the same context/chunk plus the local MTP model
with draft depth two. Also change the existing no-saved-context fallback
expectation from `204800` to the already selected `51200` default.

- [x] **Step 2: Run the test to verify RED**

Run:

```sh
make ds4_test
./ds4_test --server
```

Expected: the launcher assertions fail because the current agent command still
contains `--prefill-chunk 4096 --mtp ...` and `greedy` is not yet a valid
profile.

- [x] **Step 3: Implement the launcher profiles**

Change the performance case to accept `agent|greedy`, keep
`DEFAULT_CTX=51200`, set `DEFAULT_PREFILL_CHUNK=5120`, and leave
`DEFAULT_MTP_PATH` empty for `agent`. Set the existing MTP GGUF path only when
`PROFILE=greedy`. Update the invalid-profile diagnostic to list all three
profiles.

- [x] **Step 4: Run focused verification to verify GREEN**

Run:

```sh
bash -n start-server.sh
make ds4_test
./ds4_test --server
DS4_MODEL= DS4_DRY_RUN=1 ./start-server.sh
DS4_MODEL= DS4_DRY_RUN=1 DS4_PROFILE=greedy ./start-server.sh
```

Expected: shell syntax and server tests pass; the first command contains the
5120 chunk without MTP and the second contains MTP draft depth two.

- [x] **Step 5: Synchronize tuning documentation**

Document `51200`, `5120`, `163840`, and the 2048-token continued interval as
the agent defaults. Explain that `greedy` enables MTP and that
`DS4_MTP_PATH=...` remains the explicit override.

- [x] **Step 6: Run full relevant verification**

Run:

```sh
make test
git diff --check
```

Expected: all tests exit zero and the diff has no whitespace errors.
