# Dashboard Layouts and Client Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver three structurally distinct Chinese DS4 dashboard themes and show a safe, useful client-service name alongside each direct peer IP.

**Architecture:** Extend the bounded call-history record with a sanitized client label resolved at HTTP ingress from `X-DS4-Client`, then `User-Agent`, then a Chinese fallback. Keep JSON and dashboard rendering on DOM/text APIs. Replace the single dashboard layout with three theme-specific layout roots that consume the same status snapshot and bind the same administration controls.

**Tech Stack:** C99 HTTP server and tests, embedded HTML/CSS/JavaScript, Node/Playwright dashboard fixture.

---

### Task 1: Capture and expose client-service identity

**Files:**
- Modify: `ds4_call_history.h`
- Modify: `ds4_call_history.c`
- Modify: `ds4_server.c: HTTP header parsing, job creation, status JSON, server tests`

- [ ] **Step 1: Write failing C tests for client precedence and JSON output**

Add a focused history test that starts records with `hanako-agent`, `Hermes/1.0`, and `未标识服务`, snapshots them, and asserts that the client field survives copying and aggregation. Add a status JSON assertion for `"client":"hanako-agent"`; add ingress tests for `X-DS4-Client` winning over `User-Agent`, `User-Agent` fallback, and missing headers fallback.

- [ ] **Step 2: Run the focused server suite and verify the new assertions fail**

Run: `make ds4_test && ./ds4_test --server`

Expected: failure because call records and status JSON do not yet have a `client` field.

- [ ] **Step 3: Add bounded, sanitized client fields**

Add `char client[128]` to `ds4_call_record` and `ds4_call_caller`. Change the begin API to accept `const char *client`. Implement a local copy helper that discards ASCII control characters, trims surrounding whitespace, limits to the fixed buffer, and substitutes `未标识服务` for an empty result. Aggregate records by the `(caller, client)` pair so separate services on one IP remain distinguishable.

- [ ] **Step 4: Resolve identity at HTTP ingress and serialize it**

At job creation, read headers with existing bounded header helpers: use nonempty `X-DS4-Client`, otherwise nonempty `User-Agent`, otherwise the fallback. Pass it into `ds4_call_history_begin`. Add `client` to records and caller aggregates in `append_status_calls_json`, using `json_escape` for every emitted value.

- [ ] **Step 5: Re-run focused tests and commit**

Run: `make ds4_test && ./ds4_test --server`

Expected: `server: OK` and `ds4 tests: ok`.

Commit:
```bash
git add ds4_call_history.h ds4_call_history.c ds4_server.c
git commit -m "server: record API client identity"
```

### Task 2: Establish three theme-specific dashboard structures

**Files:**
- Modify: `ds4_server.c: dashboard_html markup, stylesheet, theme renderer and page-contract tests`
- Modify: `tests/dashboard_fixture.py`
- Modify: `tests/dashboard_ui_test.js`

- [ ] **Step 1: Write browser contract assertions for distinct layouts**

In `tests/dashboard_ui_test.js`, assert default `data-theme="paper"`, then switch through `paper`, `terminal`, and `calm`. Assert each theme exposes a distinct root (`#paperLayout`, `#terminalLayout`, `#calmLayout`), only its root is visible, every root contains the same `#contextSaveRestart` and KV controls through shared controls or explicit event delegation, and mobile `scrollWidth <= innerWidth`.

- [ ] **Step 2: Run the UI test and verify it fails**

Run: `node --check tests/dashboard_ui_test.js && ./tests/run_dashboard_ui_test.sh`

Expected: failure because the existing page has one shared layout and only changes color variables.

- [ ] **Step 3: Replace color-only theme behavior with explicit layout roots**

Keep one `<main id="dashboard">`, but render three child layout roots. Paper orders executive state, prose findings, resource/context facts, then detailed calls. Terminal orders status line, dense metric grid, then a live-style call event list. Calm orders a health summary, context/resource explanations, then a service-oriented timeline. Use a `setTheme()` implementation that sets `data-theme`, toggles `hidden` and `aria-hidden` on the three roots, persists only the allow-listed theme to localStorage, and defaults to paper on storage failure or bad values.

- [ ] **Step 4: Bind shared snapshot data and safe controls**

Refactor paint helpers to update every corresponding text target using `textContent`, `replaceChildren`, and element constructors. Render client labels and IP independently; do not concatenate them into HTML. Keep polling serialized and retain existing Context/KV local-admin headers, busy controls, CSRF boundaries, stale handling, and keyboard labels.

- [ ] **Step 5: Re-run UI and server page-contract tests, then commit**

Run: `make ds4_test && ./ds4_test --server && node --check tests/dashboard_ui_test.js && ./tests/run_dashboard_ui_test.sh`

Expected: all commands exit 0; the fixture's deliberate stale-state 503 may appear in browser console output.

Commit:
```bash
git add ds4_server.c tests/dashboard_fixture.py tests/dashboard_ui_test.js
git commit -m "server: add distinct dashboard layouts"
```

### Task 3: Add service-oriented call exploration

**Files:**
- Modify: `ds4_server.c: call table, service aggregate, client filter and renderer`
- Modify: `tests/dashboard_fixture.py`
- Modify: `tests/dashboard_ui_test.js`

- [ ] **Step 1: Write failing UI checks for service presentation and XSS safety**

Extend the fixture with records for `hanako-agent`, `hermes-agent`, `openclaw`, and a client string containing `<script>`. Assert a 服务 column and a 按服务筛选 control; filtering `openclaw` leaves only its rows; and the malicious value appears as literal text with zero `script`/`img` elements.

- [ ] **Step 2: Run the UI test and verify it fails**

Run: `./tests/run_dashboard_ui_test.sh`

Expected: failure because the existing call records have no client column or service filter.

- [ ] **Step 3: Render client service and per-service aggregate safely**

Add the 服务 column to every theme's call presentation, a service filter fed from snapshot records, and a client-oriented aggregate (client, IP, calls, failures, prompt tokens). Use `textContent` for headers, cells, error strings, and values. Map only internal statuses to Chinese labels; leave supplied client text as text, not markup.

- [ ] **Step 4: Verify focused suites and commit**

Run: `make ds4_test && ./ds4_test --server && node --check tests/dashboard_ui_test.js && ./tests/run_dashboard_ui_test.sh && git diff --check`

Expected: success, including service filter and malicious-text assertions.

Commit:
```bash
git add ds4_server.c tests/dashboard_fixture.py tests/dashboard_ui_test.js
git commit -m "dashboard: show API client services"
```

### Task 4: Document client headers and finish verification

**Files:**
- Modify: `README.md: Runtime dashboard and local administration`
- Modify: `docs/agent-kv-cache-tuning.md`

- [ ] **Step 1: Document the exact identity behavior**

Add an example `curl -H 'X-DS4-Client: hanako-agent'` and document the priority `X-DS4-Client` → `User-Agent` → `未标识服务`. State that this is observability metadata, not authentication, that IP remains a direct peer address, and that DS4 does not trust forwarded-IP headers or store request bodies.

- [ ] **Step 2: Document each theme’s practical purpose**

Describe paper as default editorial report, terminal as dense live operations, and calm as explanatory service timeline. State that themes share the same status data and controls, while their layout and section order differ.

- [ ] **Step 3: Run full lightweight verification and commit**

Run: `make ds4_test && ./ds4_test --server && node --check tests/dashboard_ui_test.js && ./tests/run_dashboard_ui_test.sh && bash -n start-server.sh && make cpu && git diff --check`

Expected: all commands exit 0. Record the existing CPU-only unused KV helper warnings if they remain; do not start a huge model-backed inference process for this dashboard change.

Commit:
```bash
git add README.md docs/agent-kv-cache-tuning.md
git commit -m "docs: explain dashboard clients and layouts"
```
