# HTTP 客户端断连取消实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 当非流式 HTTP 客户端在排队、prefill 或 decode 阶段超时断开时，DS4 及时停止孤儿请求，并保证 session/KV、调用历史和状态统计保持一致。

**Architecture:** DS4 保持单 worker 和单请求连接模型。在 worker 出队前以零超时 `poll()` 加 `recv(MSG_PEEK)` 判断 peer EOF；active job 把相同 predicate 安装到 `ds4_session_set_cancel()`，并在 decode token 边界显式探测。取消走独立的 `cancelled` 结束路径：不发送最终响应、不删除健康磁盘 KV，invalidate 可能不一致或语义已废弃的 live session，并清除协议 live binding。

**Tech Stack:** C99、POSIX sockets/poll、pthread、DS4 session cooperative cancellation、现有 `ds4_test --server` 测试框架。

---

## 文件结构

- 修改 `ds4_server.c`：增加断连 predicate、worker 生命周期接线、prefill/decode 取消分支、独立取消统计与响应结果处理，以及内嵌 server 单元测试。
- 修改 `ds4_call_history.h`：增加独立的 terminal `cancelled` 状态；`ds4_call_history.c` 既有通用 terminal 处理和仅聚合 `FAILED` 的逻辑已经兼容，无需改动。
- 新建 `docs/openhanako-memory-timeout-analysis.md`：记录实测根因、修复语义、验证结果和 TCP 半关闭取舍。
- 新建本计划：固定 TDD 步骤和验证命令，避免与当前主工作区的启动脚本/仪表盘改动混杂。

### Task 1: 以失败测试固定断连和取消统计契约

**Files:**

- Modify: `ds4_server.c`（`DS4_SERVER_TEST` 单元测试区及 `ds4_server_unit_tests_run()`）

- [x] **Step 1: 添加断连 predicate 契约测试**

  新增 `test_nonstream_client_disconnect_probe_contract()`：

  ```c
  static void test_nonstream_client_disconnect_probe_contract(void) {
      int sv[2];
      TEST_ASSERT(socketpair(AF_UNIX, SOCK_STREAM, 0, sv) == 0);
      set_client_socket_nonblocking(sv[0]);
      TEST_ASSERT(!server_client_disconnected(sv[0]));
      TEST_ASSERT(send(sv[1], "x", 1, 0) == 1);
      TEST_ASSERT(!server_client_disconnected(sv[0]));
      char byte = 0;
      TEST_ASSERT(recv(sv[0], &byte, 1, 0) == 1);
      /* DS4 每连接只处理一个请求；body 读完后的 peer EOF 表示放弃响应。 */
      TEST_ASSERT(shutdown(sv[1], SHUT_WR) == 0);
      TEST_ASSERT(server_client_disconnected(sv[0]));
      close(sv[0]);
      close(sv[1]);
  }
  ```

  该测试必须明确把 `SHUT_WR`/EOF 固定为取消语义，因为 TCP 无法被动区分完整 close 与仅发送方向半关闭，而 OpenHanako `AbortSignal.timeout()` 在本机表现为 FIN/EOF。

- [x] **Step 2: 添加 cancelled 状态与调用历史测试**

  新增 `test_cancelled_request_counts_as_failed()`，初始化最小 `server` 与 `status_mu`，调用：

  ```c
  server_status_finish_request(&s, "cancelled", "client disconnected during decode");
  ```

  断言 `cancelled_requests == 1`、`failed_requests == 0`、`completed_requests == 0`、`finish == "cancelled"`，并销毁 mutex。另新增一个 call-history 测试，以 `DS4_CALL_CANCELLED` 结束请求，断言 record status 的 JSON 名称是 `cancelled`，caller 的 `failures` 仍为 0。

- [x] **Step 3: 将三个测试加入 server 测试组并验证 RED**

  Run: `make ds4_test && ./ds4_test --server`

  Expected: FAIL；断连 helper 和 `DS4_CALL_CANCELLED` 尚不存在，且 cancelled 仍会被计入 completed。

### Task 2: 实现无副作用断连探测与排队任务丢弃

**Files:**

- Modify: `ds4_server.c`（`struct job` 附近、状态结束函数、状态 JSON、`worker_main()`）
- Modify: `ds4_call_history.h`（`ds4_call_status`）
- Modify: `ds4_call_history.c`（terminal status 与 caller 聚合）

- [x] **Step 0: 先添加排队丢弃的 RED 测试**

  以最小 `server`、call history、stack `job` 和 socket pair 验证：open peer 不丢弃且 history 保持 active；peer EOF 后 queue-drop helper 返回 true，history 变为 `DS4_CALL_CANCELLED`、finish=`cancelled`、detail=`client disconnected while queued`；因为未进入 prefill，status `total_requests` 保持 0。先运行 `make ds4_test`，Expected: FAIL with queue-drop helper missing。

- [x] **Step 1: 实现 socket predicate**

  在 `struct job` 附近增加：

  ```c
  static bool server_client_disconnected(int fd) {
      struct pollfd pfd = {.fd = fd, .events = POLLIN};
      int rc;
      do rc = poll(&pfd, 1, 0); while (rc < 0 && errno == EINTR);
      if (rc == 0) return false;
      if (rc < 0 || (pfd.revents & (POLLERR | POLLNVAL))) return true;
      if (!(pfd.revents & (POLLIN | POLLHUP))) return false;
      char byte;
      ssize_t n = recv(fd, &byte, 1, MSG_PEEK | MSG_DONTWAIT);
      if (n == 0) return true;
      if (n > 0) return false;
      return errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR;
  }
  ```

  `MSG_PEEK` 不得消费潜在字节；predicate 只用于已完整读取 request body 的 job。

- [x] **Step 2: 限定为非流式 job 并提供 session callback**

  增加：

  ```c
  static bool server_job_client_disconnected(const job *j) {
      return j && !j->req.stream && server_client_disconnected(j->fd);
  }

  static bool server_job_cancel_cb(void *ud) {
      return server_job_client_disconnected((const job *)ud);
  }
  ```

  流式请求继续使用既有 SSE keepalive/write-failure 路径，避免扩大协议行为变化。

- [x] **Step 3: 出队后丢弃已断连 job**

  在 `worker_main()` 调用 `server_worker_active_call_set()` 前探测。命中时：

  - 记录 `finish="cancelled"`、`status=DS4_CALL_CANCELLED`、`output_tokens=0`；
  - error detail 使用 `client disconnected while queued`；
  - 不设置 active call，不调用 `generate_job()`；
  - 仍锁定 `j->mu`、设置 `j->done=true` 并 signal，让 client thread 释放 request 与 fd。

- [x] **Step 4: active job 安装并无条件清除 callback**

  `generate_job()` 前仅为非流式 job 调用：

  ```c
  ds4_session_set_cancel(s->session, server_job_cancel_cb, j);
  ```

  `generate_job()` 返回后、清 active id 和 signal 前无条件调用：

  ```c
  ds4_session_set_cancel(s->session, NULL, NULL);
  ```

  这是必要的生命周期约束：`job` 由 client thread 栈持有，callback 不能跨 job 留下悬空指针。

- [x] **Step 5: cancelled 使用独立 terminal 状态并保留原因**

  在 `ds4_call_status` 增加 `DS4_CALL_CANCELLED`，`call_status_name()` 输出 `cancelled`，caller aggregate 只把 `DS4_CALL_FAILED` 计入 failures。`server_status` 增加 `cancelled_requests`，`server_status_finish_request()` 对 `error`、`cancelled`、其他完成状态分别计数；status JSON 的 `totals` 增加 `"cancelled"` 字段。`server_finalize_call_history()` 将 finish=`cancelled` 映射到新 enum 并保留 detail，不得把取消伪装成模型推理错误。

- [x] **Step 6: 验证 GREEN**

  Run: `make ds4_test && ./ds4_test --server`

  Expected: PASS，输出 `server: OK` 和 `ds4 tests: ok`。

### Task 3: 接通 prefill/decode 协作取消并保护 session/KV

**Files:**

- Modify: `ds4_server.c`（`generate_job()` 的两个 sync 分支、decode loop 与最终响应路径）

- [x] **Step 0: 先添加 active-cancel 共同清理的 RED 测试**

  以 session=`NULL` 的最小 server 初始化 KV、tool、status 和 call-history mutex，预置 continued frontier 与三种 live binding；调用待实现的 active-cancel helper，断言 continued frontier 清零、live binding 全清、history/status 为独立 `cancelled` 且不增加 completed/failed。Run: `make ds4_test`；Expected: FAIL with helper missing。

- [x] **Step 1: 为两处 prefill sync 保存返回码**

  将 cold-prefix 和 full-prompt 的 `ds4_session_sync()` 结果保存为 `sync_rc`。当结果为 `DS4_SESSION_SYNC_INTERRUPTED` 且 predicate 为真时，进入专用 cancelled 分支；其他非零结果保留既有 prefill failure 行为。

- [x] **Step 2: prefill 取消执行完整安全清理**

  cancelled 分支必须按以下顺序处理：

  ```c
  ds4_session_set_progress(s->session, NULL, NULL);
  ds4_session_set_display_progress(s->session, NULL, NULL);
  server_kv_restore_suppressed_continued(s, suppressed_continued_last,
                                         cold_store_len);
  ds4_session_invalidate(s->session);
  server_kv_reset_continued_store(s);
  responses_live_clear(s);
  anthropic_live_clear(s);
  thinking_live_clear(s);
  ```

  随后 free `prefix`（若存在）、`disk_cache_path`、`effective_prompt`，记录 history/status 为 `cancelled` 并 return。严禁调用 `server_kv_discard_failed_disk_entry()`，因为 interruption 不代表磁盘快照损坏。

- [x] **Step 3: sync 成功后立即再次探测**

  cold-prefix sync 和 full-prompt sync 返回 0 后都再调用一次 predicate。Metal 冷短 layer-major、CPU cold prefill 和 distributed path 可能不在执行中读取 callback；成功后的探测负责覆盖这些路径。

- [x] **Step 4: decode token 边界主动探测**

  在 decode `while` 顶部、`server_kv_maybe_store_continued()` 之前探测；在一次 MTP speculative eval 返回后也再次探测。命中时设置：

  ```c
  finish = "cancelled";
  snprintf(err, sizeof(err), "client disconnected during decode");
  ```

  并停止 decode。这样普通 decode 最多多执行一个 token，MTP 最多多执行一个 speculative batch。

- [x] **Step 5: cancelled 跳过所有后处理和响应**

  在 DSML repair 前、解析前和最终响应前再次探测并保持 `final_finish="cancelled"`。cancelled 路径必须：

  - 跳过 DSML repair、tool parse/canonicalize、Responses/Anthropic/thinking live remember；
  - invalidate session 并 reset continued-store frontier；
  - 清除所有协议 live binding；
  - 不调用任何 SSE/final response writer；
  - 仍通过统一 cleanup free stream state、parsed buffers、text 和 effective prompt；
  - history/status 记录实际已产生的 `completion` 与取消阶段原因。

- [x] **Step 6: 记录非流式最终 write 的真实结果**

  将三个被忽略的返回值赋给 `response_ok`：

  ```c
  response_ok = anthropic_final_response(...);
  response_ok = responses_final_response(...);
  response_ok = final_response(...);
  ```

  覆盖最后一次 predicate 与最终 write 之间的断连竞态；write 失败继续按既有 `error` 规则记录。

- [x] **Step 7: 运行聚焦回归**

  Run: `make ds4_test && ./ds4_test --server`

  Expected: PASS；无新增 compiler warning（Metal SDK 既有 deprecated warning 除外）。

### Task 4: 文档、静态检查与完整验证

**Files:**

- Create: `docs/openhanako-memory-timeout-analysis.md`
- Modify: `docs/superpowers/plans/2026-07-16-http-client-disconnect-cancellation.md`（勾选完成项）

- [x] **Step 1: 落盘中文根因与修复说明**

  文档需包含：16 个 Hana memory 请求全部 60 秒超时但 DS4 继续生成 26,220 token 的证据、根因链、P0 实现、session/KV 清理、单请求 EOF 契约、未读取用户正文的隐私边界。

- [x] **Step 2: 运行格式和差异检查**

  Run: `git diff --check`

  Expected: 无输出，exit 0。

  Run: `git diff --stat && git status --short`

  Expected: 仅出现本计划范围内的 `ds4_server.c`、`ds4_call_history.h` 与两个中文文档。

- [x] **Step 3: 运行 CPU 构建验证**

  Run: `make cpu`

  Expected: exit 0，生成 CPU 版本二进制；不启动模型推理。

- [x] **Step 4: 运行完整测试目标的安全子集**

  Run: `./ds4_test --server`

  Expected: PASS。

  `make test` 默认执行 `--all`，会触发真实大模型/Metal 长上下文测试。早期验证时已有 DS4 大模型实例运行；最终重跑前该实例虽已自然退出，但本修复没有仅为 HTTP 生命周期验证重新加载巨大模型。以从干净产物构建的 Metal server 测试、生产 server 编译、CPU build、第二轮 server 测试和静态检查作为本次无模型验证，并把真实 Hana/Metal 运行验证保留为明确后续项。

- [x] **Step 5: 两阶段审查**

  先做 spec compliance review，逐项确认排队、prefill、decode、KV、history/status 与 EOF 契约；通过后再做 code quality review，重点检查 callback 生命周期、所有 early return、取消竞态、资源释放和未相关改动。

  最终完整 diff 审查未发现 Critical 或 Important 问题；保留的 Minor 风险是无模型测试无法实际驱动生产 worker 的 callback 安装/清除，以及真实 Hana/Metal 取消路径仍待运行验证。
