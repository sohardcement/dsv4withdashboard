# DS4 Dashboard「流明墙」重构设计

## 背景与目标

现有 Dashboard 已具备完整的运行监控、本地 KV 管理、上下文设置、调用筛选和请求检查能力，但视觉仍由顶部工具栏、等高指标带、左右表格/检查器和多组主题组成。该骨架接近常见管理后台，主题切换只改变皮肤，无法形成 DS4 自己的产品识别。

本次重构采用用户批准的 B1「流明墙」方向：

- 以巨数排版构成页面空间，而不是把指标塞入六张卡片；
- 只保留一条真正有折射对象的玻璃控制柱；
- 使用极慢的黑白灰光场建立空间感，彻底移除黄、蓝、青绿环境光；
- 红绿只表达状态，操作按钮统一使用墨黑；
- 保留现有可靠的状态、管理、安全和可访问性行为，不改变服务端数据契约。

目标优先级：

1. 1440×900 下高效盯盘和请求排障；
2. KV 与上下文管理操作的安全闭环；
3. 形成不依赖圆角卡片、彩色渐变和外部资产的独立视觉识别；
4. 390×844、reduced-motion、离线和低性能设备仍可完整使用。

## 已批准的视觉基线

本设计以可视化对比稿 `B1 · 流明墙` 为准。关键 token 固定如下：

- 墙体基底：`linear-gradient(158deg, #f3f4f6 0%, #e9eaed 52%, #dcdde1 100%)`；
- 动态光团：`radial-gradient(1000px 720px, rgba(255,255,255,.85), transparent 70%)`；
- 静态灰影：`radial-gradient(760px 620px, rgba(148,153,161,.16), transparent 65%)`；
- 墨色：`#1b1e24`；
- 次级文字：`#676c74`；
- 幽灵巨数：`rgba(27,30,36,.08)`，当前主指标最高可到 `.12`；
- 玻璃填充：`rgba(255,255,255,.55)`；
- 玻璃边缘：外缘 `rgba(20,24,30,.08)`，顶部内高光 `rgba(255,255,255,.75)`；
- 玻璃阴影：`0 24px 64px rgba(20,24,30,.12), 0 2px 6px rgba(20,24,30,.06)`；
- 在线/进行中：`#15803d`；
- 失败/危险：`#dc2626`；
- 过期/警告：`#b45309`。

全页不使用彩色环境光。绿色实心主按钮被禁止；`.primary` 使用 `#1b1e24` 底和白字。玻璃柱、输入和按钮只允许 0–2px 技术性圆角，不使用 12–16px 的通用卡片圆角。

## 产品与行为边界

### 必须保留

- `GET /` 与 `GET /dashboard` 继续直接返回 `ds4_server.c` 内嵌页面；
- 每秒轮询 `/ds4/status`，保留 generation 守卫、超时、退避和最后快照；
- `online`、`lastUpdatedAt`、`lastSnapshot` 等现有浏览器测试可见状态；
- 管理与监控两种模式，以及 `ds4-dashboard-mode` 的本地持久化；
- KV 的 `idle/checking/review/applying/saving/success/error` 状态机；
- dry-run、显式确认、修订冲突重检、持久化和焦点恢复；
- 上下文范围校验、403 隔离、持久化结果和脏输入保留；
- 四个调用筛选器、键盘选择、请求检查器和筛选后选择清理；
- 所有服务端字符串只通过 `textContent` 进入 DOM；
- 首次不可用、快照过期和恢复后的状态语义；
- 管理与监控中的主机资源不可用语义；
- 44px 最小交互目标、可见标签、`aria-describedby`、`aria-invalid`、`aria-controls`、`aria-selected` 和 `:focus-visible`。

### 明确改变

- 删除暖纸面、深色终端、冷静蓝绿、液态玻璃四主题选择；
- 删除 `ds4-dashboard-theme` 的读取、应用和指针追光逻辑；旧 localStorage key 被忽略，不主动迁移；
- 单一视觉系统固定为 B1「流明墙」；
- 无有效模式记录时默认进入监控模式；管理模式仍位于模式切换的第一项；
- 监控指标从等宽六格改为错落巨数幕墙；
- 最近调用从传统后台表格外观改为电报流，但保留语义行、筛选和完整检查器；
- 管理模式从左侧导航加内容卡片改为墙面读数加单条玻璃操作柱。

### 非目标

- 不新增趋势图、历史存储、告警、远程管理或身份认证；
- 不改变 `/ds4/status`、KV 管理或上下文管理的 JSON；
- 不引入框架、网络字体、图标包、图片、WebGL 或构建步骤；
- 不修改推理、KV、会话、Metal/CUDA/ROCm 或模型加载路径；
- 不借本次重构顺手调整服务端性能配置和其他未提交改动。

## 共享页面框架

### 顶部桅杆

`.topbar` 变为贴在墙面上的纤细桅杆，而不是悬浮卡片。顺序为：

1. `DS4` 品牌与 `#model`；
2. 管理/监控模式切换；
3. `#connectionState`，包含 `#health` 和 `#updatedAt`。

模式按钮保持原生 `button` 和 `aria-pressed`。激活项用墨黑底白字，非激活项透明。顶部桅杆不使用 backdrop blur。

### 流明背景

页面底层新增 `.light-field`。唯一循环环境动效是光团 60 秒一次的 `translate3d(-8vw,0,0)` 到 `translate3d(8vw,2vh,0)` 往返：

- 只动画 `transform`；
- 不响应指针；
- 不改变布局、滤镜或透明度；
- `prefers-reduced-motion: reduce` 下完全静止；
- 760px 以下完全静止，避免移动端持续合成；
- stale/offline 时暂停在最后位置。

### 巨数分层

每个关键体征由两层组成：

- 可读值：深墨色、稳定尺寸、具备标签和单位，承担真实信息读取；
- 幽灵镜像：更大的同值数字、`aria-hidden="true"`、低对比度、允许在容器内部出血，承担空间构图和玻璃折射。

幽灵镜像不得成为唯一信息来源。幕墙容器必须 `overflow:hidden`，不能制造页面级滚动。

## 监控模式

### 桌面信息架构

1440px 下 `.monitor-grid` 使用约 8:4 的墙面/控制柱比例。

左侧 `.num-wall`：

- `#monitorDecode` 为主读数；
- `#monitorPrefill`、`#monitorCacheHit`、`#monitorContext`、`#monitorQueue` 错落排布；
- `#monitorPhase` 与 `#monitorPhaseMeta` 提供高对比度的活动阶段与服务；
- `#monitorPrefillBar` 与 `#monitorDecodeBar` 保持 3px 发丝进度；
- 每个数字通过 `data-mirror="decode|prefill|cache|context|queue"` 连接一个 `aria-hidden` 镜像；
- 数值方向滚动沿用已有 increase/decrease 语义，镜像只在动画完成后同步最终文本，避免双重滚动。

右侧 `.glass-column`：

1. 活动请求和 `#monitorCallsActive`；
2. `#callFilterCaller`、`#callFilterClient`、`#callFilterApi`、`#callFilterStatus`；
3. `.call-table-wrap` 内的 `#monitorCalls` 电报流；
4. `#requestInspector` 请求详情。

玻璃柱必须覆盖至少一个幽灵巨数的笔画，让 blur 有真实折射对象。调用行用发丝线、等宽时间/请求号和状态词建立节奏，不使用独立白卡。选中行以轻微横移和 2px 墨线表示，状态颜色仍只用于状态文本。

`#monitorHost .host-ruler` 位于墙面底部，作为一条低矮玻璃标尺显示内存压力、物理内存和 DS4 RSS。

### 1440×900 首屏要求

- 顶部桅杆、全部关键体征、至少五条调用、电报选择和完整检查器都能到达；
- 第五条调用与检查器最后一项的底部坐标不得超过 900px；
- 页面不出现纵向为容纳首屏内容而产生的额外空白大区；
- 除玻璃控制柱与主机标尺外，不出现第二张大面积玻璃面；
- 不出现等高指标卡片、白色圆角卡片阵列或彩色背景光。

## 管理模式

管理模式沿用同一 8:4 空间关系，不建立另一套后台皮肤。

左侧墙面：

- `#managementSummary` 展示运行阶段、上下文余量和 KV 使用量；
- 上下文余量为管理页主巨数，KV 当前值为次巨数；
- `#managementRecent` 以三条安静电报摘要呈现；
- `#managementHost .host-ruler` 作为墙底标尺；
- 所有只读数据保持现有 id 和内容语义。

右侧玻璃操作柱：

- `.management-nav` 迁入柱顶，保留五个锚点和现有类名；
- `#kvCapacity` 与 `#contextCapacity` 按语义垂直排列，以发丝线分段，不建立嵌套卡片；
- `#kvReview` 在 KV 分段内原位展开，使用 2px 危险色顶线和极淡危险底色；
- `#adminNotice`、`#contextNotice` 不改为 toast；
- `#kvApplyNow`、`#kvConfirmApply`、`#contextSaveRestart` 的主要操作使用墨黑；
- 操作中禁用、成功、失败和焦点归还逻辑保持不变。

管理页允许纵向滚动，但摘要、目标值、生效时机和主操作必须在进入对应锚点后形成单一闭环。

## 响应式

### 981–1200px

- 两列比例收敛，玻璃柱最小宽度 360px；
- 幕墙数字缩小但不改语义顺序；
- 主机标尺保持三列；
- 调用流只在自身容器内横向滚动。

### 761–980px

- 墙面与玻璃柱改为单列；
- 玻璃柱从 sticky 恢复普通文档流；
- 管理设置仍可在 800px 保持两列，窄于 760px 改为单列；
- `.management-nav` 保留为横向锚点带或隐藏，但 DOM 和链接继续存在。

### 390×844

- 光团停止；
- 玻璃 blur 降至 12px，并提供不支持 blur 时的实色回退；
- 主读数约 40px，幽灵镜像缩小并裁在幕墙内部；
- 所有交互高度至少 44px；
- 页面 `scrollWidth <= innerWidth`；
- 唯一允许横向滚动的是 `.call-table-wrap`；
- 不隐藏管理结果、错误、检查器或关键状态。

## 动效与状态

- 光场：60s 单一循环；
- 指标方向滚动：沿用已有 420ms transform/opacity 动效；
- 模式进入：最多 320ms 的 opacity/translate，一次性播放；
- 调用选中：180ms 横移，不使用弹簧过冲；
- 数值未变、不可用、首次出现或 stale 时不播放方向动效；
- reduced-motion 下全部直接切换，无滚轮、无模式入场、无行横移。

## 可访问性与安全

- 幽灵镜像全部 `aria-hidden="true"`；
- 可读值保留真实标题结构和中文标签；
- 状态同时使用文字，不能只用红绿；
- `.glass-column` 在不支持 `backdrop-filter` 时回退到 `rgba(255,255,255,.88)`；
- 服务、调用方、API、错误等不可信文本必须继续通过 `textContent`；
- 不使用 `innerHTML` 渲染任何快照字段；
- 调用选择继续是可聚焦按钮，保留 `aria-controls="requestInspector"` 与行 `aria-selected`；
- KV 审阅继续接收程序化焦点并在退出后归还触发器；
- stale/offline 禁用写操作但保留最后快照和用户脏输入。

## 实现边界

主要修改：

- `ds4_server.c`：重写 `dashboard_html` 的 CSS 与 DOM，保留并清理现有行为函数；
- `tests/dashboard_ui_test.js`：先增加 B1 视觉、主题删除、默认模式、动效降级和首屏边界断言，再实现；
- `README.md`：将多主题说明替换为单一流明墙与监控默认说明；
- `docs/superpowers/plans/2026-07-22-dashboard-lumen-wall.md`：实施步骤。

不修改 `tests/dashboard_fixture.py`，因为现有 fixture 已覆盖状态快照、管理端点、恶意字符串、离线和主机不可用。

## 测试与验收

自动化至少覆盖：

1. 主题选择器和 `data-theme` 消失；
2. 无有效本地模式时默认监控，合法选择仍持久化；
3. `.light-field`、`.num-wall`、`.glass-column` 和五个镜像节点存在；
4. 镜像与真实指标同步且 `aria-hidden`；
5. 玻璃 blur、背景 token、墨黑主按钮和红绿状态色符合批准 token；
6. 60s 光场与 reduced-motion/移动端静止；
7. 1440×900 第五条调用和检查器最后一项在首屏内；
8. 390×844 无页面溢出，调用流容器承担唯一横滚；
9. 现有 KV、上下文、轮询、筛选、键盘、恶意文本、离线和恢复回归全部通过；
10. `make ds4_test` 与 `./ds4_test --server` 通过。

视觉验收使用真实浏览器截图：桌面监控、桌面管理、390px 监控和 390px 管理。除截图外还需检查浏览器控制台、页面错误、computed style、实际交互和 reduced-motion 模拟。

## 已知风险

- 大面积灰阶渐变在低端显示器或远程桌面可能出现 banding；
- `backdrop-filter` 在低端 GPU 上可能增加合成成本，移动端必须降级；
- 巨数出血容易制造页面横向溢出，所有镜像必须被幕墙容器裁切；
- `dashboard_html` 是 C 字符串，任何引号和反斜杠错误都会同时破坏 C 编译与 fixture 提取；
- 当前工作区已有 `ds4_server.c` 的其他未提交改动，实现必须按 hunk 隔离并保留；
- 重构前浏览器基线已存在“请求检查器最后一项超出 1440×900 首屏”的失败，本次布局必须修复并在最终结果中明确说明。
