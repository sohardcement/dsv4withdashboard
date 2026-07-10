# 中文看板：Context、调用详情与主机资源实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 DS4 看板中增加可切换中文主题、Context 状态与下次启动设置、可信直连 IP 的内存调用历史，以及主机内存/Swap/进程 RSS 指标。

**Architecture:** 将平台主机采样和调用环形历史拆成小型 C99 模块；`ds4_server.c` 只负责将请求生命周期、状态快照和管理路由连接起来。`/ds4/status` 以复制后的快照返回 `context`、`host` 与 `calls`；前端在同一单页中按本地主题 token 渲染这些字段，所有服务数据均使用安全 DOM 节点写入。

**Tech Stack:** C99、POSIX/pthreads、macOS Mach/sysctl、Linux `/proc` 回退、Bash、嵌入式 HTML/CSS/JavaScript、现有 C 测试和 Playwright dashboard harness。

---

## 文件结构

- Create `ds4_host_metrics.h`：跨平台主机资源快照的公共 C99 类型和采样 API。
- Create `ds4_host_metrics.c`：macOS Mach/sysctl 与 Linux `/proc` 实现。
- Create `ds4_call_history.h`：调用记录、聚合和固定容量历史 API。
- Create `ds4_call_history.c`：有界内存历史和 caller 聚合实现。
- Modify `Makefile`：将两个新对象加入 server、测试和 CPU 目标。
- Modify `ds4_server.c`：采集 peer 地址、接入调用历史/host 缓存、Context 管理接口、状态 JSON 和中文三主题页面。
- Modify `start-server.sh`：读取并校验 `DS4_CTX_FILE` 的 next-start Context 值。
- Modify `docs/agent-kv-cache-tuning.md`：说明 Context、调用历史、主题和主机资源口径。
- Modify `tests/dashboard_fixture.py`、`tests/dashboard_ui_test.js`、`tests/run_dashboard_ui_test.sh`：保持可提交的中文看板行为测试。

### Task 1: 主机资源快照模块

**Files:**
- Create: `ds4_host_metrics.h`
- Create: `ds4_host_metrics.c`
- Modify: `Makefile`
- Test: `ds4_server.c` 的 `DS4_SERVER_TEST` 区域

- [ ] **Step 1: 写失败测试**

在 server 单元测试中增加一个 deterministic 的平台无关格式测试，使用测试构造的 `ds4_host_metrics`：

```c
static void test_host_metrics_snapshot_has_truthful_unknowns(void) {
    ds4_host_metrics m = {0};
    m.memory_total_bytes = 128ull << 30;
    m.memory_used_bytes = 64ull << 30;
    m.memory_available_bytes = 64ull << 30;
    m.swap_total_bytes = 16ull << 30;
    m.swap_used_bytes = 0;
    m.process_rss_bytes = 58ull << 30;
    m.pressure = DS4_HOST_PRESSURE_NORMAL;
    TEST_ASSERT(!strcmp(ds4_host_pressure_name(m.pressure), "normal"));
    TEST_ASSERT(!strcmp(ds4_host_pressure_name(DS4_HOST_PRESSURE_UNKNOWN), "unknown"));
}
```

- [ ] **Step 2: 验证 RED**

Run: `make ds4_test && ./ds4_test --server`

Expected: 编译失败，因为 `ds4_host_metrics` 和压力名称 API 尚不存在。

- [ ] **Step 3: 实现类型和采样 API**

在头文件定义：

```c
typedef enum {
    DS4_HOST_PRESSURE_UNKNOWN,
    DS4_HOST_PRESSURE_NORMAL,
    DS4_HOST_PRESSURE_WARNING,
    DS4_HOST_PRESSURE_CRITICAL,
} ds4_host_pressure;

typedef struct {
    uint64_t memory_total_bytes;
    uint64_t memory_used_bytes;
    uint64_t memory_available_bytes;
    uint64_t swap_total_bytes;
    uint64_t swap_used_bytes;
    uint64_t process_rss_bytes;
    ds4_host_pressure pressure;
    double sampled_at;
    bool available;
} ds4_host_metrics;

bool ds4_host_metrics_sample(ds4_host_metrics *out);
const char *ds4_host_pressure_name(ds4_host_pressure pressure);
```

在 macOS 使用 `sysctlbyname("hw.memsize")`、`host_statistics64`、`vm.swapusage` 和 `task_info(mach_task_self(), TASK_BASIC_INFO_64, ...)`。在 Linux 读取 `/proc/meminfo` 的 `MemTotal`、`MemAvailable`、`SwapTotal`、`SwapFree` 和 `/proc/self/status` 的 `VmRSS`；若 `/proc/pressure/memory` 可读取，按 `some avg10` 的阈值映射 `warning`/`critical`，否则 `unknown`。任何不可用字段保留 0 且 `available=false`，绝不伪造值。

将 `ds4_host_metrics.o` 加入 `ds4-server`、`ds4_test`、`ds4_server_cpu.o` 的链接依赖。

- [ ] **Step 4: 验证 GREEN**

Run: `make ds4_test && ./ds4_test --server && make cpu`

Expected: server 测试通过；CPU 构建无新 warning。

- [ ] **Step 5: Commit**

```bash
git add ds4_host_metrics.h ds4_host_metrics.c Makefile ds4_server.c
git commit -m "server: add host resource metrics"
```

### Task 2: 有界调用历史与调用方聚合

**Files:**
- Create: `ds4_call_history.h`
- Create: `ds4_call_history.c`
- Modify: `Makefile`
- Modify: `ds4_server.c`
- Test: `ds4_server.c`

- [ ] **Step 1: 写失败测试**

创建容量为 2 的历史，记录两个完成请求和一个活动请求，验证最旧完成项被淘汰、活动项保留、caller 聚合正确：

```c
static void test_call_history_evicts_only_completed_records(void) {
    ds4_call_history h = {0};
    ds4_call_history_init(&h, 2);
    uint64_t a = ds4_call_history_begin(&h, "127.0.0.1", "openai", "chat", 1.0);
    uint64_t b = ds4_call_history_begin(&h, "::1", "responses", "chat", 2.0);
    ds4_call_history_finish(&h, a, 1.2, 10, 3, 2, "disk-text", "stop", NULL);
    uint64_t c = ds4_call_history_begin(&h, "127.0.0.1", "anthropic", "chat", 3.0);
    TEST_ASSERT(ds4_call_history_count(&h) == 2);
    TEST_ASSERT(ds4_call_history_find(&h, b) != NULL);
    TEST_ASSERT(ds4_call_history_find(&h, c) != NULL);
    ds4_call_history_free(&h);
}
```

- [ ] **Step 2: 验证 RED**

Run: `make ds4_test && ./ds4_test --server`

Expected: 缺少调用历史 API 的编译错误。

- [ ] **Step 3: 实现调用历史模块**

定义固定上限 `DS4_CALL_HISTORY_CAPACITY 200`。每条 `ds4_call_record` 包含 `request_id`、caller、api、kind、stream/tools、开始/结束时间、prompt/cached/cache_write/output token、cache source、finish、error、状态。`ds4_call_history_begin` 分配单调 request ID；满时只移除最旧的 completed/failed 记录，若全部活动则允许临时超出上限，直到出现可移除记录。

实现 `ds4_call_history_snapshot`，把记录复制到调用者拥有的数组，并构造按 caller 聚合数组：calls、failed、总 prompt/cached token、平均完成耗时、最近活动时间。调用方文本长度固定为 64；错误截断到 160 字节。

- [ ] **Step 4: 捕获 TCP peer 并接入 worker 生命周期**

在 `client_main` 的 request 解析后、入队前，使用 `getpeername` 与 `inet_ntop` 写入 `job.caller`。不读取 `X-Forwarded-For`/`Forwarded`。`AF_UNIX` 显示 `local`，失败显示 `unknown`。

给 `server` 增加 `pthread_mutex_t call_history_mu` 和 `ds4_call_history calls`。在 job 入队后调用 begin；在 worker 已确定 prompt/cache 后更新记录 token/cache source；在完成、失败或中断路径调用 finish。所有 early error 在尚未 begin 时不创建记录。

- [ ] **Step 5: 验证 GREEN**

Run: `make ds4_test && ./ds4_test --server`

Expected: 环形淘汰、聚合、IPv4/IPv6/local fallback 和完成/失败更新测试通过。

- [ ] **Step 6: Commit**

```bash
git add ds4_call_history.h ds4_call_history.c Makefile ds4_server.c
git commit -m "server: track recent API callers"
```

### Task 3: 状态快照中的 Context、Calls 和 Host

**Files:**
- Modify: `ds4_server.c`
- Test: `ds4_server.c`

- [ ] **Step 1: 写失败 JSON 测试**

构造含 host/call snapshot 的 server，断言新增 JSON 字段和口径：

```c
TEST_ASSERT(strstr(out.ptr, "\"context\":{\"current_tokens\":12") != NULL);
TEST_ASSERT(strstr(out.ptr, "\"remaining_tokens\":116") != NULL);
TEST_ASSERT(strstr(out.ptr, "\"host\":{\"available\":true") != NULL);
TEST_ASSERT(strstr(out.ptr, "\"calls\":{\"capacity\":200") != NULL);
TEST_ASSERT(strstr(out.ptr, "\"caller\":\"127.0.0.1\"") != NULL);
TEST_ASSERT(strstr(out.ptr, "x-forwarded-for") == NULL);
```

- [ ] **Step 2: 验证 RED**

Run: `make ds4_test && ./ds4_test --server`

Expected: status JSON 不包含新增对象，断言失败。

- [ ] **Step 3: 增加采样缓存和序列化**

在 `server` 中保存 `host_metrics` 与 `host_metrics_mu`。实现 `server_host_get_snapshot`：若上一次采样不到 1 秒，返回复制缓存；否则在不持有 status/KV/call-history mutex 时调用 `ds4_host_metrics_sample`，再短暂持锁发布。`send_status_json` 依次复制 status、published KV、host 和 calls，任何两个 mutex 不同时持有。

状态 JSON 增加：

```json
"context":{"current_tokens":0,"limit_tokens":0,"remaining_tokens":0,"utilization":0},
"host":{"available":false,"memory_pressure":"unknown",...},
"calls":{"capacity":200,"active_request_id":0,"records":[],"callers":[]}
```

所有 token/byte 数用 JSON 整数；timestamp 用秒数；不存在值使用 `null` 或已有 `unknown` 字符串。

- [ ] **Step 4: 验证 GREEN**

Run: `make ds4_test && ./ds4_test --server && git diff --check`

Expected: 新旧 status 字段兼容，新增对象和锁顺序测试通过。

- [ ] **Step 5: Commit**

```bash
git add ds4_server.c
git commit -m "server: expose context calls and host status"
```

### Task 4: Context 下次启动配置与安全管理接口

**Files:**
- Modify: `ds4_server.c`
- Modify: `start-server.sh`
- Test: `ds4_server.c`

- [ ] **Step 1: 写失败 Context 配置与路由测试**

仿照 KV admin 测试，覆盖保存、路径 override、loopback/header 拒绝、非法值和 route 语义：

```c
TEST_ASSERT(context_admin_parse_request(
    "{\"context_tokens\":131072}", strlen("{\"context_tokens\":131072}"), &req, &err));
TEST_ASSERT(req.context_tokens == 131072);
TEST_ASSERT(!context_admin_parse_request(
    "{\"context_tokens\":4095}", strlen("{\"context_tokens\":4095}"), &req, &err));
TEST_ASSERT(!context_admin_parse_request(
    "{\"context_tokens\":1e6}", strlen("{\"context_tokens\":1e6}"), &req, &err));
```

创建 loopback TCP request，验证 `POST /ds4/admin/context` 带 `X-DS4-Admin: 1` 成功；AF_UNIX 或缺失 header 返回 403 且不写文件。

- [ ] **Step 2: 验证 RED**

Run: `make ds4_test && ./ds4_test --server`

Expected: 缺少 Context parser/route 的编译或断言失败。

- [ ] **Step 3: 实现原子 Context 保存**

复用 KV admin 的已验证安全结构，但使用独立的 `context_admin_*` 名称和 `${DS4_CTX_FILE:-$HOME/.ds4/context-tokens}`。请求 JSON 严格只接受 `context_tokens` 十进制整数，范围 `[4096, INT_MAX]`。禁止 CORS，要求 loopback、`application/json` 和 `X-DS4-Admin: 1`；在读 body 前检查这些条件和 4096-byte 上限。

持久化响应：

```json
{"ok":true,"current_context_tokens":131072,"next_context_tokens":262144,
 "persistent":{"attempted":true,"ok":true,"committed":true,"durable":true}}
```

写入流程采用同目录 0600 临时文件、`fflush`、file `fsync`、`rename`、directory `fsync`，并区分 committed/durable。不得更改 `s->session` 或当前 Context。

- [ ] **Step 4: 让启动脚本读取保存值**

在 profile 选择后增加 `CTX_FILE=${DS4_CTX_FILE:-$HOME/.ds4/context-tokens}`，拒绝 CR/LF 路径，读取有效 `[4096,2147483647]` 十进制值。优先级为有效 `DS4_CTX`、保存值、profile default；显式无效/空 `DS4_CTX` 给出警告并回退保存值/default。将 `ctx_file` 和有效 `ctx` 记入 config snapshot。

- [ ] **Step 5: 验证 GREEN**

Run:

```bash
make ds4_test && ./ds4_test --server
bash -n start-server.sh
tmp=$(mktemp -d)
mkdir -p "$tmp/.ds4"
printf '262144\n' > "$tmp/.ds4/context-tokens"
HOME="$tmp" DS4_MODEL= DS4_DRY_RUN=1 ./start-server.sh
HOME="$tmp" DS4_MODEL= DS4_CTX=131072 DS4_DRY_RUN=1 ./start-server.sh
rm -rf "$tmp"
```

Expected: dry-run first emits `--ctx 262144`, second emits `--ctx 131072`; server tests pass.

- [ ] **Step 6: Commit**

```bash
git add ds4_server.c start-server.sh
git commit -m "server: save next-start context limit"
```

### Task 5: 中文三主题看板与调用详情交互

**Files:**
- Modify: `ds4_server.c`
- Modify: `tests/dashboard_fixture.py`
- Modify: `tests/dashboard_ui_test.js`
- Modify: `tests/run_dashboard_ui_test.sh`

- [ ] **Step 1: 写失败 dashboard 契约测试**

扩展 `test_dashboard_page_is_served_as_html`：

```c
TEST_ASSERT(strstr(out, "data-theme=\"paper\"") != NULL);
TEST_ASSERT(strstr(out, "data-theme=\"terminal\"") != NULL);
TEST_ASSERT(strstr(out, "data-theme=\"calm\"") != NULL);
TEST_ASSERT(strstr(out, "id=\"contextCurrent\"") != NULL);
TEST_ASSERT(strstr(out, "id=\"callHistory\"") != NULL);
TEST_ASSERT(strstr(out, "id=\"hostMemory\"") != NULL);
TEST_ASSERT(strstr(out, "/ds4/admin/context") != NULL);
```

- [ ] **Step 2: 验证 RED**

Run: `make ds4_test && ./ds4_test --server`

Expected: 主题、Context、调用和主机 DOM hooks 断言失败。

- [ ] **Step 3: 实现主题、中文文案和状态渲染**

保留 A 主题作为默认 `paper`，并加入 `terminal`、`calm` CSS token。主题按钮使用 `data-theme`，`localStorage["ds4-dashboard-theme"]` 保存选择；非法/缺失值回退 `paper`。三主题同样显示 phase/error/disabled 状态。

新增 Context 区显示当前/上限、剩余和利用率；Context 保存表单 `contextNextInput` 使用 JSON POST 和 `X-DS4-Admin: 1`，成功文案明确“下次启动生效，需要重启”。新增 host 区显示整机已用/总量、可用、压力、Swap、DS4 RSS；`unknown`/`null` 输出中文“不可用”。

调用详情使用 `document.createElement` 和 `textContent` 创建行，默认最近记录；前端过滤器为 caller、API、结果。caller 聚合显示“最近 200 条窗口”。不得把服务字段拼接进 `innerHTML`。

- [ ] **Step 4: 扩展可提交的浏览器 fixture/harness**

在 fixture 加入 `context`、`host`、`calls` 样例和 `/ds4/admin/context` 的成功/403/持久化失败响应。Playwright 测试必须断言：

- 三主题切换后 `data-theme` 与 localStorage 一致；
- 中文 desktop 1440x900 与 mobile 390x844 无横向溢出；
- Context 保存发送管理员 header，成功后显示重启提示；
- 调用方过滤只保留匹配记录，错误/恶意 caller 文本作为纯文本显示；
- host unknown、Swap 和 offline stale 状态正确；
- 控制台没有非故意网络错误。

- [ ] **Step 5: 验证 GREEN**

Run:

```bash
make ds4_test && ./ds4_test --server
./tests/run_dashboard_ui_test.sh
node --check tests/dashboard_ui_test.js
```

Expected: C 契约和浏览器状态机测试通过。

- [ ] **Step 6: Commit**

```bash
git add ds4_server.c tests/dashboard_fixture.py tests/dashboard_ui_test.js tests/run_dashboard_ui_test.sh
git commit -m "server: add Chinese dashboard themes"
```

### Task 6: 文档与完整验证

**Files:**
- Modify: `docs/agent-kv-cache-tuning.md`

- [ ] **Step 1: 更新运行手册**

增加“中文看板与调用历史”章节，明确三主题、localStorage、Context next-start 文件/环境优先级、调用历史仅内存/200 条/直连 IP、主机指标口径和平台 unavailable 行为。

- [ ] **Step 2: 运行完整可用验证**

Run:

```bash
git diff --check main..HEAD
make ds4_test && ./ds4_test --server
./tests/run_dashboard_ui_test.sh
bash -n start-server.sh
make cpu
```

按环境允许情况运行 `make test`；若官方向量 GGUF 不匹配，记录该夹具差异，不把它归因于本变更。不得同时启动多个大模型进程。

- [ ] **Step 3: 对照规格复核**

逐项检查 `docs/superpowers/specs/2026-07-11-dashboard-context-calls-host-design.md` 的主题、Context、调用、host、安全、兼容与测试要求。任何缺口必须先写失败测试再修复。

- [ ] **Step 4: Commit**

```bash
git add docs/agent-kv-cache-tuning.md
git commit -m "docs: explain dashboard context and call history"
```
