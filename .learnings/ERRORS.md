# Errors

## [ERR-20260816-001] in_app_browser_screenshot_timeout

**Logged**: 2026-08-16T09:15:00+08:00
**Priority**: low
**Status**: resolved
**Area**: docs

### Summary
读取 X 帖子中的基准图时，页面截图命令超时。

### Error
```text
Timed out running CDP command "Page.captureScreenshot"
```

### Context
- 帖子正文已经提供主要吞吐数据；截图只用于核对附图细节。
- 评论区对测试版本提出质疑，因此即使截图成功，该结果也只能视为待复核的第三方数据。

### Suggested Fix
监测任务优先使用可引用的正文和原始基准文件；截图超时时不要重复消耗时间，也不要提升证据等级。

### Metadata
- Reproducible: unknown
- Related Files: none

### Resolution
- **Resolved**: 2026-08-16T09:15:00+08:00
- **Notes**: 保留正文证据并降级为“有争议、待本机复测”。

---

## [ERR-20260827-001] zsh_readonly_status_variable

**Logged**: 2026-08-27T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: tests

### Summary
诊断脚本误用 zsh 只读特殊变量 `status` 保存退出码，导致断言命令自身失败。

### Error
```text
zsh:4: read-only variable: status
```

### Context
- 对 `/ds4/status` 的 dashboard 状态同步断言需要保存 `jq` 的退出码。
- 当前执行 shell 是 zsh，`status` 不能作为普通脚本变量赋值。

### Suggested Fix
在 zsh 兼容脚本中使用任务专属变量名，例如 `sync_rc`，不要复用 shell 特殊变量。

### Metadata
- Reproducible: yes
- Related Files: `tests/run_dashboard_ui_test.sh`

### Resolution
- **Resolved**: 2026-08-27T00:00:00+08:00
- **Notes**: 后续诊断命令改用 `sync_rc`。

---

## [ERR-20260817-001] in-app-browser-mlxfast-details

**Logged**: 2026-08-17T09:01:46+08:00
**Priority**: low
**Status**: pending
**Area**: infra

### Summary
The mlx.fast leaderboard exposed submission detail buttons in the DOM snapshot, but an exact accessible-name Playwright locator could not resolve the first button.

### Error
```text
Playwright selector deadline exceeded
Locator diagnostics: no_matches
```

### Context
- Read-only verification of the mlx.fast Qwen3.8 Apple Silicon leaderboard.
- The snapshot contained `Open tanishq-dubey's submission details`, but the corresponding role/name locator returned no matches.
- The headline and aggregate throughput remained readable; exact submission hardware therefore stays unverified.

### Suggested Fix
Use a fresh DOM snapshot and a visible node id or inspect the solver/submission URL exposed by the page instead of relying on a translated or transient accessible name.

### Metadata
- Reproducible: unknown
- Related Files: none

---

## [ERR-20260815-001] grounded_citations_sources_status_subcommand

**Logged**: 2026-08-15T09:20:00+08:00
**Priority**: low
**Status**: resolved
**Area**: docs

### Summary
`grounded-citations` 的 `sources.py` 不提供 `status` 子命令，查询引用账本应使用 `list`。

### Error
```text
sources.py: error: argument cmd: invalid choice: 'status'
```

### Context
- 在生成模型监测简报前尝试查看已登记来源。
- 失败发生在只读查询步骤，没有修改引用账本或研究结果。

### Suggested Fix
先运行 `sources.py --help`，并使用 `sources.py list` 查看当前账本。

### Metadata
- Reproducible: yes
- Related Files: none

### Resolution
- **Resolved**: 2026-08-15T09:20:00+08:00
- **Notes**: 改用受支持的 `list` 子命令后继续。

---

## [ERR-20260716-GIT-PUSH-SSH] github_ssh_port_blocked

**Logged**: 2026-07-16T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: infra

### Summary
The first PR branch push failed because the repository's SSH origin used blocked port 22 even though GitHub CLI was authenticated for HTTPS.

### Error
```text
Connection closed by 198.18.1.29 port 22
fatal: Could not read from remote repository.
```

### Context
- `origin` is `git@github.com:sohardcement/dsv4withdashboard.git`.
- `gh auth status` reports an active HTTPS-authenticated account with `repo` scope.
- `git ls-remote` against the HTTPS repository URL succeeded.
- The failed push did not update any remote refs.

### Suggested Fix
Keep the user's configured remote unchanged and use a command-scoped Git URL rewrite from `git@github.com:` to `https://github.com/` for the push.

### Metadata
- Reproducible: yes
- Related Files: none

### Resolution
- **Resolved**: 2026-07-16T00:00:00+08:00
- **Notes**: HTTPS connectivity and authentication were verified before retrying the same branch push with a non-persistent URL rewrite.

---

## [ERR-20260812-001] importlib_dataclass_dynamic_module

**Logged**: 2026-08-12T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: config

### Summary
通过 `importlib.util.module_from_spec()` 动态加载含 `@dataclass` 的仓库脚本时，未先注册模块导致装饰器初始化失败。

### Error
```text
AttributeError: 'NoneType' object has no attribute '__dict__'
```

### Context
- 尝试只读复用 `gguf-tools/mixed/splice_mixed_expert_layers_gguf.py` 的 `parse_gguf()` 检查本地 GGUF 张量类型。
- 在 `spec.loader.exec_module(mod)` 前没有把 `mod` 放入 `sys.modules`。
- Python 3.11 的 `dataclasses` 会通过 `sys.modules[cls.__module__]` 解析类型上下文。

### Suggested Fix
在 `exec_module()` 前执行 `sys.modules[spec.name] = mod`，或通过正常可导入模块路径加载脚本。

### Metadata
- Reproducible: yes
- Related Files: `gguf-tools/mixed/splice_mixed_expert_layers_gguf.py`

### Resolution
- **Resolved**: 2026-08-12T00:00:00+08:00
- **Notes**: 在 `exec_module()` 前注册 `sys.modules[spec.name]` 后，解析器成功只读输出当前模型的 routed expert 张量类型。

---

## [ERR-20260811-HF-TLS] huggingface_api_parallel_fetch

**Logged**: 2026-08-11T09:00:40+08:00
**Priority**: low
**Status**: resolved
**Area**: infra

### Summary
并行读取多个 Hugging Face 模型元数据时出现一次临时 TLS 连接失败，导致部分候选返回空结果。

### Error
```text
curl: (35) LibreSSL SSL_connect: SSL_ERROR_SYSCALL in connection to huggingface.co:443
```

### Context
- 监测任务并行请求 6 个 `https://huggingface.co/api/models/<id>?blobs=true` 端点。
- 同批请求中至少一个成功，失败更像瞬时连接/并发问题，而不是模型不存在。

### Suggested Fix
对外部模型 API 使用串行请求并配置有限次数重试；失败结果不得解释为仓库不存在。

### Metadata
- Reproducible: unknown
- Related Files: `.learnings/ERRORS.md`

### Resolution
- **Resolved**: 2026-08-11T09:08:00+08:00
- **Notes**: 改为串行请求并为 `curl` 配置 2 次有限重试后，6 个模型仓库的元数据与文件大小均成功读取。

---

## [ERR-20260717-NOWLEDGE-UNAVAILABLE] local_memory_service_refused_connection

**Logged**: 2026-07-17T06:30:00+08:00
**Priority**: low
**Status**: unresolved
**Area**: infra

### Summary
Review-context lookup could not reach the local Nowledge Mem service.

### Error
```text
Failed to connect to 127.0.0.1 port 14242: Connection refused
```

### Context
- The memory search was useful but non-blocking for reviewing the merged cancellation fixes.
- Retrying outside the filesystem sandbox produced the same connection refusal, so the failure was not caused by repository permissions.
- Local Git history and GitHub PR metadata provided sufficient evidence to continue.

### Suggested Fix
Check that the Nowledge Mem local service is running and listening on port `14242` before relying on cross-tool memory lookup.

### Metadata
- Reproducible: yes
- Related Files: none

---

## [ERR-20260717-SERVER-TEST-SANDBOX] loopback_socket_denied_in_sandbox

**Logged**: 2026-07-17T06:37:00+08:00
**Priority**: low
**Status**: resolved
**Area**: tests

### Summary
The focused server regression test failed and hung when the sandbox blocked its loopback `bind` and `connect` calls.

### Error
```text
tests/../ds4_server.c:14867: assertion failed: bind(listener, (struct sockaddr *)&addr, sizeof(addr)) == 0
tests/../ds4_server.c:14872: assertion failed: connect(client_fd, (struct sockaddr *)&addr, sizeof(addr)) == 0
```

### Context
- `make ds4_test` completed successfully in the sandbox.
- `./ds4_test --server` exercises local HTTP sockets and therefore needs loopback network access.
- The same binary and arguments passed immediately outside the sandbox with `server: OK` and `ds4 tests: ok`.

### Suggested Fix
Run socket-based server regressions with the narrow permission needed for local loopback networking; do not treat sandbox socket denials as code regressions.

### Metadata
- Reproducible: yes
- Related Files: `ds4_server.c`, `tests/ds4_test.c`

### Resolution
- **Resolved**: 2026-07-17T06:37:00+08:00
- **Notes**: Re-ran the unchanged test command outside the sandbox and confirmed exit code 0.

---

## [ERR-20260716-MTP-PROFILE-FIXTURE] greedy_profile_test_required_ignored_mtp

**Logged**: 2026-07-16T00:00:00+08:00
**Priority**: medium
**Status**: resolved
**Area**: tests

### Summary
The new greedy launcher profile test assumed the ignored 3.5 GiB MTP GGUF existed, so it failed in a clean worktree and would fail in CI.

### Error
```text
assertion failed: strstr(out, "--mtp gguf/DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf") != NULL
assertion failed: strstr(out, "--mtp-draft 2") != NULL
```

### Context
- `start-server.sh` intentionally clears its optional default MTP path when that file is absent.
- The primary worktree contains the ignored local support model; a clean worktree does not.
- The launcher behavior was correct, but the unit test encoded a machine-local fixture assumption.

### Suggested Fix
Make the default-path assertion conditional on the optional GGUF existing, then use a tracked readable stub path through `DS4_MTP_PATH` to verify deterministic MTP argument and draft-depth assembly everywhere.

### Metadata
- Reproducible: yes
- Related Files: `start-server.sh`, `ds4_server.c`, `.gitignore`

### Resolution
- **Resolved**: 2026-07-16T00:00:00+08:00
- **Notes**: The isolated PR branch now covers both optional-default behavior and explicit MTP enable/disable behavior without requiring a large local model in CI.

---

## [ERR-20260716-WORKTREE-MODEL-FIXTURE] make_test_missing_ignored_model

**Logged**: 2026-07-16T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: tests

### Summary
A clean worktree baseline `make test` stopped because the ignored local `ds4flash.gguf` symlink is not copied into new worktrees.

### Error
```text
long-context:
ds4: cannot open model 'ds4flash.gguf': No such file or directory
make: *** [test] Error 1
```

### Context
- The compile, Q4_K unit tests, extractor tests, and agent tests completed before the model-loading failure.
- The primary worktree has ignored symlink `ds4flash.gguf` pointing to the local IQ2/Q2 model.
- `tests/ds4_test.c` supports an explicit `DS4_TEST_MODEL` override.

### Suggested Fix
For full tests in an isolated worktree, set `DS4_TEST_MODEL` to the readable absolute target of the primary worktree's model symlink instead of creating or tracking another model link.

### Metadata
- Reproducible: yes
- Related Files: `.gitignore`, `tests/ds4_test.c`, `Makefile`

### Resolution
- **Resolved**: 2026-07-16T00:00:00+08:00
- **Notes**: Root cause was verified from the missing ignored link and the documented test override; the baseline is rerun with the original model's absolute path.

---

## [ERR-20260716-CTX-HARNESS-BRACE] diagnostic_harness_compile

**Logged**: 2026-07-16T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: tests

### Summary
The first compile of the temporary same-process context benchmark failed because its decode loop lacked a closing brace.

### Error
```text
/tmp/ds4_ctx_alloc_bench.c:58:33: error: function definition is not allowed here
/tmp/ds4_ctx_alloc_bench.c:118:2: error: expected '}'
```

### Context
- This was a temporary `/tmp` diagnostic harness, not repository production code.
- Numbered source output showed the `for` loop opened at line 43 and was not closed before timing output.

### Suggested Fix
Inspect the compiler's matching-brace location, close the decode loop at the source, and recompile unchanged otherwise.

### Metadata
- Reproducible: yes
- Related Files: `/tmp/ds4_ctx_alloc_bench.c`

### Resolution
- **Resolved**: 2026-07-16T00:00:00+08:00
- **Notes**: Added the missing loop brace; the same compile command then succeeded without warnings.

---

## [ERR-20260713-004] subagent_stream_disconnect

**Logged**: 2026-07-13T23:50:00+08:00
**Priority**: medium
**Status**: resolved
**Area**: config

### Summary
A newly allocated Task 4 subagent stream disconnected before producing implementation output.

### Error
```text
stream disconnected before completion: error sending request for url (https://chatgpt.com/backend-api/codex/responses)
```

### Context
- Operation: retry dashboard monitor-mode implementation after capacity failures.
- The task used an isolated worktree with a verified approved HEAD.
- No source files or commits were produced before the disconnect.

### Suggested Fix
Retry with a fresh agent and verify worktree HEAD/status before accepting work; if recurrent, pause subagent execution and report the external service blocker.

### Metadata
- Reproducible: unknown
- Related Files: none

---

## [ERR-20260716-METAL-BENCH-BUILD] make_variant_target_timestamp

**Logged**: 2026-07-16T00:00:00+08:00
**Priority**: medium
**Status**: resolved
**Area**: tests

### Summary
The first controlled Metal benchmark attempt used a CPU-only `ds4-bench` because `make ds4-bench` treated a CPU target artifact as up to date.

### Error
```text
ds4: metal backend requested but this build has no graph backend support; aborting startup
```

### Context
- `make cpu` and the normal macOS build write the same `ds4-bench` path.
- The CPU-linked executable was newer than the normal object prerequisites, so the non-variant-aware Make target did not relink it.
- `otool -L ds4-bench` confirmed the failed binary lacked Foundation and Metal frameworks.
- The process exited before loading the model or writing benchmark results.

### Suggested Fix
After switching build variants, use `make -B ds4-bench` (or clean/rebuild the intended variant) and verify the linked frameworks before starting a Metal benchmark.

### Metadata
- Reproducible: yes
- Related Files: `Makefile`, `ds4_bench.c`

### Resolution
- **Resolved**: 2026-07-16T00:00:00+08:00
- **Notes**: Root cause was confirmed from the target recipes, timestamps, and linked libraries; the benchmark is being force-rebuilt as the normal Metal target.

---

## [ERR-20260716-DOC-PATCH] tuning_doc_context_mismatch

**Logged**: 2026-07-16T09:25:25+08:00
**Priority**: low
**Status**: resolved
**Area**: docs

### Summary
A multi-hunk documentation patch was rejected because one wrapped sentence did
not exactly match the current tuning note.

### Error
```text
apply_patch verification failed: Failed to find expected lines in
docs/agent-kv-cache-tuning.md
```

### Context
- The patch combined independent current-default and historical-sweep edits.
- `apply_patch` rejected the complete patch, so no partial documentation change
  was written.

### Suggested Fix
Patch independently scoped sections after reading their exact current line
wrapping; keep historical benchmark prose separate from current defaults.

### Metadata
- Reproducible: yes
- Related Files: `docs/agent-kv-cache-tuning.md`

### Resolution
- **Resolved**: 2026-07-16T09:25:25+08:00
- **Notes**: Confirmed the failed patch made no changes and split the update
  into exact-context hunks.

---

## [ERR-20260715-DASHBOARD-MOTION-TEST] web_animations_api_timing

**Logged**: 2026-07-15T00:00:00+08:00
**Priority**: medium
**Status**: resolved
**Area**: testing

### Summary
The first scale-trajectory regression assertion sampled Web Animations API keyframes before the patched snapshot had rendered.

### Error
```text
Error: increase motion scale trajectory is not a subtle scale-up
```

### Context
- The test helper only waited for a truthy `data-motion-direction`, so an existing `none` marker could satisfy it before the next poll.
- The browser implementation emitted the expected keyframes once the test waited for the exact direction and animation layers.

### Suggested Fix
Wait for the expected direction and incoming/outgoing layer classes before sampling animation keyframes; keep the assertion focused on the actual Web Animations API output.

### Metadata
- Reproducible: yes
- Related Files: `tests/dashboard_ui_test.js`, `ds4_server.c`

### Resolution
- **Resolved**: 2026-07-15T00:00:00+08:00
- **Notes**: Updated the helper usage to wait for the exact directional animation before reading keyframes; the full dashboard UI test then passed.


## [ERR-20260715-PLAN-PATCH] plan_patch_hunk_format

**Logged**: 2026-07-15T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: docs

### Summary
The first two attempts to add the implementation plan failed because lines inside a shell code block were missing the patch addition prefix.

### Error
```text
apply_patch verification failed: invalid hunk ... is not a valid hunk header
```

### Context
- The plan file did not exist before the patch, so no repository content was changed.
- A shorter corrected patch added the complete plan successfully.

### Suggested Fix
When creating a new file with apply_patch, verify every line in embedded code blocks is prefixed with `+` in the patch payload.

### Metadata
- Reproducible: yes
- Related Files: `docs/superpowers/plans/2026-07-15-dashboard-metric-motion.md`

### Resolution
- **Resolved**: 2026-07-15T00:00:00+08:00
- **Notes**: Re-applied the plan with correctly prefixed hunk lines and confirmed the file was created.

## [ERR-20260713-003] subagent_model_capacity

**Logged**: 2026-07-13T23:45:00+08:00
**Priority**: low
**Status**: resolved
**Area**: config

### Summary
The Task 4 implementation subagent could not start because its selected model was at capacity.

### Error
```text
Selected model is at capacity. Please try a different model.
```

### Context
- Operation: dispatch the dashboard monitor-mode implementation task.
- The failure occurred before any file edits or commits.
- The isolated worktree remained at the approved Task 3 HEAD.

### Suggested Fix
Retry the same bounded task without changing scope; verify the worktree HEAD before accepting results.

### Metadata
- Reproducible: unknown
- Related Files: none

### Resolution
- **Resolved**: 2026-07-13T23:45:00+08:00
- **Notes**: Re-dispatched the same task after confirming no implementation output was produced.

---

## [ERR-20260713-002] backticks_in_exec_search

**Logged**: 2026-07-13T23:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: config

### Summary
A plan self-review search embedded Markdown backticks in a shell command, causing unintended command substitution.

### Error
```text
zsh:1: command not found: 99
```

### Context
- The `rg` pattern in an `exec_command` string included ``records `99` ``.
- zsh evaluated the backticked text before running ripgrep.
- The remaining search still completed and no repository data was changed.

### Suggested Fix
Avoid Markdown backticks in shell command strings; search for plain text or use a safely quoted script file/pattern.

### Metadata
- Reproducible: yes
- Related Files: `docs/superpowers/plans/2026-07-13-dashboard-management-monitor.md`

### Resolution
- **Resolved**: 2026-07-13T23:00:00+08:00
- **Notes**: Re-ran the review with plain patterns and corrected the plan findings.

---

## [ERR-20260713-001] duplicate_goal_creation

**Logged**: 2026-07-13T21:10:00+08:00
**Priority**: low
**Status**: resolved
**Area**: config

### Summary
Creating a goal failed because the current task already had the same active goal.

### Error
```text
cannot create a new goal because this thread has an unfinished goal; complete the existing goal first
```

### Context
- Attempted to create the dashboard optimization goal after the `/goal` request.
- The desktop task had already materialized that request as an active goal.

### Suggested Fix
Read the current goal before creating one when `/goal` may already have initialized task state; reuse an equivalent active goal.

### Metadata
- Reproducible: yes
- Related Files: none

### Resolution
- **Resolved**: 2026-07-13T21:10:00+08:00
- **Notes**: Read the current goal and continued it because its objective exactly matches the request.

---

## [ERR-20260627-001] dry_run_side_effect

**Logged**: 2026-06-27T22:15:00+08:00
**Priority**: high
**Status**: fixed
**Area**: config

### Summary
`DS4_DRY_RUN=1 DS4_TRACE_RESET=1 ./start-server.sh` truncated the live trace because trace reset happened before the dry-run exit.

### Error
```text
/tmp/ds4-trace.jsonl became size=0 after a dry-run verification command.
```

### Context
- Command shape: `DS4_DRY_RUN=1 DS4_TRACE_RESET=1 ./start-server.sh`
- The startup script performed side effects before checking `DS4_DRY_RUN`.
- This erased the current trace data, though prior summary output remained in the conversation and KV files were unaffected.

### Suggested Fix
Keep all dry-run paths side-effect free. Perform trace reset only after the dry-run branch exits and immediately before the real `exec`.

### Metadata
- Reproducible: yes
- Related Files: `start-server.sh`

---

## [ERR-20260710-002] stale_playwright_cli_wrapper

**Logged**: 2026-07-10T00:00:00+08:00
**Priority**: medium
**Status**: pending
**Area**: tests

### Summary
The bundled Playwright skill wrapper targets a CLI entry point that the current `@playwright/mcp` package no longer exposes.

### Error
```text
The wrapper could not launch playwright-cli from the current @playwright/mcp package.
```

### Context
- Intended wrapper: `$HOME/.codex/skills/playwright/scripts/playwright_cli.sh`.
- Dashboard verification required desktop/mobile screenshots and interaction checks.
- Verification recovered by using the current `@playwright/cli` package with an isolated package cache.

### Suggested Fix
Update the bundled wrapper to use the current supported Playwright CLI package/entry point, and add a wrapper smoke test that runs `--help`.

### Metadata
- Reproducible: yes
- Related Files: `output/playwright/`

---

## [ERR-20260710-001] nonexistent_server_test_target

**Logged**: 2026-07-10T00:00:00+08:00
**Priority**: medium
**Status**: resolved
**Area**: tests

### Summary
The dashboard implementation plan named a `ds4_server_test` Make target that the repository does not define.

### Error
```text
make: *** No rule to make target `ds4_server_test'.  Stop.
```

### Context
- Attempted baseline command: `make ds4_server_test && ./ds4_server_test`.
- `ds4_server_test` appears only in the Makefile clean list.
- Server unit tests are compiled into `ds4_test` and selected with `./ds4_test --server`.

### Suggested Fix
Use `make ds4_test && ./ds4_test --server` for focused server tests and keep implementation plans aligned with actual Makefile targets.

### Metadata
- Reproducible: yes
- Related Files: `Makefile`, `tests/ds4_test.c`, `docs/superpowers/plans/2026-07-10-dashboard-kv-observability.md`

### Resolution
- **Resolved**: 2026-07-10T00:00:00+08:00
- **Notes**: Corrected the implementation plan before dispatching Task 1.

---

## [ERR-20260715-BROWSER] brainstorm_preview_background_server

**Logged**: 2026-07-15T00:00:00+08:00
**Priority**: medium
**Status**: resolved
**Area**: infra

### Summary
The visual companion preview URL became unreachable immediately after the background server command returned.

### Error
```text
curl: (7) Failed to connect to 127.0.0.1 port 60632 after 0 ms: Couldn't connect to server
```

### Context
- Started `/Users/shc/.codex/superpowers/skills/brainstorming/scripts/start-server.sh --project-dir /Users/shc/ds4 --background`.
- The command reported `server-started`, but the process was gone when checked from the next command.
- The visual companion server was bound to `127.0.0.1`.

### Suggested Fix
Run the companion server in foreground mode in a persistent PTY/session, then verify the port with curl before sharing the URL.

### Metadata
- Reproducible: yes
- Related Files: `.superpowers/brainstorm/63146-1784080316/state/server-info`

### Resolution
- **Resolved**: 2026-07-15T00:00:00+08:00
- **Notes**: Restarted the companion server in foreground mode in a persistent PTY, created the screen in the new session directory, and verified the new port with curl.

---

## [ERR-20260715-GIT-STAGING] commit_included_preexisting_index

**Logged**: 2026-07-15T00:00:00+08:00
**Priority**: high
**Status**: resolved
**Area**: config

### Summary
A design-doc commit included unrelated files that were already staged before the commit command.

### Error
```text
git commit: 212 files changed, 364563 insertions(+)
```

### Context
- The worktree already contained many staged dashboard verification artifacts and other user changes.
- The command staged the spec file and committed without first isolating or checking the complete index.
- The working tree contents must be preserved while correcting the commit boundary.

### Suggested Fix
Move `HEAD` back one commit with a non-destructive mixed reset, verify all files remain present, then stage and commit only the spec path.

### Metadata
- Reproducible: yes
- Related Files: `docs/superpowers/specs/2026-07-15-dashboard-metric-motion-design.md`

### Resolution
- **Resolved**: 2026-07-15T00:00:00+08:00
- **Notes**: Used a mixed reset to preserve all worktree files, verified the spec remained present, and isolated the next commit to the spec path only.


---
