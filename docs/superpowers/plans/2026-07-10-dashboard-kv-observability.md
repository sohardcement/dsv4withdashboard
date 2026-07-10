# Dashboard KV Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an editorial DS4 runtime dashboard with current and process-lifetime KV hit metrics, honest cache capacity reporting, and loopback-only controls for changing the disk KV budget now or on restart.

**Architecture:** Keep the embedded single-page dashboard in `ds4_server.c`, extend its status snapshot, and add a small JSON admin route. Add pure accounting and budget-change operations to `ds4_kvstore`; serialize server access with a dedicated `kv_mu`, while process counters remain under `status_mu`. Persist the next-start limit as one numeric file under `$HOME/.ds4`, with `DS4_KV_SPACE` retaining highest precedence.

**Tech Stack:** C99, POSIX sockets/filesystem/pthreads, embedded HTML/CSS/JavaScript, Bash, existing C test macros and `make test` workflow.

---

## File Structure

- Modify `ds4_kvstore.h`: public cache stats and budget-change result types and functions.
- Modify `ds4_kvstore.c`: indexed byte accounting, budget dry-run/apply behavior.
- Modify `ds4_server.c`: cumulative metrics, KV locking, status JSON, loopback admin endpoint, persistence helper, redesigned dashboard, and server unit tests.
- Modify `start-server.sh`: load the saved next-start KV budget below explicit environment precedence.
- Modify `docs/agent-kv-cache-tuning.md`: document status metrics, capacity controls, persistence, and loopback restriction.

### Task 1: KV Store Stats Snapshot

**Files:**
- Modify: `ds4_kvstore.h`
- Modify: `ds4_kvstore.c`
- Test: `ds4_server.c` in the existing `DS4_SERVER_TEST` section

- [ ] **Step 1: Write the failing stats test**

Add a test beside the existing KV eviction tests. Populate an enabled in-memory store with two indexed entries and assert exact byte and entry totals:

```c
static void test_kvstore_stats_sum_indexed_files(void) {
    ds4_kvstore kc = {0};
    kc.enabled = true;
    kc.budget_bytes = 1024;
    kc.len = 2;
    kc.cap = 2;
    kc.entry = calloc(2, sizeof(kc.entry[0]));
    kc.entry[0].file_size = 100;
    kc.entry[1].file_size = 250;

    ds4_kvstore_stats stats = ds4_kvstore_get_stats(&kc);
    TEST_ASSERT(stats.enabled);
    TEST_ASSERT(stats.budget_bytes == 1024);
    TEST_ASSERT(stats.used_bytes == 350);
    TEST_ASSERT(stats.entries == 2);

    ds4_kvstore_clear(&kc);
}
```

Register the test in the server test runner.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `make ds4_server_test && ./ds4_server_test`

Expected: compilation fails because `ds4_kvstore_stats` and `ds4_kvstore_get_stats` do not exist.

- [ ] **Step 3: Add the stats API**

Add to `ds4_kvstore.h`:

```c
typedef struct {
    bool enabled;
    uint64_t budget_bytes;
    uint64_t used_bytes;
    uint64_t entries;
} ds4_kvstore_stats;

ds4_kvstore_stats ds4_kvstore_get_stats(const ds4_kvstore *kc);
```

Implement in `ds4_kvstore.c` with saturating addition so corrupt/extreme metadata cannot wrap:

```c
ds4_kvstore_stats ds4_kvstore_get_stats(const ds4_kvstore *kc) {
    ds4_kvstore_stats out = {0};
    if (!kc) return out;
    out.enabled = kc->enabled;
    out.budget_bytes = kc->budget_bytes;
    out.entries = kc->len > 0 ? (uint64_t)kc->len : 0;
    for (int i = 0; i < kc->len; i++) {
        uint64_t n = kc->entry[i].file_size;
        out.used_bytes = UINT64_MAX - out.used_bytes < n ?
            UINT64_MAX : out.used_bytes + n;
    }
    return out;
}
```

- [ ] **Step 4: Run the test and verify GREEN**

Run: `make ds4_server_test && ./ds4_server_test`

Expected: all server unit tests pass.

- [ ] **Step 5: Commit**

```bash
git add ds4_kvstore.h ds4_kvstore.c ds4_server.c
git commit -m "kvstore: expose indexed capacity stats"
```

### Task 2: Runtime KV Budget Dry-Run and Apply

**Files:**
- Modify: `ds4_kvstore.h`
- Modify: `ds4_kvstore.c`
- Test: `ds4_server.c`

- [ ] **Step 1: Write failing growth and shrink tests**

Create real temporary cache files so eviction behavior is exercised, not mocked. Add assertions for no eviction on growth and exact before/after counts on shrink:

```c
static void test_kvstore_budget_change_reports_and_evicts(void) {
    char dir[] = "/tmp/ds4-budget-test-XXXXXX";
    TEST_ASSERT(mkdtemp(dir) != NULL);
    ds4_kvstore kc = {0};
    kc.enabled = true;
    kc.dir = strdup(dir);
    kc.budget_bytes = 1000;
    test_kvstore_add_sized_file(&kc, dir, 'a', 400, 1024, 0);
    test_kvstore_add_sized_file(&kc, dir, 'b', 400, 2048, 0);

    ds4_kvstore_budget_result dry =
        ds4_kvstore_set_budget(&kc, 500, false);
    TEST_ASSERT(dry.ok && dry.eviction_required);
    TEST_ASSERT(dry.before_entries == 2 && dry.after_entries == 2);
    TEST_ASSERT(kc.budget_bytes == 1000);

    ds4_kvstore_budget_result applied =
        ds4_kvstore_set_budget(&kc, 500, true);
    TEST_ASSERT(applied.ok && applied.eviction_required);
    TEST_ASSERT(applied.after_bytes <= 500);
    TEST_ASSERT(applied.after_entries < applied.before_entries);
    TEST_ASSERT(kc.budget_bytes == 500);

    ds4_kvstore_budget_result grown =
        ds4_kvstore_set_budget(&kc, 2000, true);
    TEST_ASSERT(grown.ok && !grown.eviction_required);
    TEST_ASSERT(grown.before_entries == grown.after_entries);
    ds4_kvstore_close(&kc);
    rmdir(dir);
}
```

Use an existing KV fixture helper if one already creates valid cache files; otherwise add a focused `test_kvstore_add_sized_file` helper beside these tests that writes valid headers and payloads.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `make ds4_server_test && ./ds4_server_test`

Expected: compilation fails because the budget result and setter do not exist.

- [ ] **Step 3: Add the budget result and operation**

Add to `ds4_kvstore.h`:

```c
typedef struct {
    bool ok;
    bool applied;
    bool eviction_required;
    uint64_t old_budget_bytes;
    uint64_t new_budget_bytes;
    uint64_t before_bytes;
    uint64_t after_bytes;
    uint64_t before_entries;
    uint64_t after_entries;
} ds4_kvstore_budget_result;

ds4_kvstore_budget_result ds4_kvstore_set_budget(
        ds4_kvstore *kc, uint64_t budget_bytes, bool apply);
```

Implement it by taking a stats snapshot, rejecting disabled stores and zero budgets, returning an unchanged dry-run when `apply == false`, and otherwise assigning `budget_bytes`, calling `ds4_kvstore_evict(kc, NULL, 0, NULL)` when usage exceeds the new budget, then taking the after snapshot.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `make ds4_server_test && ./ds4_server_test`

Expected: all server unit tests pass, including actual file eviction.

- [ ] **Step 5: Commit**

```bash
git add ds4_kvstore.h ds4_kvstore.c ds4_server.c
git commit -m "kvstore: support runtime budget changes"
```

### Task 3: Process-Lifetime Cache Counters and Status JSON

**Files:**
- Modify: `ds4_server.c`
- Test: `ds4_server.c`

- [ ] **Step 1: Write failing status counter tests**

Extend the status JSON test to begin two requests, one cache hit and one miss, and verify raw counters rather than rounded percentages:

```c
static void test_server_status_reports_cache_totals(void) {
    server s = {0};
    pthread_mutex_init(&s.status_mu, NULL);
    server_status_init(&s);
    request hit, miss;
    request_init(&hit, REQ_CHAT, 64);
    request_init(&miss, REQ_CHAT, 64);
    server_status_begin_request(&s, &hit, 75, 100, "disk-text");
    server_status_finish_request(&s, "stop", NULL);
    server_status_begin_request(&s, &miss, 0, 50, "none");
    server_status_finish_request(&s, "stop", NULL);

    buf out = {0};
    append_status_json(&out, &s.status, NULL);
    TEST_ASSERT(strstr(out.p, "\"prompt_tokens\":150") != NULL);
    TEST_ASSERT(strstr(out.p, "\"cached_tokens\":75") != NULL);
    TEST_ASSERT(strstr(out.p, "\"prompt_requests\":2") != NULL);
    TEST_ASSERT(strstr(out.p, "\"hit_requests\":1") != NULL);
    buf_free(&out);
    request_free(&hit);
    request_free(&miss);
    pthread_mutex_destroy(&s.status_mu);
}
```

Also assert that an empty-prompt request does not increase either request denominator.

- [ ] **Step 2: Run and verify RED**

Run: `make ds4_server_test && ./ds4_server_test`

Expected: test fails because totals JSON lacks cache counters.

- [ ] **Step 3: Add raw counters and one-time accounting**

Extend `server_status`:

```c
uint64_t total_prompt_tokens;
uint64_t total_cached_tokens;
uint64_t prompt_requests;
uint64_t cache_hit_requests;
```

In `server_status_begin_request`, use saturating helpers to add `prompt_tokens` and clamped `cached_tokens`; increment `prompt_requests` only when prompt tokens are positive and `cache_hit_requests` only when both prompt and cached tokens are positive. Emit raw values in `totals.cache` so the browser derives ratios without precision loss.

- [ ] **Step 4: Add KV capacity to the same snapshot**

Change the serializer signature to accept a KV snapshot:

```c
static void append_status_json(buf *b, const server_status *st,
                               const ds4_kvstore_stats *kv);
```

Emit:

```json
"kv_cache":{"enabled":true,"budget_bytes":171798691840,"used_bytes":0,"entries":0}
```

When disabled, emit zeros with `enabled:false`. In `send_status_json`, lock `status_mu` to copy status, then lock the new `kv_mu` separately to obtain KV stats; never hold both mutexes simultaneously.

- [ ] **Step 5: Run tests and verify GREEN**

Run: `make ds4_server_test && ./ds4_server_test`

Expected: all server unit tests pass.

- [ ] **Step 6: Commit**

```bash
git add ds4_server.c
git commit -m "server: report KV hit and capacity metrics"
```

### Task 4: Serialize Server KV Access

**Files:**
- Modify: `ds4_server.c`
- Test: `ds4_server.c`

- [ ] **Step 1: Write a failing concurrent snapshot test**

Add a small test thread that repeatedly reads stats while the main thread changes the budget. Assert all snapshots remain internally valid (`used_bytes` is the sum represented by the stable test store and the budget is one of the applied values). This test must call the server locking wrappers, not raw KV functions.

```c
static void test_server_kv_snapshot_serializes_budget_changes(void) {
    server s = {0};
    pthread_mutex_init(&s.kv_mu, NULL);
    s.kv.enabled = true;
    s.kv.budget_bytes = 1024;
    kv_snapshot_test_ctx ctx = {.srv = &s, .ok = true};
    pthread_t reader;
    TEST_ASSERT(pthread_create(&reader, NULL, kv_snapshot_reader, &ctx) == 0);
    for (int i = 0; i < 1000; i++)
        server_kv_set_budget(&s, i & 1 ? 1024 : 2048, false);
    pthread_join(reader, NULL);
    TEST_ASSERT(ctx.ok);
    pthread_mutex_destroy(&s.kv_mu);
}
```

- [ ] **Step 2: Run and verify RED**

Run: `make ds4_server_test && ./ds4_server_test`

Expected: compilation fails because `kv_mu` and server KV wrappers do not exist.

- [ ] **Step 3: Add the dedicated mutex and wrappers**

Add `pthread_mutex_t kv_mu` to `server`, initialize it before opening the KV cache, and destroy it in `server_close_resources`. Wrap all server calls that read or mutate `s->kv`, including open/close, lookup/load, store, continued-store bookkeeping, eviction, stats snapshot, and budget changes.

Use a strict rule: callers invoke `server_kv_*` wrappers and never take `kv_mu` themselves. Each wrapper takes and releases `kv_mu`, preventing nested lock acquisition.

- [ ] **Step 4: Run tests under ThreadSanitizer where available**

Run: `make ds4_server_test && ./ds4_server_test`

Then on clang:

```bash
make clean
make ds4_server_test CFLAGS='-std=c99 -O1 -g -Wall -Wextra -fsanitize=thread'
./ds4_server_test
```

Expected: normal tests pass; the sanitizer run reports no race in the new snapshot/budget test. If the platform runtime cannot launch ThreadSanitizer, record that limitation and retain the deterministic locking test.

- [ ] **Step 5: Commit**

```bash
git add ds4_server.c
git commit -m "server: serialize KV store administration"
```

### Task 5: Loopback-Only Admin API and Persistence

**Files:**
- Modify: `ds4_server.c`
- Test: `ds4_server.c`

- [ ] **Step 1: Write failing parser, authorization, and persistence tests**

Extract admin logic into testable helpers and cover these exact cases:

```c
static void test_kv_admin_request_validation(void) {
    kv_admin_request r = {0};
    char err[128];
    TEST_ASSERT(parse_kv_admin_request(
        "{\"budget_mb\":8192,\"mode\":\"dry-run\"}", &r, err, sizeof(err)));
    TEST_ASSERT(r.budget_bytes == 8192ull * 1024ull * 1024ull);
    TEST_ASSERT(r.mode == KV_ADMIN_DRY_RUN);
    TEST_ASSERT(!parse_kv_admin_request(
        "{\"budget_mb\":0,\"mode\":\"apply\"}", &r, err, sizeof(err)));
    TEST_ASSERT(!parse_kv_admin_request(
        "{\"budget_mb\":1e99,\"mode\":\"apply\"}", &r, err, sizeof(err)));
}

static void test_peer_loopback_detection(void) {
    TEST_ASSERT(sockaddr_is_loopback_ipv4("127.0.0.1"));
    TEST_ASSERT(sockaddr_is_loopback_ipv6("::1"));
    TEST_ASSERT(!sockaddr_is_loopback_ipv4("192.168.1.10"));
}

static void test_persist_kv_budget_atomic_file(void) {
    char dir[] = "/tmp/ds4-admin-config-XXXXXX";
    TEST_ASSERT(mkdtemp(dir) != NULL);
    char path[PATH_MAX];
    snprintf(path, sizeof(path), "%s/kv-space-mb", dir);
    char err[128];
    TEST_ASSERT(persist_kv_budget_mb(path, 8192, err, sizeof(err)));
    TEST_ASSERT(test_read_uint_file(path) == 8192);
    unlink(path);
    rmdir(dir);
}
```

- [ ] **Step 2: Run and verify RED**

Run: `make ds4_server_test && ./ds4_server_test`

Expected: compilation fails because the request type and helpers do not exist.

- [ ] **Step 3: Implement strict request parsing and loopback detection**

Define modes `dry-run`, `apply`, and `persist`. Require one integer `budget_mb`, reject unknown modes, reject unknown top-level fields, and enforce a documented minimum of 256 MiB and the multiplication overflow bound `UINT64_MAX / (1024 * 1024)`.

Implement `peer_is_loopback(fd)` with `getpeername`, accepting only `AF_INET` address `INADDR_LOOPBACK` and `AF_INET6` address `IN6_IS_ADDR_LOOPBACK`.

- [ ] **Step 4: Implement atomic persistence**

Resolve the default path as `$HOME/.ds4/kv-space-mb`. Ensure the parent directory exists with mode `0700`, write `<decimal>\n` to a same-directory temporary file with mode `0600`, call `fflush` and `fsync`, then `rename`. Return an explicit error string on every failure and unlink the temporary file.

- [ ] **Step 5: Add the route and response contract**

Handle only `POST /ds4/admin/kv-cache`. Before parsing or mutating, require loopback and `Content-Type: application/json`. Return JSON with this stable shape:

```json
{
  "ok": true,
  "mode": "apply",
  "runtime": {
    "attempted": true,
    "ok": true,
    "old_budget_bytes": 171798691840,
    "new_budget_bytes": 85899345920,
    "before_bytes": 45634027520,
    "after_bytes": 45634027520,
    "before_entries": 12,
    "after_entries": 12,
    "eviction_required": false
  },
  "persistent": {"attempted": false, "ok": false, "error": ""}
}
```

Use HTTP 400 for malformed input, 403 for non-loopback peers, 409 for a disabled KV store on runtime apply, and 500 only for internal/persistence failures. A successful runtime change plus failed persistence returns HTTP 200 with top-level `ok:false` and both sub-results, preserving the successful runtime fact.

- [ ] **Step 6: Add socket-level route tests and verify GREEN**

Use `socketpair` for JSON response formatting and direct helper injection for loopback authorization because Unix-domain socket pairs are not loopback TCP peers. Assert status codes and response fields for dry-run, apply-disabled, malformed sizes, and persistence failure.

Run: `make ds4_server_test && ./ds4_server_test`

Expected: all server unit tests pass.

- [ ] **Step 7: Commit**

```bash
git add ds4_server.c
git commit -m "server: add local KV capacity controls"
```

### Task 6: Persisted Start-Script Override

**Files:**
- Modify: `start-server.sh`
- Modify: `docs/agent-kv-cache-tuning.md`
- Test: shell commands using `DS4_DRY_RUN=1`

- [ ] **Step 1: Verify the missing behavior**

Run with an isolated home:

```bash
tmp=$(mktemp -d)
mkdir -p "$tmp/.ds4"
printf '12288\n' > "$tmp/.ds4/kv-space-mb"
HOME="$tmp" DS4_DRY_RUN=1 DS4_MODEL= ./start-server.sh
```

Expected before implementation: output still contains the profile default after `--kv-disk-space-mb`, not `12288`.

- [ ] **Step 2: Load the persisted override below environment precedence**

Add after profile selection and before `KV_SPACE` assignment:

```bash
KV_SPACE_FILE=${DS4_KV_SPACE_FILE:-$HOME/.ds4/kv-space-mb}
SAVED_KV_SPACE=
if [ -r "$KV_SPACE_FILE" ]; then
    IFS= read -r SAVED_KV_SPACE < "$KV_SPACE_FILE" || true
    if [[ ! "$SAVED_KV_SPACE" =~ ^[0-9]+$ ]] || [ "$SAVED_KV_SPACE" -lt 256 ]; then
        echo "ignoring invalid KV cache limit in $KV_SPACE_FILE" >&2
        SAVED_KV_SPACE=
    fi
fi
KV_SPACE=${DS4_KV_SPACE:-${SAVED_KV_SPACE:-$DEFAULT_KV_SPACE}}
```

Remove the earlier direct `KV_SPACE=${DS4_KV_SPACE:-$DEFAULT_KV_SPACE}` assignment and add `kv_space_file` to the config snapshot.

- [ ] **Step 3: Verify saved, environment, and invalid precedence**

Run:

```bash
HOME="$tmp" DS4_DRY_RUN=1 DS4_MODEL= ./start-server.sh
HOME="$tmp" DS4_DRY_RUN=1 DS4_MODEL= DS4_KV_SPACE=4096 ./start-server.sh
printf 'invalid\n' > "$tmp/.ds4/kv-space-mb"
HOME="$tmp" DS4_DRY_RUN=1 DS4_MODEL= ./start-server.sh
rm -rf "$tmp"
```

Expected: the three commands use `12288`, `4096`, and the profile default respectively.

- [ ] **Step 4: Document behavior**

Add a “Dashboard capacity controls” section explaining current vs process-lifetime hit rates, actual indexed disk bytes, live token/context utilization, the 256 MiB minimum, immediate eviction semantics, saved path, `DS4_KV_SPACE` precedence, and loopback-only mutation.

- [ ] **Step 5: Commit**

```bash
git add start-server.sh docs/agent-kv-cache-tuning.md
git commit -m "server: load saved KV capacity limit"
```

### Task 7: Editorial Dashboard Redesign

**Files:**
- Modify: `ds4_server.c`
- Test: `ds4_server.c`

- [ ] **Step 1: Write failing dashboard contract assertions**

Extend `test_dashboard_page_is_served_as_html` to require stable IDs/data hooks for the new layout and controls:

```c
TEST_ASSERT(strstr(out, "id=\"requestHitRate\"") != NULL);
TEST_ASSERT(strstr(out, "id=\"processTokenHitRate\"") != NULL);
TEST_ASSERT(strstr(out, "id=\"processRequestHitRate\"") != NULL);
TEST_ASSERT(strstr(out, "id=\"kvCapacity\"") != NULL);
TEST_ASSERT(strstr(out, "id=\"kvBudgetInput\"") != NULL);
TEST_ASSERT(strstr(out, "id=\"kvApplyNow\"") != NULL);
TEST_ASSERT(strstr(out, "id=\"kvSaveRestart\"") != NULL);
TEST_ASSERT(strstr(out, "/ds4/admin/kv-cache") != NULL);
```

- [ ] **Step 2: Run and verify RED**

Run: `make ds4_server_test && ./ds4_server_test`

Expected: assertions fail because the current dashboard lacks these elements.

- [ ] **Step 3: Replace the visual system and information hierarchy**

Rewrite `dashboard_html` around these semantic sections:

```html
<main class="page">
  <header class="masthead">model / backend / context / phase</header>
  <section class="hero">current KV hit rate + decode speed</section>
  <section class="request-strip">cache source / prompt / cached / write</section>
  <section class="operations">prefill / ETA / decode / queue</section>
  <section class="process">process token hit / request hit / totals</section>
  <section id="kvCapacity" class="capacity">disk usage + live context + editor</section>
  <div id="adminNotice" role="status" aria-live="polite"></div>
</main>
```

Use CSS variables `--paper:#f2f0e8`, `--ink:#171714`, `--muted:#69675f`, `--line:#cbc7ba`, `--accent:#e33f27`, a serif display stack for primary metrics, and monospace for raw values. Use borders/rules and whitespace instead of card shadows. At `max-width:760px`, stack hero and metric columns while retaining source order.

- [ ] **Step 4: Bind honest metric formatting**

Add JavaScript helpers with unavailable-value behavior:

```js
const ratio=(n,d)=>d>0?n/d:null;
const pct=v=>v==null?'—':(v*100).toFixed(1)+'%';
const bytes=n=>{
  n=Number(n)||0;
  if(n>=1073741824)return (n/1073741824).toFixed(1)+' GB';
  if(n>=1048576)return (n/1048576).toFixed(1)+' MB';
  return n+' B';
};
```

Derive current and cumulative hit rates from raw status counters. Show `Disabled` for a disabled KV store. Preserve the last successful snapshot on polling failure, mark the page stale/offline, and render an em dash for unknown ratios rather than zero.

- [ ] **Step 5: Implement the two capacity actions**

While the editor is focused, polling may update the rest of the dashboard but must not replace its value. “Save for restart” sends mode `persist`. “Apply now” first sends mode `dry-run`; when `eviction_required` is true, show a native confirmation containing current usage and proposed limit, then send mode `apply`. Display returned before/after bytes and entries in `adminNotice`.

Disable both buttons when status says disk KV is disabled. On HTTP 403, explain that controls work only from localhost. Never infer success from HTTP status alone; parse and display the response's runtime and persistent sub-results.

- [ ] **Step 6: Run tests and inspect in a browser**

Run: `make ds4_server_test && ./ds4_server_test`

Start a lightweight test instance only if an existing model-backed server is not already running; otherwise use the existing server. Inspect `/dashboard` at 1440x900 and 390x844, verify no horizontal overflow, confirm the capacity editor keeps its input during polling, and exercise dry-run without accepting an eviction.

Expected: server tests pass and both viewports preserve the intended reading order.

- [ ] **Step 7: Commit**

```bash
git add ds4_server.c
git commit -m "server: redesign runtime dashboard"
```

### Task 8: Full Regression Verification

**Files:**
- No production changes unless verification exposes a defect

- [ ] **Step 1: Run formatting and diff checks**

Run:

```bash
git diff --check origin/main..HEAD
git status --short
```

Expected: no whitespace errors; only intentional changes are present.

- [ ] **Step 2: Run focused server tests**

Run: `make ds4_server_test && ./ds4_server_test`

Expected: zero failures.

- [ ] **Step 3: Run the repository test suite**

Run: `make test`

Expected: all configured tests pass. Do not start a second huge model process.

- [ ] **Step 4: Verify the CPU build**

Run: `make cpu`

Expected: all CPU binaries compile without new warnings or errors. Do not run large CPU inference.

- [ ] **Step 5: Review the implementation against the design**

Re-read `docs/superpowers/specs/2026-07-10-dashboard-kv-observability-design.md` and check every scope, metric, interaction, error, concurrency, and compatibility requirement against code and tests. Fix any gap using a new RED/GREEN cycle.

- [ ] **Step 6: Commit verification fixes only if needed**

```bash
git add ds4_kvstore.h ds4_kvstore.c ds4_server.c start-server.sh docs/agent-kv-cache-tuning.md
git commit -m "fix: close KV dashboard verification gaps"
```

Skip this commit when verification required no code change.
