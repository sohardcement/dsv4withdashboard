# Dashboard 实时信号层 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不伪造业务数据的前提下，让 DS4 Dashboard 在静态数据时仍具备可感知、克制的实时节奏。

**Architecture:** Dashboard 继续由 `ds4_server.c` 的内嵌 HTML/CSS/JS 单文件实现。每次成功 `paint(snapshot)` 后由一个轻量 `cueFreshness()` 触发连接区回执；数值仍只在实际值变动时滚动，进度条改为 CSS 宽度过渡。CSS 媒体查询与既有 `setStale()` 继续作为全局动效熔断器。

**Tech Stack:** C99 字符串内嵌 HTML/CSS/JavaScript、Node/Playwright Dashboard UI 回归、Python fixture server。

## Global Constraints

- 不改变 `/ds4/status`、KV、上下文或推理后端契约。
- 轮询回执仅在成功渲染真实快照后启动；失败、`stale`、`prefers-reduced-motion: reduce` 时不启动。
- 移动端不得运行连续环境光；390px 页面不得横向滚动。
- 不引入新依赖；不使用弹跳、彩色流光、粒子或伪造指标变化。
- 保留现有未提交工作区改动；本轮不自动提交、推送或创建 PR。

---

### Task 1: 为实时信号层写失败的浏览器契约

**Files:**
- Modify: `tests/dashboard_ui_test.js:220-445`
- Modify: `tests/dashboard_fixture.py`（仅当 fixture 需要暴露固定的连续成功快照时）

**Interfaces:**
- Consumes: 现有 `cfg(patch)`、`reloadReady()`、`page.emulateMedia()` 和 fixture 的 `/config` 状态覆写。
- Produces: 对 `#connectionPulse`、`#updatedAt`、`.light-field`、`.light-shadow`、`.metric-bar span` 和 `document.getAnimations()` 的可重复验收。

- [x] **Step 1: 写入轮询回执与进度条的失败断言**

  在首次 `cfg({reset:true})` 成功渲染之后，追加以下浏览器检查。测试应记录回执动画的开始时间和动画名称，而不是用截图推测动画存在。

  ```js
  const signalBefore = await page.evaluate(() => ({
    pulse: document.getElementById('connectionPulse').dataset.signalRevision || '0',
    stamp: document.getElementById('updatedAt').dataset.signalRevision || '0'
  }));
  await cfg({status_patch:{queue_depth:2}});
  await page.waitForFunction(before => {
    const state = document.getElementById('connectionPulse');
    const stamp = document.getElementById('updatedAt');
    return Number(state.dataset.signalRevision || 0) > Number(before.pulse) &&
      Number(stamp.dataset.signalRevision || 0) > Number(before.stamp);
  }, signalBefore);
  const signal = await page.evaluate(() => {
    const pulse=document.getElementById('connectionPulse'),stamp=document.getElementById('updatedAt'),prefill=document.getElementById('monitorPrefillBar'),decode=document.getElementById('monitorDecodeBar');
    return {
      pulseRevision:Number(pulse.dataset.signalRevision||0),
      stampRevision:Number(stamp.dataset.signalRevision||0),
      pulseAnimations:pulse.getAnimations().map(a=>({duration:a.effect.getTiming().duration,playState:a.playState})),
      stampAnimations:stamp.getAnimations().map(a=>({duration:a.effect.getTiming().duration,playState:a.playState})),
      prefillWidthTransition:getComputedStyle(prefill).transitionProperty,
      decodeWidthTransition:getComputedStyle(decode).transitionDuration
    };
  });
  assert(signal.pulseRevision>0&&signal.stampRevision>0&&signal.pulseAnimations.some(a=>a.duration===620)&&signal.stampAnimations.some(a=>a.duration===420)&&signal.prefillWidthTransition.includes('width')&&parseFloat(signal.decodeWidthTransition)>0,'successful polling does not cue the signal layer or progress transition');
  ```

- [x] **Step 2: 运行测试，确认新断言失败**

  Run: `DS4_DASHBOARD_TEST_PORT=18787 tests/run_dashboard_ui_test.sh`

  Expected: FAIL because current Dashboard lacks `#connectionPulse` and signal revisions; after Task 2 the same assertion must pass without relaxing it.

- [x] **Step 3: 补齐降级与交互动效契约**

  在既有 reduced-motion、mobile、stale 断言附近加入以下检查：

  ```js
  await page.emulateMedia({reducedMotion:'reduce'});
  await cfg({status_patch:{queue_depth:3}});
  await page.waitForFunction(()=>document.getElementById('dashboard').classList.contains('stale')===false);
  const reducedSignal = await page.evaluate(() => ({
    state: document.getElementById('connectionPulse').getAnimations().filter(a=>a.playState==='running').length,
    stamp: document.getElementById('updatedAt').getAnimations().filter(a=>a.playState==='running').length,
    light: getComputedStyle(document.querySelector('.light-field')).animationName,
    shadow: getComputedStyle(document.querySelector('.light-shadow')).animationName
  }));
  assert(reducedSignal.state===0&&reducedSignal.stamp===0&&reducedSignal.light==='none'&&reducedSignal.shadow==='none','reduced motion still starts dashboard signal animations');
  await page.emulateMedia({reducedMotion:'no-preference'});
  await page.setViewportSize({width:390,height:844});
  const mobileSignal = await page.evaluate(() => ({
    light:getComputedStyle(document.querySelector('.light-field')).animationName,
    shadow:getComputedStyle(document.querySelector('.light-shadow')).animationName,
    width:document.documentElement.scrollWidth,
    viewport:innerWidth
  }));
  assert(mobileSignal.light==='none'&&mobileSignal.shadow==='none'&&mobileSignal.width<=mobileSignal.viewport,'mobile signal layer animates continuously or causes overflow');
  ```

- [x] **Step 4: 运行完整测试，记录仍待实现的失败**

  Run: `DS4_DASHBOARD_TEST_PORT=18787 tests/run_dashboard_ui_test.sh`

  Expected: FAIL only on the newly added real-time signal assertions; existing Dashboard contracts remain green up to that point.

### Task 2: 实现真实轮询回执、环境节奏与操作反馈

**Files:**
- Modify: `ds4_server.c:8199-8339`
- Test: `tests/dashboard_ui_test.js:220-445`

**Interfaces:**
- Consumes: DOM IDs `dashboard`、`connectionState`、`updatedAt`、`monitorPrefillBar`、`monitorDecodeBar`；`paint(snapshot)` 和 `setStale(flag)`。
- Produces: `cueFreshness()`、`motionAllowed()`、`data-signal-revision` 语义，以及不超过设计时长的 CSS 动效。

- [x] **Step 1: 为连接区和环境光添加结构与 CSS**

  给在线圆点增加稳定 ID `#connectionPulse`，保留现有 `#connectionState` 容器和 `#updatedAt` 时间文本 ID：

  ```html
  <div id="connectionState" class="state"><span id="connectionPulse" class="status-dot" aria-hidden="true"></span><strong id="health" aria-label="健康">等待中</strong><strong id="updatedAt" aria-label="更新时间">尚未更新</strong></div>
  ```

  将环境层改为两个不同相位的动画，并补充如下规则（嵌入 C 字符串时保留转义）：

  ```css
  .light-field{animation:signal-drift 18s cubic-bezier(.42,0,.58,1) infinite alternate;will-change:transform}
  .light-shadow{animation:signal-shadow 26s cubic-bezier(.42,0,.58,1) infinite alternate;will-change:transform}
  @keyframes signal-drift{from{transform:translate3d(-5vw,-1vh,0)}to{transform:translate3d(5vw,2vh,0)}}
  @keyframes signal-shadow{from{transform:translate3d(3vw,2vh,0)}to{transform:translate3d(-4vw,-2vh,0)}}
  .metric-bar span{transition:width 360ms cubic-bezier(.22,.8,.24,1),background-color var(--motion-fast) ease}
  button,input,select,.status-dot,.metric-bar span{transition:transform var(--motion-fast) ease,background-color var(--motion-fast) ease,color var(--motion-fast) ease,border-color var(--motion-fast) ease,box-shadow var(--motion-fast) ease}
  @media(hover:hover) and (pointer:fine){.mode-switch button:hover,.call-filters input:hover,.call-filters select:hover{transform:translateY(-1px);border-color:rgba(27,30,36,.36);box-shadow:0 6px 16px rgba(20,24,30,.08)}.monitor-table tbody tr:not([aria-selected=true]):hover{box-shadow:inset 2px 0 0 rgba(27,30,36,.32);padding-left:12px}}
  ```

  扩展既有 `@media(max-width:760px)` 与 `@media(prefers-reduced-motion:reduce)`，同时禁用 `.light-field` 和 `.light-shadow` 的连续动画；保留 `stale` 的全局动效熔断。

- [x] **Step 2: 以 Web Animations API 实现无伪造数据的轮询回执**

  在 `paint(snapshot)` 前定义以下函数，并在 `setStale(false)` 后调用。使用元素级 `animate()`，避免通过读布局属性重启动画；每次回执写递增 revision，供测试验证。`setStale(true)` 与低动效媒体查询变更必须取消正在运行的回执。

  ```js
  let signalRevision=0;
  const reducedMotion=matchMedia('(prefers-reduced-motion: reduce)');
  function freshnessNodes(){return [$('connectionPulse'),$('updatedAt')].filter(Boolean)}
  function clearFreshness(){freshnessNodes().forEach(node=>node.getAnimations().forEach(animation=>animation.cancel()))}
  function motionAllowed(){return !dash.classList.contains('stale')&&!reducedMotion.matches}
  function cueFreshness(){
    if(!motionAllowed())return;
    const pulse=$('connectionPulse'),stamp=$('updatedAt');
    if(!pulse||!stamp)return;
    const revision=String(++signalRevision);
    pulse.dataset.signalRevision=revision;
    stamp.dataset.signalRevision=revision;
    pulse.getAnimations().forEach(animation=>animation.cancel());
    stamp.getAnimations().forEach(animation=>animation.cancel());
    pulse.animate([{boxShadow:'0 0 0 0 rgba(27,30,36,.18)'},{boxShadow:'0 0 0 10px rgba(27,30,36,0)',offset:.7},{boxShadow:'none'}],{duration:620,easing:'cubic-bezier(.22,.8,.24,1)'});
    stamp.animate([{opacity:.55,transform:'translateY(1px)'},{opacity:1,transform:'none'}],{duration:420,easing:'ease-out'});
  }
  if(reducedMotion.addEventListener)reducedMotion.addEventListener('change',()=>{if(reducedMotion.matches)clearFreshness()});
  function paint(s){validateSnapshot(s);const previous=lastSnapshot;try{renderSnapshot(s)}catch(error){if(previous)renderSnapshot(previous);throw error}lastSnapshot=s;lastUpdatedAt=Date.now();online=true;kvEnabled=s.kv_cache.enabled===true;currentKvBudgetBytes=kvEnabled?s.kv_cache.budget_bytes:null;setStale(false);text('updatedAt',freshnessLabel(false));cueFreshness();updateKvTargetState();contextControls();setKvState(kvState)}
  ```

  Update `setStale(flag)` so `flag===true` calls `clearFreshness()`. Do not call `cueFreshness()` from `tick()` error handling or user input handlers. Preserve existing number-roll timing and `lastUpdatedAt` semantics.

- [x] **Step 3: 将模式与操作动效调至设计时长**

  将 `.mode-layout` 与 `.mode-enter` 使用的时长设置为 `280ms`，并加一个仅影响内容容器的短错峰：

  ```css
  --motion-mode:280ms;
  .mode-layout,.mode-enter{animation:mode-in var(--motion-mode) cubic-bezier(.22,.8,.24,1) both}
  .mode-enter>.model{animation:mode-subtitle 220ms 40ms ease both}
  @keyframes mode-subtitle{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
  ```

  将既有测试的非数据动效上限从 240ms 改为 `<=280ms`，将截图前的 `wait(260)` 改为 `wait(300)`，并保持行和控件反馈不超过 200ms。把恢复在线状态断言中的 `lumen-drift` 更新为 `signal-drift`，并额外断言 `light-shadow` 也在桌面在线时运行。

- [x] **Step 4: 运行新增浏览器契约，确认通过**

  Run: `DS4_DASHBOARD_TEST_PORT=18787 tests/run_dashboard_ui_test.sh`

  Expected: PASS；断言成功轮询会产生 `620ms`/`420ms` 回执、真实数值动画不积累、reduced-motion/stale/mobile 没有连续动效、布局和交互无回归。

### Task 3: 进行服务端、静态与可视化回归

**Files:**
- Modify: `docs/superpowers/specs/2026-07-22-dashboard-live-signal-motion-design.md`（仅在验收发现需要澄清实现边界时）
- Verify: `ds4_server.c`、`tests/dashboard_ui_test.js`

**Interfaces:**
- Consumes: Task 1–2 的完整 Dashboard UI 回归和本地 fixture。
- Produces: 已验证的本地预览、截图和无语义回归结论。

- [x] **Step 1: 执行代码与服务端检查**

  Run:

  ```bash
  git diff --check
  python3 -m py_compile tests/dashboard_fixture.py
  make ds4_test && ./ds4_test --server
  ```

  Expected: 每条命令以 `0` 退出；`server: OK` 和 `ds4 tests: ok` 出现。

- [x] **Step 2: 启动独立本地 fixture 并进行浏览器验收**

  Run:

  ```bash
  python3 tests/dashboard_fixture.py ds4_server.c 18768
  ```

  在浏览器中检查：

  ```js
  ({
    online: !document.getElementById('dashboard').classList.contains('stale'),
    signal: document.getElementById('connectionPulse').dataset.signalRevision,
    desktopField: getComputedStyle(document.querySelector('.light-field')).animationName,
    mobileStops: matchMedia('(max-width: 760px)').matches
  })
  ```

  Expected: 桌面在线时 `signal` 随成功轮询递增、环境光有命名动画；切到 390px 或 stale/reduced-motion 后连续背景动画停止。实际操作模式切换和调用记录选择，确认没有布局跳动或控制台错误。

- [x] **Step 3: 审查最终 Diff，不执行提交**

  Run:

  ```bash
  git diff --check
  git diff -- ds4_server.c tests/dashboard_ui_test.js docs/superpowers/specs/2026-07-22-dashboard-live-signal-motion-design.md
  ```

  Expected: 只有 Dashboard 动效、测试和设计文档相关变更；不暂存、不提交、不推送。
