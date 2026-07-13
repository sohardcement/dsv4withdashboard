# Dashboard Management and Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the three dashboard themes with a polished management-first dashboard and a compact monitor mode, including safe inline administration feedback, accessible call inspection, and responsive verification.

**Architecture:** Keep the dashboard as one dependency-free HTML/CSS/JavaScript string embedded in `ds4_server.c`. Render two semantic mode roots from one `/ds4/status` snapshot and one set of admin controls; a small client-side state model owns the selected mode, selected call, filters, polling freshness, and KV administration state. Existing server endpoints and inference behavior remain unchanged.

**Tech Stack:** C99 embedded string literals, browser-native HTML/CSS/JavaScript, Python `ThreadingHTTPServer` fixture, Playwright CLI browser checks, existing C server tests.

---

## File map

- `ds4_server.c:8198-8260` — replace the current dashboard HTML/CSS/JavaScript with the management/monitor shell, rendering functions, mode state, inline KV state machine, responsive styles, and accessibility behavior.
- `tests/dashboard_ui_test.js:1-84` — replace theme assertions and native-confirm expectations with dual-mode, inline-review, keyboard selection, stale-state, and responsive assertions.
- `tests/dashboard_fixture.py:9-16` — enrich fixture call records with fields already present in the real status JSON so the request inspector and duration behavior can be tested.
- `README.md:731-767` — document the management/monitor modes and inline administration semantics instead of the removed three themes.
- `output/playwright/dashboard-management-desktop.png` — generated visual-verification artifact; do not stage or commit.
- `output/playwright/dashboard-monitor-desktop.png` — generated visual-verification artifact; do not stage or commit.
- `output/playwright/dashboard-management-mobile.png` — generated visual-verification artifact; do not stage or commit.

Do not modify or restage the already staged `.playwright-cli/` and `output/playwright/npm-cache/` artifacts. Each commit below must name only the intended source and test paths.

### Task 1: Introduce the shared shell and two persistent modes

**Files:**
- Modify: `tests/dashboard_ui_test.js:42-73`
- Modify: `ds4_server.c:8198-8260`

- [ ] **Step 1: Replace the theme test with a failing mode-shell test**

In `tests/dashboard_ui_test.js`, replace the block that writes `ds4-dashboard-theme`, loops over `paper/terminal/calm`, and checks the old theme roots with:

```javascript
await cfg({reset:true});
await page.evaluate(()=>localStorage.setItem('ds4-dashboard-mode','not-a-mode'));
await page.reload();
await wait(150);
assert(await page.locator('#dashboard').getAttribute('data-mode')==='management','management must be the default mode');
assert(await page.locator('#managementLayout').isVisible(),'management root is not visible by default');
assert(!(await page.locator('#monitorLayout').isVisible()),'monitor root is visible by default');
assert(await page.locator('[data-mode-choice="management"]').getAttribute('aria-pressed')==='true','management mode is not announced');
assert(await page.locator('#paperLayout,#terminalLayout,#calmLayout').count()===0,'legacy theme roots remain');

await page.locator('[data-mode-choice="monitor"]').click();
assert(await page.locator('#dashboard').getAttribute('data-mode')==='monitor','monitor mode did not apply');
assert(await page.locator('#monitorLayout').isVisible()&&!(await page.locator('#managementLayout').isVisible()),'mode roots did not switch');
await page.reload();
await wait(100);
assert(await page.locator('#dashboard').getAttribute('data-mode')==='monitor','monitor mode did not persist');
await page.locator('[data-mode-choice="management"]').click();
```

Change the existing screenshot destination near the end of the test from `dashboard-desktop.png` to `dashboard-management-desktop.png` so the already staged screenshot is not overwritten.

- [ ] **Step 2: Run the browser test and verify the new assertion fails**

Run:

```bash
./tests/run_dashboard_ui_test.sh
```

Expected: FAIL at `management must be the default mode` because the current page still exposes `data-theme="paper"` and the three theme roots.

- [ ] **Step 3: Replace the old theme shell with the two-mode semantic shell**

In the embedded dashboard markup in `ds4_server.c`, remove `.theme-switch`, `paperLayout`, `terminalLayout`, `calmLayout`, and their duplicated metric/event sections. Add this top-level structure, keeping the existing KV and context form IDs unique:

```html
<header class="topbar">
  <a class="brand" href="#managementSummary">DS4<span aria-hidden="true">●</span></a>
  <nav class="mode-switch" aria-label="Dashboard 模式">
    <button type="button" data-mode-choice="management" aria-pressed="true">管理</button>
    <button type="button" data-mode-choice="monitor" aria-pressed="false">监控</button>
  </nav>
  <div class="connection" id="connectionState">
    <span class="status-dot" aria-hidden="true"></span>
    <strong id="health">等待状态</strong>
    <span id="updatedAt">尚未更新</span>
  </div>
</header>
```

Change the `<main>` attribute from `data-theme="paper"` to `data-mode="management"`. For Task 1, rename the current `paperLayout` root to `managementLayout`, retain all of its existing child sections and the shared admin forms, change `chineseStatic` selectors from `#paperLayout` to `#managementLayout`, and delete the terminal/calm roots. Insert `<div id="monitorLayout" class="mode-layout" hidden aria-hidden="true"></div>` immediately after the management root. Task 2 replaces the retained report body with the approved management information architecture. Replace `setTheme` with a mode function that validates storage and never resets page state:

```javascript
function setMode(value){
  const mode=value==='monitor'?'monitor':'management';
  dash.dataset.mode=mode;
  for(const name of ['management','monitor']){
    const root=$(name+'Layout'),active=name===mode;
    root.hidden=!active;
    root.setAttribute('aria-hidden',String(!active));
  }
  document.querySelectorAll('[data-mode-choice]').forEach(button=>
    button.setAttribute('aria-pressed',String(button.dataset.modeChoice===mode)));
  try{localStorage.setItem('ds4-dashboard-mode',mode)}catch(error){}
}
try{setMode(localStorage.getItem('ds4-dashboard-mode'))}catch(error){setMode('management')}
document.querySelectorAll('[data-mode-choice]').forEach(button=>
  button.addEventListener('click',()=>setMode(button.dataset.modeChoice)));
```

Add the “precision instrument” base tokens and visible focus behavior before layout-specific CSS:

```css
:root{color-scheme:light;--paper:#f3f0e7;--surface:#f8f5ed;--ink:#171a1d;--muted:#706d65;--line:#c4bfb4;--accent:#df4932;--success:#28734b;--danger:#a52a1c}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 Avenir,"Gill Sans","Trebuchet MS",Arial,sans-serif}
button,input,select{min-height:44px;font:inherit;color:inherit}
:focus-visible{outline:3px solid #2563eb;outline-offset:3px}
.mode-layout[hidden]{display:none!important}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;transition:none!important}}
```

- [ ] **Step 4: Run the focused browser test and verify mode assertions pass**

Run `./tests/run_dashboard_ui_test.sh`.

Expected: the mode assertions pass; the run may fail later on selectors for the old dashboard content that will be replaced in Tasks 2–5. Confirm the first failure is after the new mode block.

- [ ] **Step 5: Commit the shell and its test**

```bash
git add ds4_server.c tests/dashboard_ui_test.js
git commit --only ds4_server.c tests/dashboard_ui_test.js -m "dashboard: introduce management and monitor modes"
```

### Task 2: Build and render the management-first workspace

**Files:**
- Modify: `tests/dashboard_ui_test.js:42-84`
- Modify: `ds4_server.c:8198-8260`

- [ ] **Step 1: Add failing assertions for the management information hierarchy**

After switching back to management mode, add:

```javascript
assert((await page.locator('#managementTitle').innerText())==='运行与容量','management title is missing');
assert((await page.locator('#managementPhase').innerText()).includes('解码'),'management phase was not localized');
assert((await page.locator('#managementContext').innerText()).includes('115,720'),'context remaining is not prominent');
assert((await page.locator('#managementKv').innerText()).includes('46.0 / 64.0 GB'),'KV capacity summary is missing');
assert((await page.locator('#kvEffect').innerText()).includes('立即影响运行'),'KV effect is ambiguous');
assert((await page.locator('#contextEffect').innerText()).includes('重启后生效'),'context effect is ambiguous');
assert(await page.locator('#managementRecentCalls [data-call-id]').count()===3,'management mode must show exactly three recent calls');
assert((await page.locator('#managementRecentCalls').innerText()).includes('hanako-agent'),'recent calls omit service identity');
assert((await page.locator('#managementHost').innerText()).includes('内存压力'),'host summary is missing');
```

- [ ] **Step 2: Run the browser test and verify the management assertions fail**

Run `./tests/run_dashboard_ui_test.sh`.

Expected: FAIL with `management title is missing` or a missing `#managementTitle` locator.

- [ ] **Step 3: Add the management DOM with one copy of each form**

Populate `#managementLayout` with:

```html
<div class="management-grid">
  <aside class="section-nav" aria-label="管理区段">
    <a href="#managementSummary">运行概览</a>
    <a href="#kvCapacity">磁盘 KV 容量</a>
    <a href="#contextCapacity">上下文窗口</a>
    <a href="#managementRecent">最近调用</a>
    <a href="#managementHost">主机资源</a>
  </aside>
  <div class="management-main">
    <section id="managementSummary" aria-labelledby="managementTitle">
      <p class="eyebrow">Runtime management</p>
      <h1 id="managementTitle">运行与容量</h1>
      <p id="model">正在读取状态</p>
      <div class="summary-ruler">
        <div><span>运行状态</span><strong id="managementPhase">连接中</strong><small id="managementQueue">—</small></div>
        <div><span>上下文余量</span><strong id="managementContext">—</strong><small id="managementContextRatio">—</small></div>
        <div><span>磁盘 KV</span><strong id="managementKv">—</strong><small id="managementKvRatio">—</small></div>
      </div>
    </section>
    <section id="kvCapacity" class="setting-block"></section>
    <section id="contextCapacity" class="setting-block"></section>
    <section id="managementRecent" aria-labelledby="managementRecentTitle">
      <h2 id="managementRecentTitle">最近调用</h2>
      <div id="managementRecentCalls"></div>
    </section>
    <section id="managementHost" aria-labelledby="managementHostTitle">
      <h2 id="managementHostTitle">主机资源</h2>
      <div class="host-summary">
        <div><span>内存压力</span><strong id="managementHostPressure">不可用</strong></div>
        <div><span>物理内存</span><strong id="managementHostPhysical">不可用</strong></div>
        <div><span>DS4 RSS</span><strong id="managementHostRss">不可用</strong></div>
      </div>
    </section>
  </div>
</div>
```

Move the existing `kvForm`, `contextForm`, `adminNotice`, and `contextNotice` markup into their corresponding setting blocks. Add `#kvEffect` with `立即影响运行` and `#contextEffect` with `重启后生效`. Do not clone or append these forms into monitor mode.

- [ ] **Step 4: Add focused management render helpers**

Add and call these helpers from `paint(snapshot)`:

```javascript
function phaseLabel(value){return ({decode:'解码中',prefill:'预填充中',idle:'空闲'})[value]||value||'未知'}
function paintManagement(snapshot){
  const model=snapshot.model||{},context=snapshot.context||{},kv=snapshot.kv_cache||{};
  text('managementPhase',phaseLabel(snapshot.phase));
  text('managementQueue','队列 '+num(snapshot.queue_depth)+' · '+num(snapshot.clients)+' 个客户端');
  text('managementContext',num(context.remaining).toLocaleString());
  text('managementContextRatio',pct(1-num(context.utilization))+' 可用');
  text('managementKv',kv.enabled?bytes(kv.used_bytes)+' / '+bytes(kv.budget_bytes):'已禁用');
  text('managementKvRatio',kv.enabled?pct(ratio(kv.used_bytes,kv.budget_bytes))+' 已使用':'未配置磁盘缓存');
  paintRecentCalls((snapshot.calls&&snapshot.calls.records)||[]);
  paintHost(snapshot.host);
}
function paintRecentCalls(records){
  const root=$('managementRecentCalls');
  root.replaceChildren();
  for(const record of records.slice(0,3)){
    const row=document.createElement('div');
    row.dataset.callId=record.request_id||'';
    for(const value of ['#'+(record.request_id||'—'),record.client||'未标识服务',record.api||'未知 API',callStatus(record.status)]){
      const span=document.createElement('span');span.textContent=value;row.append(span);
    }
    root.append(row);
  }
}
```

Preserve the existing rule that focused KV/context inputs are not overwritten by polling.

Update the successful context message in `saveContext` to `已保存：下次启动生效，需要重启；当前运行值未改变。` and extend the existing context-success assertion to require both `需要重启` and `当前运行值未改变`.

- [ ] **Step 5: Add management layout CSS and rerun the test**

Implement a `180px 1fr` management grid above 900px, dual-column `.setting-block` above 760px, and single-column fallbacks below those breakpoints. Use ruler lines and typography rather than separate rounded cards. Run `./tests/run_dashboard_ui_test.sh`.

Expected: the new management assertions pass; later legacy KV-confirm or monitor assertions may still fail.

- [ ] **Step 6: Commit the management workspace**

```bash
git add ds4_server.c tests/dashboard_ui_test.js
git commit --only ds4_server.c tests/dashboard_ui_test.js -m "dashboard: prioritize runtime management"
```

### Task 3: Replace native confirmation with the inline KV state machine

**Files:**
- Modify: `tests/dashboard_ui_test.js:1-40`
- Modify: `ds4_server.c:8248-8256`

- [ ] **Step 1: Replace auto-confirm setup with failing inline-review assertions**

Remove the `window.confirm` override. For a normal target, assert that the first click performs only the dry run and enters review:

```javascript
await cfg({reset:true}); await page.reload(); await wait(100);
await page.locator('#kvBudgetInput').fill('80');
await page.locator('#kvApplyNow').click();
await wait(120);
let s=await fixture();
assert(s.admin.map(x=>x.mode).join(',')==='dry-run','checking must not apply before review');
assert(await page.locator('#kvReview').isVisible(),'inline KV review did not open');
assert((await page.locator('#kvReview').innerText()).includes('64.0 GB → 80.0 GB'),'review omits capacity change');
assert(await page.locator('#kvConfirmApply').isVisible()&&await page.locator('#kvCancelApply').isVisible(),'review actions are missing');
await page.locator('#kvCancelApply').click();
assert(!(await page.locator('#kvReview').isVisible()),'cancel did not close review');
assert((await fixture()).admin.map(x=>x.mode).join(',')==='dry-run','cancel applied a change');
```

Then confirm a second review and assert `dry-run,apply`. Update double-click serialization to expect only one `dry-run` before confirmation, and update apply-plus-save serialization so save is disabled throughout `checking`, `review`, and `applying`.

- [ ] **Step 2: Add a failing changed-impact retry test**

Replace the native confirm-count assertion with:

```javascript
await cfg({reset:true,admin_delay_ms:40,mismatch_once:true,mismatch_makes_eviction:true});
await page.reload(); await wait(100);
await page.locator('#kvBudgetInput').fill('80');
await page.locator('#kvApplyNow').click(); await wait(100);
await page.locator('#kvConfirmApply').click(); await wait(180);
s=await fixture();
assert(s.admin.map(x=>x.mode).join(',')==='dry-run,apply,dry-run','changed revision should return to review before a second apply');
assert(await page.locator('#kvReview').isVisible(),'changed impact was not re-reviewed');
assert((await page.locator('#kvReview').innerText()).includes('90.0 GB'),'new eviction pressure is missing');
await page.locator('#kvConfirmApply').click(); await wait(120);
assert((await fixture()).admin.map(x=>x.mode).join(',')==='dry-run,apply,dry-run,apply','reviewed retry did not apply');
```

- [ ] **Step 3: Run the test and verify it fails because native confirmation still applies immediately**

Run `./tests/run_dashboard_ui_test.sh`.

Expected: FAIL with `checking must not apply before review`.

- [ ] **Step 4: Add review markup and the explicit state model**

Add this inside the KV setting action area:

```html
<section id="kvReview" class="impact-review" hidden tabindex="-1" aria-labelledby="kvReviewTitle">
  <h3 id="kvReviewTitle">审阅运行时影响</h3>
  <dl id="kvReviewFacts"></dl>
  <div class="controls">
    <button id="kvConfirmApply" class="primary" type="button">确认立即应用</button>
    <button id="kvCancelApply" type="button">取消</button>
  </div>
</section>
```

Replace `adminBusy`-only behavior with:

```javascript
let kvState='idle',kvReview=null,kvTrigger=null;
function setKvState(next){
  kvState=next;
  dash.dataset.kvState=next;
  const locked=['checking','review','applying','saving'].includes(next);
  for(const id of ['kvBudgetInput','kvBudgetUnit','kvApplyNow','kvSaveRestart'])$(id).disabled=locked||!online||!adminLocal;
  $('kvReview').hidden=next!=='review';
}
function reviewFingerprint(runtime){
  return [runtime.old_budget_bytes,runtime.new_budget_bytes,runtime.before_bytes,runtime.before_entries,runtime.after_entries].join(':');
}
function showKvReview(runtime,mb){
  kvReview={runtime,mb,fingerprint:reviewFingerprint(runtime)};
  const facts=$('kvReviewFacts');facts.replaceChildren();
  for(const [label,value] of [
    ['容量',bytes(runtime.old_budget_bytes)+' → '+bytes(runtime.new_budget_bytes)],
    ['修改前使用量',bytes(runtime.before_bytes)],
    ['预计清理',Math.max(0,num(runtime.before_entries)-num(runtime.after_entries))+' 条'],
    ['预计释放',bytes(Math.max(0,num(runtime.before_bytes)-num(runtime.after_bytes)))]]){
    const dt=document.createElement('dt'),dd=document.createElement('dd');
    dt.textContent=label;dd.textContent=value;facts.append(dt,dd);
  }
  setKvState('review');$('kvReview').focus();
}
```

- [ ] **Step 5: Implement check, confirm, retry, and cancel as separate actions**

Use these transitions instead of `applyWork` and `window.confirm`:

```javascript
async function checkKvImpact(){
  if(kvState!=='idle'&&kvState!=='success'&&kvState!=='error')return;
  kvTrigger=document.activeElement;const mb=budgetMB();setKvState('checking');
  try{const body=await admin('dry-run',mb),runtime=body.runtime||{};
    if(!runtime.ok||runtime.revision==null)throw new Error('运行时预检未返回有效修订版本。');
    showKvReview(runtime,mb);
  }catch(error){finishKvError(error)}
}
async function confirmKvApply(){
  if(kvState!=='review'||!kvReview)return;
  const reviewed=kvReview;setKvState('applying');
  try{const body=await admin('apply',reviewed.mb,reviewed.runtime.revision);
    if(!(body.runtime&&body.runtime.ok&&body.runtime.applied))throw new Error('服务器未确认已应用运行时上限。');
    finishKvSuccess(runtimeMessage(body));
  }catch(error){
    if(error.code!=='kv_state_changed')return finishKvError(error);
    try{const body=await admin('dry-run',reviewed.mb),runtime=body.runtime||{};
      if(reviewFingerprint(runtime)!==reviewed.fingerprint){showKvReview(runtime,reviewed.mb);return}
      const retried=await admin('apply',reviewed.mb,runtime.revision);
      if(!(retried.runtime&&retried.runtime.ok&&retried.runtime.applied))throw new Error('服务器未确认已应用运行时上限。');
      finishKvSuccess(runtimeMessage(retried));
    }catch(retryError){finishKvError(retryError)}
  }
}
function cancelKvApply(){kvReview=null;setKvState('idle');(kvTrigger||$('kvApplyNow')).focus()}
```

Define the completion, error, and persistence branches completely:

```javascript
function setKvMessage(message,bad){
  $('adminNotice').className=bad?'notice bad':'notice';
  text('adminNotice',message);
}
function kvErrorMessage(error){
  if(error.code==='kv_state_changed')return 'KV 状态持续变化，请等待活动缓存操作结束后重试。';
  return /^[\u4e00-\u9fff]/.test(error.message||'')?error.message:'操作失败：请检查输入、权限或服务器状态。';
}
function finishKvSuccess(message){
  kvReview=null;setKvMessage(message,false);setKvState('success');
  (kvTrigger||$('kvApplyNow')).focus();
}
function finishKvError(error){
  kvReview=null;setKvMessage(kvErrorMessage(error),true);setKvState('error');
  (kvTrigger||$('kvApplyNow')).focus();
}
async function persistKvBudget(){
  if(!['idle','success','error'].includes(kvState))return;
  kvTrigger=document.activeElement;
  try{
    const mb=budgetMB();setKvState('saving');setKvMessage('正在保存下次启动上限…',false);
    const body=await admin('persist',mb),persistent=body.persistent||{};
    if(!persistent.committed)throw new Error('服务器未提交下次启动设置。');
    finishKvSuccess(persistentMessage(body));
  }catch(error){finishKvError(error)}
}
```

In `admin`, keep setting `adminLocal=false` on 403 but call `setKvState('error')` instead of the removed `controls` helper. Bind `kvApplyNow` to `checkKvImpact`, `kvSaveRestart` to `persistKvBudget`, and `kvConfirmApply` / `kvCancelApply` to their respective functions.

- [ ] **Step 6: Run the browser test and verify all KV scenarios pass**

Run `./tests/run_dashboard_ui_test.sh`.

Expected: inline review, cancel, confirmed apply, serialization, changed-impact re-review, retry cap, malformed response, forbidden access, and partial eviction assertions all PASS.

- [ ] **Step 7: Commit the state machine**

```bash
git add ds4_server.c tests/dashboard_ui_test.js
git commit --only ds4_server.c tests/dashboard_ui_test.js -m "dashboard: review KV changes inline"
```

### Task 4: Add the compact monitor workspace and request inspector

**Files:**
- Modify: `tests/dashboard_fixture.py:9-10`
- Modify: `tests/dashboard_ui_test.js:81-84`
- Modify: `ds4_server.c:8198-8260`

- [ ] **Step 1: Enrich fixture records with real status fields**

For fixture records `99` through `95`, add representative values already emitted by `append_status_calls_json`, for example:

```python
{"request_id":"98","caller":"192.0.2.7","client":"hermes-agent","api":"chat",
 "kind":"chat","stream":True,"tools":True,"status":"failed","started_at":100.0,
 "finished_at":142.1,"prompt_tokens":39712,"cached_tokens":24576,
 "cache_write_tokens":4096,"output_tokens":922,"cache_source":"disk-text",
 "finish":"error","error":"<script>坏</script>"}
```

Keep the malicious service and caller records in the list, and add a fifth safe record so the 1440px visual acceptance can prove that five rows fit without scrolling the page.

- [ ] **Step 2: Write failing monitor and selection tests**

After selecting monitor mode, add:

```javascript
assert((await page.locator('#monitorMetrics').innerText()).includes('52.7 t/s'),'decode speed is missing from monitor metrics');
assert((await page.locator('#monitorMetrics').innerText()).includes('75.0%'),'KV hit rate is missing from monitor metrics');
assert(await page.locator('#monitorCalls [data-request-id]').count()===5,'monitor call flow is incomplete');
await page.locator('[data-request-id="98"] .request-select').click();
assert(await page.locator('[data-request-id="98"]').getAttribute('aria-selected')==='true','selected call is not announced');
const inspector=await page.locator('#requestInspector').innerText();
assert(inspector.includes('hermes-agent')&&inspector.includes('42.1s')&&inspector.includes('61.9%'),'request inspector omitted identity, duration, or cache rate');
await page.locator('[data-request-id="97"] .request-select').focus();
await page.keyboard.press('Enter');
assert((await page.locator('#requestInspector').innerText()).includes('openclaw'),'keyboard selection failed');
await page.locator('#callFilterClient').selectOption('hanako-agent');
assert((await page.locator('#requestInspector').innerText()).includes('请选择一条调用记录'),'filtered selection did not clear');
```

Retain and adapt the malicious-text assertion to `#monitorCalls` and `#requestInspector`; assert both contain no `img,script` descendants.

- [ ] **Step 3: Run the browser test and verify monitor selectors fail**

Run `./tests/run_dashboard_ui_test.sh`.

Expected: FAIL because `#monitorMetrics`, `#monitorCalls`, and `#requestInspector` do not yet exist.

- [ ] **Step 4: Add monitor markup and CSS**

Populate `#monitorLayout` with:

```html
<section aria-labelledby="monitorTitle">
  <p class="eyebrow">Live operations</p><h1 id="monitorTitle">实时运行</h1>
  <div id="monitorMetrics" class="monitor-metrics"></div>
</section>
<div class="monitor-workspace">
  <section aria-labelledby="callsTitle">
    <div class="section-head"><h2 id="callsTitle">调用流</h2><div id="callFilters"></div></div>
    <div class="call-table-wrap"><table><thead></thead><tbody id="monitorCalls"></tbody></table></div>
  </section>
  <aside id="requestInspector" tabindex="-1" aria-labelledby="requestInspectorTitle">
    <h2 id="requestInspectorTitle">请求详情</h2><p>请选择一条调用记录</p>
  </aside>
</div>
<section id="monitorHost" aria-labelledby="monitorHostTitle">
  <h2 id="monitorHostTitle">主机资源</h2>
  <div class="host-strip">
    <div><span>物理内存</span><strong id="monitorHostPhysical">不可用</strong></div>
    <div><span>内存压力 / Swap</span><strong id="monitorHostPressure">不可用</strong></div>
    <div><span>DS4 RSS</span><strong id="monitorHostRss">不可用</strong></div>
  </div>
</section>
```

Reuse the existing four filter controls by placing them in `#callFilters`; do not create a second filter state. Use a `minmax(0,1.55fr) minmax(260px,.65fr)` workspace above 980px and stack the inspector below calls at smaller widths.

Replace the old single-root `paintHost` helper with a shared renderer that updates both modes:

```javascript
function paintHost(host){
  if(!host||!host.available){
    for(const id of ['managementHostPressure','managementHostPhysical','managementHostRss','monitorHostPressure','monitorHostPhysical','monitorHostRss'])text(id,'不可用');
    return;
  }
  const physical=bytes(host.memory_used_bytes)+' / '+bytes(host.memory_total_bytes)+' · 可用 '+bytes(host.memory_available_bytes);
  const pressureText=pressure(host.memory_pressure)+' · Swap '+bytes(host.swap_used_bytes)+' / '+bytes(host.swap_total_bytes);
  for(const id of ['managementHostPhysical','monitorHostPhysical'])text(id,physical);
  for(const id of ['managementHostPressure','monitorHostPressure'])text(id,pressureText);
  for(const id of ['managementHostRss','monitorHostRss'])text(id,bytes(host.process_rss_bytes));
}
```

- [ ] **Step 5: Implement safe row rendering and selection**

Add:

```javascript
let selectedRequestId='';
function recordDuration(record,calls,request){
  if(num(record.finished_at)>num(record.started_at))return sec(num(record.finished_at)-num(record.started_at));
  return String(record.request_id)===String((calls||{}).active_request_id)?sec(request.elapsed_sec):'—';
}
function selectRequest(id){selectedRequestId=String(id||'');paintCalls((lastSnapshot||{}).calls,(lastSnapshot||{}).request)}
function paintInspector(record,calls,request){
  const root=$('requestInspector');root.replaceChildren();
  const heading=document.createElement('h2');heading.id='requestInspectorTitle';heading.textContent=record?'请求 #'+record.request_id:'请求详情';root.append(heading);
  if(!record){const empty=document.createElement('p');empty.textContent='请选择一条调用记录';root.append(empty);return}
  const facts=[['服务',record.client],['调用方',record.caller],['API',record.api],['耗时',recordDuration(record,calls,request)],['提示 token',num(record.prompt_tokens).toLocaleString()],['KV 命中',pct(ratio(record.cached_tokens,record.prompt_tokens))],['缓存来源',record.cache_source],['结束原因',record.finish],['最近错误',record.error]];
  const dl=document.createElement('dl');for(const [label,value] of facts){const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=label;dd.textContent=value||'—';dl.append(dt,dd)}root.append(dl);
}
```

Render each call as a `tr[data-request-id]` with `aria-selected`. Put a native `<button type="button" class="request-select" aria-label="查看请求 #98">#98</button>` in the first cell and bind it to `selectRequest`. Build every cell with `textContent`.

After filtering, clear `selectedRequestId` if it is absent from `shown`, then call `paintInspector`. Preserve the existing localized status mapping and filter option replacement.

Change the call site in `paint(snapshot)` to `paintCalls(snapshot.calls,snapshot.request)`, and change all four filter listeners to `paintCalls((lastSnapshot||{}).calls,(lastSnapshot||{}).request)` so active-request duration remains available after interactive filtering.

- [ ] **Step 6: Run the monitor tests**

Run `./tests/run_dashboard_ui_test.sh`.

Expected: monitor metrics, filters, mouse and keyboard selection, inspector fields, selection clearing, localization, and malicious-text assertions PASS.

- [ ] **Step 7: Commit monitor mode**

```bash
git add ds4_server.c tests/dashboard_ui_test.js tests/dashboard_fixture.py
git commit --only ds4_server.c tests/dashboard_ui_test.js tests/dashboard_fixture.py -m "dashboard: add compact request monitor"
```

### Task 5: Finish stale-state, focus, responsive, and documentation behavior

**Files:**
- Modify: `tests/dashboard_ui_test.js:1-84`
- Modify: `ds4_server.c:8198-8260`
- Modify: `README.md:731-767`

- [ ] **Step 1: Add failing freshness, focus, and responsive assertions**

Add:

```javascript
await page.locator('[data-mode-choice="management"]').click();
await page.locator('#kvBudgetInput').fill('32');
await page.locator('#kvApplyNow').click(); await wait(120);
assert(await page.evaluate(()=>document.activeElement.id)==='kvReview','risk review did not receive focus');
await page.locator('#kvCancelApply').click();
assert(await page.evaluate(()=>document.activeElement.id)==='kvApplyNow','cancel did not restore focus');

for(const width of [1024,390]){
  await page.setViewportSize({width,height:844}); await wait(50);
  const size=await page.evaluate(()=>({page:document.documentElement.scrollWidth,viewport:innerWidth}));
  assert(size.page<=size.viewport,'page overflows at '+width+'px');
}
await page.setViewportSize({width:1440,height:900});
await cfg({offline:true}); await wait(1150);
assert((await page.locator('#connectionState').innerText()).includes('数据已过期'),'stale snapshot is not explicit');
assert((await page.locator('#updatedAt').innerText()).includes('更新'),'stale snapshot has no timestamp');
assert(await page.locator('#kvApplyNow').isDisabled()&&await page.locator('#contextSaveRestart').isDisabled(),'offline administration remained enabled');
await cfg({reset:true,host_available:false}); await page.reload(); await wait(100);
assert((await page.locator('#managementHostPhysical').innerText())==='不可用'&&(await page.locator('#monitorHostPhysical').innerText())==='不可用','unavailable host sampling was rendered as data');
```

Also assert every visible mode button and form control has a bounding-box height of at least 44px, and that the document contains none of the former English labels or three theme names.

- [ ] **Step 2: Run the browser test and verify the first missing behavior fails**

Run `./tests/run_dashboard_ui_test.sh`.

Expected: FAIL on focus restoration, stale timestamp, or responsive overflow until the finishing behavior is implemented.

- [ ] **Step 3: Implement freshness and focus behavior**

Track the last successful paint time:

```javascript
let lastUpdatedAt=0;
function freshnessLabel(stale){
  if(!lastUpdatedAt)return '尚未更新';
  const age=Math.max(0,Math.round((Date.now()-lastUpdatedAt)/1000));
  return stale?'数据已过期 · '+age+' 秒前更新':age+' 秒前更新';
}
```

On successful paint, set `lastUpdatedAt=Date.now()`, update `#updatedAt`, and clear stale styling. On polling failure, keep the last snapshot, set health to `数据已过期` or `不可用`, update `#updatedAt` with `freshnessLabel(true)`, and disable both admin groups. Ensure `showKvReview` focuses `#kvReview`, while cancel and successful completion return focus to the originating button.

- [ ] **Step 4: Finish responsive CSS and visible state styling**

At 980px, stack the monitor workspace and move its inspector below the call table. At 900px, remove the management side rail. At 760px, stack summary rulers and setting blocks. At 390px, keep mode buttons, inputs, and actions full-width where necessary. Apply `min-width:0`, `overflow-wrap:anywhere`, and bounded `.call-table-wrap{overflow-x:auto}` so only the call table can scroll horizontally.

Use `.stale` text and border treatment in addition to the status color. Keep `@media(prefers-reduced-motion:reduce)` and 44px control heights.

- [ ] **Step 5: Update the README to match the new product behavior**

Replace the three-theme paragraph at `README.md:751-756` with:

```markdown
The dashboard has two task-focused local modes under one visual system:
**管理** (the default) keeps runtime state, disk-KV capacity, context settings,
their activation timing, and operation results together; **监控** provides a
compact live metric strip, filterable call flow, request inspector, and host
resources. The selected mode is saved only in that browser's `localStorage`;
it does not change server configuration or data.

Disk-KV runtime changes use an inline dry-run review before application. The
review shows the old and new capacity and any expected eviction impact.
Persist-only KV changes and context changes remain explicitly labeled as
next-start settings and do not imply that the current process changed.
```

- [ ] **Step 6: Run the complete browser test**

Run `./tests/run_dashboard_ui_test.sh`.

Expected final output includes a returned object with `"ok":true`; no assertion or browser console error is reported.

- [ ] **Step 7: Commit responsive behavior and docs**

```bash
git add ds4_server.c tests/dashboard_ui_test.js README.md
git commit --only ds4_server.c tests/dashboard_ui_test.js README.md -m "dashboard: polish responsive operations UI"
```

### Task 6: Full regression and visual acceptance

**Files:**
- Verify: `ds4_server.c`
- Verify: `tests/dashboard_ui_test.js`
- Verify: `tests/dashboard_fixture.py`
- Verify: `README.md`
- Generate, do not stage: `output/playwright/dashboard-management-desktop.png`
- Generate, do not stage: `output/playwright/dashboard-monitor-desktop.png`
- Generate, do not stage: `output/playwright/dashboard-management-mobile.png`

- [ ] **Step 1: Run formatting and source checks**

```bash
git diff --check 893d93a..HEAD -- ds4_server.c tests/dashboard_ui_test.js tests/dashboard_fixture.py README.md
rg -n "ds4-dashboard-theme|paperLayout|terminalLayout|calmLayout|window\.confirm|innerHTML" ds4_server.c tests/dashboard_ui_test.js README.md
```

Expected: `git diff --check` prints nothing. `rg` prints nothing; all legacy theme state, native confirmation, and unsafe HTML mutation are removed.

- [ ] **Step 2: Run the browser regression from a clean fixture process**

```bash
./tests/run_dashboard_ui_test.sh
```

Expected: PASS and a returned object containing `"ok":true`.

- [ ] **Step 3: Run the focused C server regression**

```bash
make ds4_test
./ds4_test --server
```

Expected: build succeeds and the server test suite reports all selected tests passed.

- [ ] **Step 4: Capture all three acceptance screenshots**

Extend the end of `tests/dashboard_ui_test.js` long enough to switch modes and viewports before each screenshot:

```javascript
await cfg({reset:true}); await page.reload(); await wait(150);
await page.setViewportSize({width:1440,height:900});
await page.locator('[data-mode-choice="management"]').click();
await page.screenshot({path:'output/playwright/dashboard-management-desktop.png',fullPage:true});
await page.locator('[data-mode-choice="monitor"]').click();
await page.screenshot({path:'output/playwright/dashboard-monitor-desktop.png',fullPage:true});
await page.setViewportSize({width:390,height:844});
await page.locator('[data-mode-choice="management"]').click();
await page.screenshot({path:'output/playwright/dashboard-management-mobile.png',fullPage:true});
```

Run the browser regression once more. Open each PNG and verify: no clipping or page-level overflow; management current/target/effect hierarchy is obvious; monitor metrics, five available call rows where fixture data permits, and inspector fit at 1440px; Chinese text and focus/disabled styling remain legible.

- [ ] **Step 5: Commit only the screenshot-test source change**

```bash
git add tests/dashboard_ui_test.js
git commit --only tests/dashboard_ui_test.js -m "test: capture dashboard acceptance views"
```

Do not add the generated PNGs or any cache output.

- [ ] **Step 6: Audit the final diff against the approved spec**

Use `git diff 893d93a..HEAD -- ds4_server.c tests/dashboard_ui_test.js tests/dashboard_fixture.py README.md` and check every acceptance item in `docs/superpowers/specs/2026-07-13-dashboard-management-monitor-design.md`: management-first hierarchy, shared two-mode shell, inline KV review, monitor selection, truthful stale/unavailable states, safe text rendering, keyboard access, responsive behavior, Chinese copy, and unchanged local-only endpoint boundaries.

Expected: every spec item has a corresponding implementation or test; no unrelated inference/backend behavior changed.
