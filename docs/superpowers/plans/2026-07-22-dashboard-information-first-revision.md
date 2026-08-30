# Dashboard Information-First Revision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将被否决的巨数海报式 Dashboard 修订为可读、可排障、仍有细腻交互反馈的浅色玻璃控制台。

**Architecture:** 页面继续由 `ds4_server.c` 的 `dashboard_html` 单一 C 字符串输出，所有状态 API、DOM id 和管理行为不变。视觉层只调整 CSS、装饰节点和布局；浏览器回归先锁定“没有巨数背景、两列无重叠、窄屏可用”，再由 K3 重构并使用真实截图验收。

**Tech Stack:** C99 内嵌 HTML/CSS/JS、Python Dashboard fixture、Playwright CLI、现有 C server 测试。

## Global Constraints

- 只使用浅色黑白灰环境，不出现深色画框、彩色环境光或巨型数字/文字水印。
- 现有 `/ds4/status`、KV 与上下文管理 API、轮询、筛选、离线、无障碍和安全渲染契约完全不变。
- 桌面右栏固定 `400px`；981–1307px 右栏最小 `360px`、指标降为三列；列间距不少于 `24px`；不允许负边距或跨列覆盖。
- 390px 无页面横滚，只有 `.call-table-wrap` 可以横滚；reduced-motion 与 stale 保持静止语义。
- 真实数值保留既有方向滚动；行选中与按钮保留短反馈；除数值滚动外，互动动画不超过 `240ms`。
- 工作区已有无关未提交变更；不暂存、不提交、不回滚、不修改非 Dashboard 相关 hunk。

---

### Task 1: 为信息优先布局建立失败的浏览器验收契约

**Files:**
- Modify: `tests/dashboard_ui_test.js:322-371`
- Modify: `tests/run_dashboard_ui_test.sh:1-15`
- Test: `tests/run_dashboard_ui_test.sh`

**Interfaces:**
- Consumes: 现有 fixture 的 `/ds4/status` 快照与页面稳定 id：`#monitorMetrics`、`.monitor-grid`、`.monitor-console`、`.glass-column`、`.call-table-wrap`。
- Produces: 一组后续 CSS/DOM 必须满足的 `informationFirst` 浏览器断言，以及桌面、1024px、390px 截图。

- [ ] **Step 1: 在最终验收区加入失败的桌面布局断言**

  在 `tests/dashboard_ui_test.js` 的 1440px 监控模式验收中、截图前插入以下检查；保留现有请求选择和首屏断言：

  ```js
  const informationFirst = await page.evaluate(() => {
    const grid = document.querySelector('.monitor-grid').getBoundingClientRect();
    const metrics = document.getElementById('monitorMetrics').getBoundingClientRect();
    const console = document.querySelector('.monitor-console').getBoundingClientRect();
    const body = getComputedStyle(document.body);
    return {
      mirrors: document.querySelectorAll('.wall-mirror').length,
      gridWidth: grid.width,
      metricsRight: metrics.right,
      consoleLeft: console.left,
      consoleRight: console.right,
      consoleWidth: console.width,
      pageWidth: document.documentElement.scrollWidth,
      viewportWidth: innerWidth,
      outerBackground: body.backgroundColor
    };
  });
  assert(
    informationFirst.mirrors === 0 &&
    informationFirst.consoleWidth >= 399 &&
    informationFirst.consoleLeft - informationFirst.metricsRight >= 24 &&
    informationFirst.consoleLeft >= 0 &&
    informationFirst.consoleRight <= informationFirst.viewportWidth &&
    informationFirst.pageWidth <= informationFirst.viewportWidth,
    'information-first desktop layout still has numeral wallpaper, overlap, clipped console, or page overflow'
  );
  ```

- [ ] **Step 2: 为 1024px 和 390px 加入边界与无装饰节点断言**

  在既有 1024px 管理断言之后追加如下检查；它明确桌面两列和移动单列的边界，而不依赖截图主观判断：

  ```js
  await page.setViewportSize({width:1024,height:900});
  await page.locator('[data-mode-choice="monitor"]').click();
  const compactDesktop = await page.evaluate(() => {
    const metrics = document.getElementById('monitorMetrics').getBoundingClientRect();
    const console = document.querySelector('.monitor-console').getBoundingClientRect();
    return { gap: console.left - metrics.right, width: console.width, sw: document.documentElement.scrollWidth, vw: innerWidth };
  });
  assert(compactDesktop.gap >= 24 && compactDesktop.width >= 360 && compactDesktop.sw <= compactDesktop.vw, '1024px monitor console overlaps, shrinks below 360px, or overflows');
  await page.setViewportSize({width:390,height:844});
  const mobileInformationFirst = await page.evaluate(() => ({
    mirrors: document.querySelectorAll('.wall-mirror').length,
    sw: document.documentElement.scrollWidth,
    vw: innerWidth,
    consoleWidth: document.querySelector('.monitor-console').getBoundingClientRect().width
  }));
  assert(mobileInformationFirst.mirrors === 0 && mobileInformationFirst.sw <= mobileInformationFirst.vw && mobileInformationFirst.consoleWidth > 0, 'mobile information-first layout has wallpaper, page overflow, or missing console');
  ```

- [ ] **Step 3: 让页面断言错误成为进程级失败**

  `playwright-cli run-code` 可能把页面脚本的 `### Error` 打印到标准输出却返回 0。将 `tests/run_dashboard_ui_test.sh` 最后一条直接调用替换为保留原始输出、同时将该标记转换为非零退出的包装：

  ```bash
  set +e
  run_output=$("${cli[@]}" run-code --filename "$root/tests/dashboard_ui_test.js" 2>&1)
  run_status=$?
  set -e
  printf '%s\n' "$run_output"
  if [[ "$run_status" -ne 0 || "$run_output" == *"### Error"* ]]; then
    exit 1
  fi
  ```

  这不改变 fixture、浏览器会话或成功路径；它只确保页面断言失败不能以成功退出码掩盖。

- [ ] **Step 4: 运行测试确认当前版本以非零退出失败**

  Run:

  ```bash
  DS4_DASHBOARD_TEST_PORT=18769 ./tests/run_dashboard_ui_test.sh
  ```

  Expected: non-zero exit；失败信息包含 `information-first desktop layout`，因为当前页面仍插入 `.wall-mirror` 且 `.monitor-console` 使用负左边距。

### Task 2: 移除海报结构并重建无重叠监控栅格

**Files:**
- Modify: `ds4_server.c:8202-8238`
- Modify: `ds4_server.c` 中创建 `.wall-mirror`、`data-mirror` 或镜像文本的 Dashboard 脚本
- Test: `tests/dashboard_ui_test.js:322-371`

**Interfaces:**
- Consumes: Task 1 的 `informationFirst`、`compactDesktop` 与 `mobileInformationFirst` 断言。
- Produces: 无 `.wall-mirror` 节点的监控 DOM；`#monitorMetrics`、`.monitor-console`、`#monitorCalls`、`#requestInspector` id 和行为保持不变。

- [ ] **Step 1: 删除巨数背景的 CSS 与运行时镜像插入**

  在 `dashboard_html` 中删除 `.wall-mirror`、`.wall-mirror-*` 规则，并通过以下命令定位和移除创建镜像节点的脚本，而不是只将其设为透明：

  ```bash
  rg -n "wall-mirror|data-mirror|mirror" ds4_server.c
  ```

  只移除装饰镜像的节点创建、同步和最终文本写入。保留 `metric-value-window`、`metric-value-layer` 和方向滚动，因为它们渲染真实的指标值。

- [ ] **Step 2: 用严格栅格替换当前负边距布局**

  将监控样式改为以下结构；具体字体尺寸可微调，但不能改变列、间距或负边距约束：

  ```css
  .monitor-grid {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 400px;
    grid-template-areas: "wall console" "host console";
    gap: 18px 24px;
    align-items: start;
    margin-top: 16px;
  }
  .monitor-console { grid-area: console; margin-left: 0; min-width: 0; }
  .monitor-grid > .num-wall { grid-area: wall; }
  #monitorMetrics {
    display: grid;
    grid-template-columns: minmax(260px, 1.55fr) repeat(5, minmax(92px, 1fr));
    gap: 18px 20px;
    align-items: end;
    overflow: visible;
    margin: 0;
    padding: 12px 0 18px;
  }
  ```

  将 `.vital-decode` 保持为唯一 48–56px 主数；其他 `.vital strong` 最大 28px，运行阶段为正常文本块。不能在指标底部、侧面或玻璃后再次放置同值装饰文字。

- [ ] **Step 3: 让浅色基底覆盖整个视口并降低环境光存在感**

  保留 `.light-field` 作为无文本的灰阶径向光，但让其只承担背景层：

  ```css
  body { min-height: 100vh; background: linear-gradient(145deg, #f7f8fa 0%, #edf0f3 55%, #e4e7eb 100%); }
  .page { width: min(100%, 1400px); min-height: 100vh; margin: 0 auto; padding: 20px 32px 48px; }
  .light-field { opacity: .42; }
  .light-shadow { opacity: .5; }
  ```

  不添加圆角白底容器、深色外框或新的背景图片；玻璃列继续使用现有 `backdrop-filter` 回退。

- [ ] **Step 4: 实现 1024px 与移动断点**

  ```css
  @media (min-width: 981px) and (max-width: 1307px) {
    .monitor-grid { grid-template-columns: minmax(0, 1fr) minmax(360px, 400px); }
    #monitorMetrics {
      grid-template-columns: repeat(3, minmax(0, 1fr));
      grid-template-areas: "decode decode prefill" "decode decode phase" "cache context queue";
    }
  }
  @media (max-width: 980px) {
    .monitor-grid { grid-template-columns: minmax(0, 1fr); grid-template-areas: "wall" "console" "host"; }
    .monitor-console { margin-left: 0; }
  }
  ```

  实现注记：最终实现把指标与主机资源包入 `.monitor-left` 紧凑栈，右侧 `.monitor-console` 保持同级，从而避免跨行右栏参与左侧行高分摊；在 `<=980px` 用 `display:contents` 让三个内容块仍按 `wall → console → host` 的网格顺序进入文档流。

  保留既有 760px 单列指标、12px blur 与 `.call-table-wrap` 横滚约束。

- [ ] **Step 5: 运行 Task 1 断言并确认转绿**

  Run:

  ```bash
  DS4_DASHBOARD_TEST_PORT=18769 ./tests/run_dashboard_ui_test.sh
  ```

  Expected: exit 0；所有既有状态/管理断言与新增信息优先断言通过。

### Task 3: 收紧交互动效与文档说明

**Files:**
- Modify: `ds4_server.c:8214-8224`
- Modify: `README.md:751-759`
- Test: `tests/dashboard_ui_test.js:344-370`

**Interfaces:**
- Consumes: Task 2 的纯布局与实时指标 DOM。
- Produces: 仍具方向数值滚动、行选择和模式切换反馈，但没有与信息竞争的装饰动效；README 与实际页面一致。

- [ ] **Step 1: 增加动效边界测试**

  在 reduced-motion 测试前追加以下检查：

  ```js
  const motionBudget = await page.evaluate(() => {
    const mode = getComputedStyle(document.querySelector('.mode-layout:not([hidden])'));
    const row = getComputedStyle(document.querySelector('#monitorCalls tr[aria-selected="true"]'));
    return { mode: mode.animationDuration, row: row.transitionDuration };
  });
  assert(motionBudget.mode === '0.24s' || motionBudget.mode === '240ms', 'mode transition exceeds the information-first motion budget');
  ```

  若当前测试没有选中行，先使用现有的 `request-select` 操作选择一条调用；不新增模拟数据或改变状态契约。

- [ ] **Step 2: 调整非数值动效时长，不影响数值滚动**

  将 `--motion-fast` 保持 `180ms`，将 `--motion-smooth` 设为 `240ms`。保留 `metric-in-*` / `metric-out-*` 的 `420ms`，因为它们是用户批准的数值方向滚动。保留 stale 时 `setStale()` 暂停 `.light-field` 的逻辑。

- [ ] **Step 3: 把 README 视觉描述改为实际产品语言**

  将 751–759 行替换为如下含义：监控模式是“信息优先的实时控制台”，主读数和次要运行指标使用严格网格，右侧为独立半透明调用/检查器列；没有数字幕墙或主题选择；环境光仅为低对比度背景，窄屏、stale 和 reduced-motion 时静止。

- [ ] **Step 4: 运行局部与文档卫生检查**

  Run:

  ```bash
  python3 -m py_compile tests/dashboard_fixture.py
  git diff --check -- ds4_server.c tests/dashboard_ui_test.js README.md
  DS4_DASHBOARD_TEST_PORT=18769 ./tests/run_dashboard_ui_test.sh
  ```

  Expected: 三条命令均 exit 0。

### Task 4: 真实浏览器验收与回归

**Files:**
- Verify only: `ds4_server.c`, `tests/dashboard_ui_test.js`, `README.md`
- Generate: `output/playwright/dashboard-monitor-desktop.png`
- Generate: `output/playwright/dashboard-management-desktop.png`
- Generate: `output/playwright/dashboard-monitor-mobile.png`
- Generate: `output/playwright/dashboard-management-mobile.png`

**Interfaces:**
- Consumes: Task 1–3 的浏览器断言和 Dashboard fixture。
- Produces: 用户可查看的四张最终截图、控制台检查结果和服务端回归结果。

- [ ] **Step 1: 用 fixture 启动独立的视觉验收服务**

  Run:

  ```bash
  python3 tests/dashboard_fixture.py ds4_server.c 18770
  ```

  Expected: 服务监听 `http://127.0.0.1:18770/`；不加载模型，不占用用户正在查看的 18768 预览端口。

- [ ] **Step 2: 在 1440px 采集监控与管理截图**

  在 Playwright 会话中依次选择监控和管理模式，等待 `#health` 不再是“等待中”，并保存上述两个 1440px 文件。截图时检查：真实指标没有装饰文字重叠、右栏边界完整、玻璃未遮挡表格内容、深色外框不存在。

- [ ] **Step 3: 在 390px 采集两种模式截图**

  保存上述两个 390px 文件。检查页面 `scrollWidth <= innerWidth`，调用表可横滚但页面本身不横滚，所有按钮高度至少 44px。

- [ ] **Step 4: 检查浏览器控制台与完整回归**

  Run:

  ```bash
  DS4_DASHBOARD_TEST_PORT=18769 ./tests/run_dashboard_ui_test.sh
  make ds4_test
  ./ds4_test --server
  git diff --check
  ```

  Expected: 浏览器正常路径无 console error；全量 UI、C server 与 diff 检查均 exit 0。负向 fixture 中故意触发的 403/409/500/503 只在对应断言场景出现，不计为正常路径错误。

## Plan Self-Review

- **Spec coverage:** Task 1 锁定无巨数、无重叠、无裁切和移动边界；Task 2 实现网格和纯灰环境；Task 3 保留但收紧交互与文档；Task 4 用真实截图和全量回归验收。规格中的每项边界均有对应任务。
- **Placeholder scan:** 本计划没有待定实现、泛化测试描述或未定义接口；每项代码步骤给出具体选择器、CSS 或命令。
- **Type consistency:** 全程沿用现有 DOM id、CSS 类、fixture URL 和测试入口；不新增服务端接口或数据类型。
