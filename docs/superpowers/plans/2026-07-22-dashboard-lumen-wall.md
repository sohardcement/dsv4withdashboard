# DS4 Dashboard「流明墙」Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. The user explicitly selected Kimi K3 as the implementation worker; use K3 for each production-code proposal and review every patch locally before applying it.

**Goal:** 将现有内嵌 Dashboard 绿地重构为批准的 B1「流明墙」：巨数幕墙、单条玻璃控制柱、60 秒黑白灰光场和高反馈交互，同时完整保留管理安全、轮询、筛选、离线和无障碍契约。

**Architecture:** 保持单文件嵌入架构，服务端 API 与 fixture 不变。先用现有 Playwright/C server tests 写出主题删除、监控默认、B1 DOM/token、动效降级和首屏边界的失败契约；再以 CSS/DOM 绿地重写、JS 行为复用的方式替换 `dashboard_html`，最后同步 README 并做真实浏览器视觉验收。

**Tech Stack:** C99 相邻字符串字面量、原生 HTML/CSS/JavaScript、CSS backdrop-filter/transform、Python fixture、Playwright CLI、Markdown。

## Global Constraints

- 设计基准：`docs/superpowers/specs/2026-07-22-dashboard-lumen-wall-design.md`。
- 不改变 `/ds4/status`、`/ds4/admin/kv-cache`、`/ds4/admin/context` 的请求或响应契约。
- 不修改 `tests/dashboard_fixture.py`，不引入依赖、资源文件、框架、网络字体、图标包或构建步骤。
- 所有动态服务端文本继续使用 `textContent`，不得用 `innerHTML`。
- 保留 KV 状态机、revision 重检、焦点恢复、脏输入、筛选选择、stale/offline 和 host unavailable 行为。
- 背景零彩色环境光；唯一循环环境动效为 60s transform-only 灰阶光团。
- `prefers-reduced-motion` 与 760px 以下必须停止光团；390px 页面不得横向溢出。
- `.primary` 必须为 `#1b1e24`，在线 `#15803d`，失败 `#dc2626`，警告 `#b45309`。
- 不覆盖或提交工作区既有修改；当前 `ds4_server.c` 已含与启动性能配置有关的用户改动，最终 Diff 必须按 hunk 复核。
- 当前基线 `DS4_DASHBOARD_TEST_PORT=18766 ./tests/run_dashboard_ui_test.sh` 已存在“last inspector fact must fit within the 1440x900 acceptance viewport”失败；新 RED 必须在该旧失败之前触发，最终 GREEN 必须同时解决两者。
- 未经用户要求不推送、不开 PR、不合并。若工作区无法安全隔离提交，下面的 commit 步骤只作为逻辑检查点，不执行实际 commit。

---

### Task 1: 写出 B1 的失败浏览器与 C 页面契约

**Files:**
- Modify: `tests/dashboard_ui_test.js:133-161, 271-293`
- Modify test section only: `ds4_server.c:14020-14080`
- Test: `tests/run_dashboard_ui_test.sh`

**Interfaces:**
- Consumes: 现有 fixture 的 `/fixture/config`、`/fixture/state`、状态快照和恶意文本矩阵。
- Produces: B1 页面必须满足的 DOM、token、默认模式、动效和 viewport 契约。

- [ ] **Step 1: 用 B1 断言替换四主题断言。**

将 `tests/dashboard_ui_test.js` 中从“invalid theme”到切回 paper 的断言替换为以下完整契约：

```js
await cfg({reset:true});
await page.evaluate(()=>{
  localStorage.removeItem('ds4-dashboard-mode');
  localStorage.setItem('ds4-dashboard-theme','terminal');
});
await reloadReady();
assert(await page.locator('#dashboard').getAttribute('data-mode')==='monitor','fresh dashboard must default to monitor');
assert(await page.locator('#monitorLayout').isVisible()&&await page.locator('#managementLayout').getAttribute('hidden')==='','fresh dashboard did not expose monitor only');
assert(await page.locator('[data-theme-choice],.theme-switch').count()===0,'legacy theme controls remain');
const lumenContract=await page.evaluate(()=>{
  const root=getComputedStyle(document.documentElement);
    const wall=document.body;
  const light=document.querySelector('.light-field');
  const glass=document.querySelector('.glass-column');
  return {
    htmlTheme:document.documentElement.dataset.theme||'',
    dashTheme:document.getElementById('dashboard').dataset.theme||'',
    ink:root.getPropertyValue('--ink').trim(),
    success:root.getPropertyValue('--success').trim(),
    danger:root.getPropertyValue('--danger').trim(),
    wallBackground:wall?getComputedStyle(wall).backgroundImage:'',
    lightDuration:light?getComputedStyle(light).animationDuration:'',
    glassBlur:glass?getComputedStyle(glass).backdropFilter:''
  };
});
assert(!lumenContract.htmlTheme&&!lumenContract.dashTheme,'theme dataset survived single-system migration');
assert(lumenContract.ink==='#1b1e24'&&lumenContract.success==='#15803d'&&lumenContract.danger==='#dc2626','B1 signal tokens are wrong');
assert(lumenContract.wallBackground.includes('158deg')&&lumenContract.lightDuration==='60s'&&lumenContract.glassBlur.includes('blur(24px)'),'B1 wall, light, or glass material is missing');
assert(await page.locator('.glass-column:visible').count()===1,'the active mode must expose exactly one primary glass column');
```

保留模式按钮顺序断言；删除所有点击 `terminal/calm/glass/paper` 与 `themeTokens()` 的代码。删除紧随模式切换之后、断言旧 `#f3f0e7/#171a1d/#28734b/#a52a1c` precision-instrument palette 的 `tokens` 两行；B1 token 已由 `lumenContract` 唯一覆盖。切换到 management 后再次断言 `.glass-column:visible` 数量为 1。

- [ ] **Step 2: 增加巨数镜像、状态色、墨黑操作和动效方向断言。**

在初始监控指标内容断言之后插入：

```js
const mirrorPairs=[
  ['decode','monitorDecode'],
  ['prefill','monitorPrefill'],
  ['cache','monitorCacheHit'],
  ['context','monitorContext'],
  ['queue','monitorQueue']
];
for(const [name,id] of mirrorPairs){
  const mirror=page.locator(`[data-mirror="${name}"]`);
  assert(await mirror.count()===1&&await mirror.getAttribute('aria-hidden')==='true',name+' wall mirror is missing or exposed to assistive tech');
  assert((await mirror.innerText()).trim()===(await page.locator('#'+id).innerText()).trim(),name+' wall mirror is out of sync');
}
const colorContract=await page.evaluate(()=>{
  const primaries=[...document.querySelectorAll('button.primary')];
  const active=document.querySelector('[data-request-id="99"] .result');
  const failed=document.querySelector('[data-request-id="98"] .result');
  return {
    complete:primaries.length>0&&!!active&&!!failed,
    primaries:primaries.map(node=>getComputedStyle(node).backgroundColor),
    active:active?getComputedStyle(active).color:'',
    failed:failed?getComputedStyle(failed).color:''
  };
});
assert(colorContract.complete&&colorContract.primaries.every(value=>value==='rgb(27, 30, 36)')&&colorContract.active==='rgb(21, 128, 61)'&&colorContract.failed==='rgb(220, 38, 38)','B1 action or status color discipline is broken');
const motionIds=['monitorPrefill','monitorDecode','monitorCacheHit','monitorContext','monitorQueue'];
let motionSnapshot=await page.evaluate(()=>lastUpdatedAt);
await cfg({status_patch:{queue_depth:3,prefill:{avg_tps:1900.4},decode:{avg_tps:60.7},request:{cached_tokens:28672},context:{utilization:.40}}});
await page.waitForFunction(([ids,before])=>lastUpdatedAt>before&&ids.every(id=>document.getElementById(id).dataset.motionDirection==='increase'),[motionIds,motionSnapshot]);
motionSnapshot=await page.evaluate(()=>lastUpdatedAt);
await cfg({status_patch:{queue_depth:1,prefill:{avg_tps:1700.4},decode:{avg_tps:44.7},request:{cached_tokens:16384},context:{utilization:.20}}});
await page.waitForFunction(([ids,before])=>lastUpdatedAt>before&&ids.every(id=>document.getElementById(id).dataset.motionDirection==='decrease'),[motionIds,motionSnapshot]);
assert(await page.locator('.metric-value-layer').count()<=motionIds.length*2,'metric motion layers accumulated');
motionSnapshot=await page.evaluate(()=>lastUpdatedAt);
await cfg({reset:true});
await page.waitForFunction(before=>lastUpdatedAt>before,motionSnapshot);
```

电报结果节点在生产标记中统一使用 `.result`；这是状态色测试的稳定接口。

删除其后旧的 `monitorPrefill/monitorDecode` 通用 `animationName` 断言；方向滚动已经由 `data-motion-direction` 与 layer 上限覆盖。保留并单独断言 `monitorPrefillBar`、`monitorDecodeBar` 存在。

同步替换旧 `.monitor-metrics` 六等列响应式断言：1200px 断言 `.monitor-grid` 为两列、`#monitorMetrics` 有 6 个直接 `.vital` 子节点且 `overflow-x:hidden`；700px 检查 `#monitorMetrics>.vital` 无内部左边框；390px 检查 `#monitorMetrics` 为单列、host 为单列且请求按钮 ≥44px。不得为了让旧 `metrics===6` 通过而恢复六张等宽指标格。

- [ ] **Step 3: 增加 reduced-motion、移动端和首屏边界断言。**

在最终截图验收段加入：

```js
await page.emulateMedia({reducedMotion:'reduce'});
const reduced=await page.evaluate(()=>({
  light:getComputedStyle(document.querySelector('.light-field')).animationName,
  mode:getComputedStyle(document.querySelector('.mode-layout:not([hidden])')).animationName
}));
assert(reduced.light==='none'&&reduced.mode==='none','reduced motion still animates the wall or mode');
await page.emulateMedia({reducedMotion:'no-preference'});
await page.setViewportSize({width:390,height:844});
const mobileLumen=await page.evaluate(()=>({
  overflow:document.documentElement.scrollWidth>innerWidth,
  light:getComputedStyle(document.querySelector('.light-field')).animationName,
  blur:getComputedStyle(document.querySelector('.glass-column')).backdropFilter
}));
assert(!mobileLumen.overflow&&mobileLumen.light==='none','mobile wall overflows or keeps ambient animation');
const mobileBlur=parseFloat((mobileLumen.blur.match(/blur\(([^p]+)px\)/)||[])[1]||'0');
assert(mobileBlur<=12,'mobile glass blur exceeds 12px');
```

保留原有 1440×900 `fifthRowBottom<=901` 与 `lastInspectorFactBottom<=901`，它们是重构前已存在失败的修复门禁。

- [ ] **Step 4: 更新 C 端页面字面量断言。**

在 `test_dashboard_page_is_served_as_html()` 中：

```c
TEST_ASSERT(strstr(out, "data-mode=\"monitor\"") != NULL);
TEST_ASSERT(strstr(out, "class=\"light-field\"") != NULL);
TEST_ASSERT(strstr(out, "class=\"num-wall\"") != NULL);
TEST_ASSERT(strstr(out, "class=\"glass-column monitor-console\"") != NULL);
TEST_ASSERT(strstr(out, "data-mirror=\"decode\"") != NULL);
TEST_ASSERT(strstr(out, "data-theme-choice") == NULL);
TEST_ASSERT(strstr(out, "ds4-dashboard-theme") == NULL);
```

将旧的 `data-mode="management"` 正向断言删除。其他端点、id、安全函数与状态机断言全部保留。

- [ ] **Step 5: 运行 RED，确认失败原因正确。**

Run:

```bash
DS4_DASHBOARD_TEST_PORT=18766 ./tests/run_dashboard_ui_test.sh
make ds4_test
./ds4_test --server
```

Expected: 浏览器测试在 `legacy theme controls remain` 或 B1 DOM/token 断言处失败，早于既存 inspector 首屏失败；C server test 因缺少 `.light-field`/`.num-wall`/`.glass-column` 或仍包含主题系统而失败。不得出现 JS 语法错误、fixture 提取错误或测试自身错误。

- [ ] **Step 6: 检查测试 Diff。**

Run `git diff -- tests/dashboard_ui_test.js ds4_server.c`，确认 `ds4_server.c` 只改到 `test_dashboard_page_is_served_as_html()` 的断言区，没有改生产 `dashboard_html`。

如能安全隔离提交：`git commit -m "test(dashboard): specify lumen wall redesign"`；否则保留为未提交逻辑检查点。

---

### Task 2: 绿地重写 B1 CSS 与 DOM，保留稳定 id

**Files:**
- Modify: `ds4_server.c:8198-8228` (`dashboard_html` 的 `<style>` 与 `<body>` 标记)
- Test: `tests/dashboard_ui_test.js`

**Interfaces:**
- Consumes: Task 1 的 B1 selectors 与全部现有稳定 id。
- Produces: `.light-field`、`.num-wall`、唯一 `.glass-column`、五个 `data-mirror`、管理/监控两模式和原有管理控件 DOM。

- [ ] **Step 1: 用批准 token 替换旧主题 CSS。**

新的根 token 必须从以下内容开始，不保留任何 `:root[data-theme=*]`：

```css
:root{color-scheme:light;--wall:#e9eaed;--surface:rgba(255,255,255,.55);--ink:#1b1e24;--muted:#676c74;--line:rgba(27,30,36,.12);--success:#15803d;--danger:#dc2626;--warning:#b45309;--selected:rgba(27,30,36,.07);--control-height:44px;--motion-fast:180ms;--motion-smooth:360ms;--instrument-font:SFMono-Regular,Menlo,Consolas,"Hiragino Sans GB","PingFang SC","Microsoft YaHei","Arial Unicode MS",monospace}
body{margin:0;min-height:100vh;background:linear-gradient(158deg,#f3f4f6 0%,#e9eaed 52%,#dcdde1 100%);color:var(--ink);overflow-x:hidden}
.light-field{position:fixed;z-index:-2;width:1100px;height:780px;left:-180px;top:-260px;pointer-events:none;background:radial-gradient(ellipse at center,rgba(255,255,255,.92) 0%,rgba(255,255,255,.62) 34%,rgba(255,255,255,0) 70%);animation:lumen-drift 60s ease-in-out infinite alternate;will-change:transform}
.light-shadow{position:fixed;z-index:-2;width:780px;height:620px;right:-150px;bottom:-250px;pointer-events:none;background:radial-gradient(ellipse at center,rgba(148,153,161,.18),rgba(148,153,161,0) 68%)}
@keyframes lumen-drift{from{transform:translate3d(-8vw,0,0)}to{transform:translate3d(8vw,2vh,0)}}
.glass-column{background:rgba(255,255,255,.55);backdrop-filter:blur(24px);-webkit-backdrop-filter:blur(24px);border:1px solid rgba(20,24,30,.08);border-top-color:rgba(255,255,255,.75);border-radius:2px;box-shadow:0 24px 64px rgba(20,24,30,.12),0 2px 6px rgba(20,24,30,.06)}
@supports not ((backdrop-filter:blur(1px)) or (-webkit-backdrop-filter:blur(1px))){.glass-column{background:rgba(255,255,255,.88)}}
@media(max-width:760px){.light-field{animation:none;transform:translate3d(2vw,0,0)}.glass-column{backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px)}}
@media(prefers-reduced-motion:reduce){*,*:before,*:after{animation:none!important;transition:none!important}.light-field{transform:translate3d(2vw,0,0)}}
```

所有后续样式必须继承这些 token。删除 `.theme-switch`、旧玻璃主题、彩色 radial gradient、指针追光、12–16px 卡片圆角与绿色实心按钮规则。

- [ ] **Step 2: 建立共享桅杆和监控幕墙 DOM。**

页面开头必须保持以下结构和属性：

```html
<body><div class="light-field" aria-hidden="true"></div><div class="light-shadow" aria-hidden="true"></div>
<main class="page" id="dashboard" data-mode="monitor">
  <header class="topbar">
    <div class="brand"><a href="#managementSummary"><span class="status-glyph" aria-hidden="true">◆</span>DS4</a><span id="model" class="model">正在读取状态</span></div>
    <nav class="mode-switch" aria-label="Dashboard 模式">
      <button type="button" data-mode-choice="management" aria-pressed="false">管理模式</button>
      <button type="button" data-mode-choice="monitor" aria-pressed="true">监控模式</button>
    </nav>
    <div id="connectionState" class="state"><span class="status-dot" aria-hidden="true"></span><strong id="health" aria-label="健康">等待中</strong><strong id="updatedAt" aria-label="更新时间">尚未更新</strong></div>
  </header>
```

监控根节点初始可见，结构必须为：

```html
<section id="monitorLayout" class="mode-layout monitor-layout" aria-hidden="false" aria-labelledby="monitorTitle">
  <h1 id="monitorTitle" class="monitor-title">实时运行</h1>
  <p class="model">实时吞吐与最近调用检查器</p>
  <div class="monitor-grid">
    <section id="monitorMetrics" class="num-wall" aria-label="实时体征">
      <span class="wall-mirror wall-mirror-decode" data-mirror="decode" aria-hidden="true">—</span>
      <span class="wall-mirror wall-mirror-prefill" data-mirror="prefill" aria-hidden="true">—</span>
      <span class="wall-mirror wall-mirror-cache" data-mirror="cache" aria-hidden="true">—</span>
      <span class="wall-mirror wall-mirror-context" data-mirror="context" aria-hidden="true">—</span>
      <span class="wall-mirror wall-mirror-queue" data-mirror="queue" aria-hidden="true">—</span>
      <div class="vital vital-phase"><span class="eyebrow">阶段 / 活动</span><strong id="monitorPhase" class="mono">—</strong><span id="monitorPhaseMeta" class="metric-phase-meta">服务 · —</span></div>
      <div class="vital vital-prefill"><span class="eyebrow">预填充速度</span><strong id="monitorPrefill" class="mono metric-value" data-motion-direction="none"><span class="metric-value-window"><span class="metric-value-layer">—</span></span></strong><span id="monitorPrefillMeta" class="metric-subvalue">—</span><div class="metric-bar" aria-hidden="true"><span id="monitorPrefillBar"></span></div></div>
      <div class="vital vital-decode"><span class="eyebrow">解码速度</span><strong id="monitorDecode" class="mono metric-value" data-motion-direction="none"><span class="metric-value-window"><span class="metric-value-layer">—</span></span></strong><span id="monitorDecodeMeta" class="metric-subvalue">—</span><div class="metric-bar" aria-hidden="true"><span id="monitorDecodeBar"></span></div></div>
      <div class="vital vital-cache"><span class="eyebrow">请求 KV 命中</span><strong id="monitorCacheHit" class="mono metric-value" data-motion-direction="none"><span class="metric-value-window"><span class="metric-value-layer">—</span></span></strong></div>
      <div class="vital vital-context"><span class="eyebrow">上下文利用率</span><strong id="monitorContext" class="mono metric-value" data-motion-direction="none"><span class="metric-value-window"><span class="metric-value-layer">—</span></span></strong></div>
      <div class="vital vital-queue"><span class="eyebrow">队列 / 客户端</span><strong id="monitorQueue" class="mono metric-value" data-motion-direction="none"><span class="metric-value-window"><span class="metric-value-layer">—</span></span></strong></div>
    </section>
    <aside class="glass-column monitor-console" aria-label="调用电报与请求检查器">
      <section class="monitor-panel" aria-labelledby="monitorCallsTitle"><div class="section-head"><h2 id="monitorCallsTitle">调用电报</h2><p id="monitorCallsActive" class="caption">当前活动请求：—</p></div><div class="call-filters"><input id="callFilterCaller" data-call-filter="caller" aria-label="按调用方筛选" placeholder="调用方"><select id="callFilterClient" data-call-filter="client" aria-label="按服务筛选"><option value="">全部服务</option></select><select id="callFilterApi" data-call-filter="api" aria-label="按 API 筛选"><option value="">全部 API</option></select><select id="callFilterStatus" data-call-filter="result" aria-label="按结果筛选"><option value="">全部结果</option><option value="active">进行中</option><option value="completed">完成</option><option value="failed">失败</option></select></div><div class="monitor-table-wrap call-table-wrap"><table class="monitor-table"><thead><tr><th>请求</th><th>服务</th><th>调用方</th><th>API</th><th>结果</th><th>时长</th><th>错误</th></tr></thead><tbody id="monitorCalls"></tbody></table></div></section>
      <aside id="requestInspector" class="monitor-panel inspector" tabindex="-1" aria-labelledby="requestInspectorTitle"><h2 id="requestInspectorTitle">请求检查器</h2><p class="caption">请选择一条调用记录</p></aside>
    </aside>
    <section id="monitorHost" class="monitor-host host-rail" aria-labelledby="monitorHostTitle"><div class="section-head"><h2 id="monitorHostTitle">主机资源</h2><p class="caption">系统采样不可用时明确标注。</p></div><div class="host-ruler"><div><span class="eyebrow">内存压力 / Swap</span><strong id="monitorHostPressure" class="mono">不可用</strong></div><div><span class="eyebrow">物理内存 已用 / 总量 / 可用</span><strong id="monitorHostPhysical" class="mono">不可用</strong></div><div><span class="eyebrow">DS4 RSS</span><strong id="monitorHostRss" class="mono">不可用</strong></div></div></section>
  </div>
</section>
```

五个镜像是唯一新增的数据镜像，全部 `aria-hidden`。六个 `.vital` 必须保持为 `#monitorMetrics` 的直接 `div` 子节点，现有按索引处理指标的代码在 Task 3 清理完成前仍能定位同一顺序。

- [ ] **Step 3: 将管理模式映射到同一墙/柱结构。**

`#managementLayout` 初始 `hidden aria-hidden="true"`。按以下精确 DOM 树重排现有节点；列出的 subtree 从当前标记整体移动，所有后代属性与文案保持不变：

```text
#managementLayout.mode-layout.management-layout[hidden][aria-hidden="true"]
├── h1#managementTitle（运行与容量）
└── .management-grid
    ├── .management-wall.num-wall
    │   ├── section#managementSummary.management-summary
    │   │   ├── #managementPhase + #managementQueue
    │   │   ├── #managementContext + #managementContextRatio
    │   │   └── #managementKv + #managementKvRatio
    │   ├── section#managementRecent.management-section
    │   │   ├── #managementCallsActive
    │   │   └── table > tbody#managementRecentCalls
    │   └── section#managementHost.management-section
    │       └── .host-ruler > #managementHostPressure + #managementHostPhysical + #managementHostRss
    └── aside.glass-column.management-console
        ├── aside.management-nav > nav[aria-label="管理章节"]（五个现有锚点）
        └── .settings-grid
            ├── section#kvCapacity.setting-block[tabindex="-1"]
            │   ├── #kvEffect + #kvUsed + #kvBudget + #kvEntries + #kvUtilization + #kvBar
            │   └── form#kvForm
            │       ├── #kvBudgetInput + #kvBudgetUnit + #budgetHelp + #kvTargetState
            │       ├── #kvApplyNow + #kvSaveRestart
            │       ├── section#kvReview[hidden][tabindex="-1"] > #kvReviewTitle + #kvReviewFacts + #kvConfirmApply + #kvCancelApply
            │       └── #adminNotice[role="status"][aria-live="polite"]
            └── section#contextCapacity.setting-block
                ├── #contextEffect + #contextCurrent + #contextRemaining + #contextUtilization
                └── form#contextForm > #contextNextInput + #contextSaveRestart + #contextNotice[role="status"][aria-live="polite"]
```

`.settings-grid` 只负责柱内分段和断点，不获得独立背景、blur、阴影或大圆角；`#kvCapacity` 与 `#contextCapacity` 仅使用发丝线分隔。

- [ ] **Step 4: 将调用表格视觉改为电报流但保留语义。**

- `#monitorCalls` 继续是 `<tbody>`，行保留 `data-request-id`/`aria-selected`；
- `.request-select` 继续是 44px 按钮和 `aria-controls="requestInspector"`；
- 结果单元格统一加 `.result`；
- 请求、服务、API、状态与时长形成可见电报主行；调用方和错误继续存在于行语义或检查器，恶意文本不得隐藏到 `innerHTML`；
- `.call-table-wrap` 是唯一允许横向滚动的容器；
- 1440×900 下列表与检查器使用紧凑行距，让第五行和最后一个 `dd` 均在 900px 内。

- [ ] **Step 5: 运行结构测试并检查页面提取。**

Run:

```bash
python3 -m py_compile tests/dashboard_fixture.py
DS4_DASHBOARD_TEST_PORT=18766 ./tests/run_dashboard_ui_test.sh
```

Expected: fixture 能提取并启动页面；主题、DOM、token、玻璃和 viewport 的测试向 GREEN 推进。若因镜像未同步、方向动效或 JS 主题逻辑而失败，失败必须对应 Task 3，而不是 HTML 语法或缺失稳定 id。

- [ ] **Step 6: 检查 production hunk。**

Run `git diff --check -- ds4_server.c` 和 `git diff --word-diff=plain -- ds4_server.c`。确认性能配置测试与本任务无关 hunk 未改变。

如能安全隔离提交：`git commit -m "dashboard: rebuild shell as lumen wall"`；否则保留为未提交逻辑检查点。

---

### Task 3: 清理主题 JS，接入监控默认、方向滚动和镜像同步

**Files:**
- Modify: `ds4_server.c:8229-8284` (`dashboard_html` 内嵌 JavaScript)
- Test: `tests/dashboard_ui_test.js`

**Interfaces:**
- Consumes: Task 2 的稳定 id、`.metric-value-window` 与 `data-mirror`。
- Produces: 无主题副作用的模式初始化、五指标方向元数据和同步镜像。

- [ ] **Step 1: 删除主题和指针追光逻辑。**

完整删除：

- `themeValues`；
- `setTheme()`；
- `[data-theme-choice]` event listeners；
- `ds4-dashboard-theme` 读取/写入；
- `glassLightFrame` 与 `pointermove`；
- `documentElement.dataset.theme` 与 `dash.dataset.theme` 赋值。

保留 `ds4-dashboard-mode`。将模式回退改为：

```js
function setMode(value){
  const mode=['management','monitor'].includes(value)?value:'monitor';
  dash.dataset.mode=mode;
  for(const name of ['management','monitor']){
    const root=$(name+'Layout'),active=name===mode;
    root.hidden=!active;
    root.setAttribute('aria-hidden',String(!active));
  }
  try{localStorage.setItem('ds4-dashboard-mode',mode)}catch(e){}
  document.querySelectorAll('[data-mode-choice]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.modeChoice===mode)));
}
try{setMode(localStorage.getItem('ds4-dashboard-mode'))}catch(e){setMode('monitor')}
```

删除现有尾部 `if(!['management','monitor'].includes(window.__ds4InitialMode))setMode('monitor')` 补丁，避免双重初始化。

- [ ] **Step 2: 实现五指标双层方向滚动。**

将五个可动指标标记为：

```html
<strong id="monitorDecode" class="mono metric-value" data-motion-direction="none"><span class="metric-value-window"><span class="metric-value-layer">—</span></span></strong>
```

其他四个只替换 id。新增 helper：

```js
const metricMotionValues=Object.create(null),metricMotionText=Object.create(null);
function metricText(id,value,raw){
  const node=$(id),windowNode=node&&node.querySelector('.metric-value-window'),next=String(value);
  if(!node||!windowNode)return;
  const numeric=finite(raw)?Number(raw):null,previous=metricMotionValues[id];
  const direction=numeric!=null&&previous!=null&&numeric!==previous?(numeric>previous?'increase':'decrease'):'none';
  node.dataset.motionDirection=direction;
  if(numeric==null)delete metricMotionValues[id];else metricMotionValues[id]=numeric;
  if(metricMotionText[id]===next)return;
  const incoming=document.createElement('span');incoming.className='metric-value-layer';incoming.textContent=next;
  const token=(node.__metricMotionToken||0)+1;node.__metricMotionToken=token;
  const finish=()=>{if(node.__metricMotionToken!==token)return;windowNode.replaceChildren(incoming);incoming.className='metric-value-layer';syncMetricMirror(id,next)};
  if(direction==='none'||matchMedia('(prefers-reduced-motion: reduce)').matches){windowNode.replaceChildren(incoming);metricMotionText[id]=next;syncMetricMirror(id,next);return}
  const outgoing=document.createElement('span');outgoing.className='metric-value-layer metric-value-layer-out-'+direction;outgoing.textContent=metricMotionText[id]||windowNode.textContent||'—';outgoing.setAttribute('aria-hidden','true');
  incoming.className='metric-value-layer metric-value-layer-in-'+direction;
  windowNode.replaceChildren(outgoing,incoming);incoming.addEventListener('animationend',finish,{once:true});setTimeout(finish,460);metricMotionText[id]=next;
}
```

CSS 使用已有方向 plan 中的四组 transform/opacity keyframes，持续 420ms，`.metric-value-window` 固定高度并 `overflow:hidden`。reduced-motion 下不运行关键帧。

- [ ] **Step 3: 同步五个幽灵镜像。**

新增明确映射：

```js
const metricMirrorNames={monitorDecode:'decode',monitorPrefill:'prefill',monitorCacheHit:'cache',monitorContext:'context',monitorQueue:'queue'};
function syncMetricMirror(id,value){
  const name=metricMirrorNames[id],mirror=name&&document.querySelector('[data-mirror="'+name+'"]');
  if(mirror&&mirror.textContent!==String(value))mirror.textContent=String(value);
}
```

首次/直接更新与 reduced-motion 立即同步；方向动画在新值落位后同步。stale/offline 不调用 paint，因此镜像自然保留最后值。

- [ ] **Step 4: 从 `paintMonitor()` 传入原始比较值。**

保持现有格式化文本不变，将五个 `text()` 替换为：

```js
metricText('monitorPrefill',prefillDisplay,finite(p.avg_tps)?p.avg_tps:null);
metricText('monitorDecode',decodeDisplay,finite(d.avg_tps)?d.avg_tps:null);
metricText('monitorCacheHit',cacheDisplay,cacheRatio);
metricText('monitorContext',contextDisplay,finite(x.utilization)?x.utilization:null);
metricText('monitorQueue',queueDisplay,finite(s.queue_depth)?s.queue_depth:null);
```

使用函数内已经计算的显示变量或按现有格式生成等价变量；禁止解析格式化后的中文字符串。`monitorPhase` 继续使用普通 `text()`。

- [ ] **Step 5: 保持原业务函数完整。**

逐项确认下列函数仍存在且核心表达式未改：

- `tick`、`paint`、`paintManagement`、`paintMonitor`、`paintCalls`、`paintRecentCalls`；
- `setKvState`、`showKvReview`、`checkKvImpact`、`confirmKvApply`、`cancelKvApply`、`persistKvBudget`；
- `saveContext`、`contextControls`；
- `admin('dry-run'|'apply'|'persist')` 与 revision 参数；
- `ds4StableCallsPersistent` 的服务标识记忆逻辑。

只允许因新 DOM 位置更新选择器，不改变其状态转换、请求或安全语义。

- [ ] **Step 6: 运行 GREEN。**

Run:

```bash
DS4_DASHBOARD_TEST_PORT=18766 ./tests/run_dashboard_ui_test.sh
make ds4_test
./ds4_test --server
```

Expected: 所有新增 B1 断言、既有 295 行行为回归、既存 inspector 首屏边界和 C server tests 全部 PASS，输出无 JS/page error。

如能安全隔离提交：`git commit -m "dashboard: integrate lumen wall interactions"`；否则保留为未提交逻辑检查点。

---

### Task 4: 文档同步、真实浏览器 QA 与最终范围复核

**Files:**
- Modify: `README.md:751-760`
- Verify: `ds4_server.c`, `tests/dashboard_ui_test.js`, design/plan docs
- Generate locally: `output/playwright/dashboard-*.png`

**Interfaces:**
- Consumes: 通过自动化回归的 B1 页面。
- Produces: 与实际产品一致的 README、四张验收截图和最终验证记录。

- [ ] **Step 1: 更新 README 的模式和视觉说明。**

将旧多主题段落替换为：

```markdown
The dashboard has two task modes under one monochrome “lumen wall” visual
system. **Monitor** is the default for live metrics, filterable recent calls,
the request inspector, and host resources. **Management** provides runtime
state, disk-KV and context settings, their effects, and operation results.
The selected mode is saved only in that browser's `localStorage` under
`ds4-dashboard-mode`; it does not change server configuration or data. The
background uses a reduced-motion-aware grayscale light field; red and green
are reserved for operational status.
```

删除 `ds4-dashboard-theme` 和主题名称表述。

- [ ] **Step 2: 启动 fixture 做桌面与移动真实浏览器检查。**

以空闲端口启动 fixture，使用 Playwright 检查 1440×900 和 390×844：

- 管理/监控切换；
- 过滤与请求选择；
- KV dry-run、取消和确认；
- stale/offline/recovery；
- reduced-motion；
- 控制台 error 和 pageerror；
- `scrollWidth`、玻璃 computed style、光团 60s 与移动端静止；
- 五条调用与完整检查器首屏边界。

生成并人工查看：

```text
output/playwright/dashboard-monitor-desktop.png
output/playwright/dashboard-management-desktop.png
output/playwright/dashboard-monitor-mobile.png
output/playwright/dashboard-management-mobile.png
```

- [ ] **Step 3: 执行完整验证。**

Run:

```bash
DS4_DASHBOARD_TEST_PORT=18766 ./tests/run_dashboard_ui_test.sh
make ds4_test
./ds4_test --server
git diff --check
```

Expected: 浏览器与 server 测试全部通过；无 whitespace error；截图无彩色环境光、无白卡阵列、无文本裁切和页面溢出。

- [ ] **Step 4: 自审 spec coverage 和最终 Diff。**

逐节对照 `docs/superpowers/specs/2026-07-22-dashboard-lumen-wall-design.md`：

- 主题删除、B1 token、唯一玻璃柱、巨数双层、60s/reduced-motion；
- 管理/监控 IA；
- 1440/390；
- KV/context/polling/security/a11y；
- README。

Run:

```bash
git status --short
git diff --stat
git diff -- ds4_server.c tests/dashboard_ui_test.js README.md docs/superpowers/specs/2026-07-22-dashboard-lumen-wall-design.md docs/superpowers/plans/2026-07-22-dashboard-lumen-wall.md
```

确认 `.learnings`、启动性能文档、`start-server.sh`、二进制和其他 output 未被本任务修改或暂存。

- [ ] **Step 5: 最终实现复核。**

调用 `superpowers:verification-before-completion`，再做一次 K3 只读设计复核。只修复可复现的阻塞问题；任何超出批准 spec 的新方向留作后续任务。
