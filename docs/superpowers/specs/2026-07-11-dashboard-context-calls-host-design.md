# DS4 中文看板：Context、调用详情与主机资源设计

## 目标

将 DS4 的运行看板扩展为中文、可切换主题的单页控制台。它需要同时回答四个问题：当前上下文还剩多少、谁在调用服务、调用是否健康、主机内存和 Swap 是否正在承压。

## 范围

本变更包括：

- 三套可切换的中文主题；
- Context 当前用量与下次启动上限设置；
- 仅内存保存的最近调用详情和调用方聚合；
- 整机内存、内存压力、Swap 和 DS4 进程 RSS；
- `/ds4/status` 的新增只读字段，以及必要的本地管理接口。

本变更不保存调用正文、不持久化调用历史、不读取或信任 `X-Forwarded-For`，也不在运行中重建 Context/KV 内存分配。

## 信息架构

看板保持单页、分层阅读：

1. **首屏运行概览**：当前请求、KV、Context、解码速度、队列和主机资源摘要。
2. **调用详情**：当前请求的调用方与协议；最近 200 条内存历史；按直连 IP 聚合的调用次数、失败数、平均耗时和最近活动时间。
3. **资源与设置**：整机内存、Swap、DS4 RSS；Context 下次启动上限和已有的 KV 容量设置。

首屏只放结论和关键数值；请求历史和调用方聚合使用可展开的表格，不堆叠同质卡片。

## 中文主题

所有主题显示同一组数据、操作和无障碍语义，只改变视觉 token。选择写入浏览器 `localStorage`，默认主题为 A；不写入服务端配置。

| 标识 | 名称 | 视觉用途 |
|---|---|---|
| `paper` | 纸面运行报告 | 米白纸面、黑色排版、朱红状态色；默认且适合日常阅读。 |
| `terminal` | 深色控制台 | 深绿黑底、高对比荧光状态；适合远距离运维与故障观察。 |
| `calm` | 从容解释型 | 冷灰蓝基调和完整中文解释；适合偶尔查看或非运维使用者。 |

主题切换控件位于页首，具备明确中文名称和当前选择状态。主题不得改变数值口径或隐藏错误状态。

## Context

### 当前生效状态

状态接口新增 `context` 对象：

```json
{
  "current_tokens": 12472,
  "limit_tokens": 131072,
  "remaining_tokens": 118600,
  "utilization": 0.0951
}
```

它反映当前 session 的真实位置和已分配窗口。看板显示“已用 / 上限”“剩余 token”和利用率，不将 token 伪装成内存字节。

### 下次启动设置

Context 上限在 session 创建时决定，运行中修改不安全。管理操作只保存一个“下次启动 Context”值：

- 接受正整数 token；最小值为 4096；最大值为服务已有命令行 `int` 上限；
- 保存到 `${DS4_CTX_FILE:-$HOME/.ds4/context-tokens}`；
- 原子写入、私有目录/文件权限、结果区分 committed 与 durable；
- `DS4_CTX` 显式环境变量优先于保存值，保存值优先于 profile 默认值；
- 看板同时显示“当前生效”和“下次启动”，保存成功后提示需要重启服务。

管理接口沿用 KV 管理接口的本机安全边界：仅 loopback、仅 JSON POST、要求 `X-DS4-Admin: 1`、不开放 CORS。

## 调用方与调用历史

### 身份来源

调用方只取 TCP peer 地址，不读取 `X-Forwarded-For`、`Forwarded` 或其他可伪造 header。IPv4/IPv6 地址以文本形式记录；Unix socket、无法解析地址或内部测试连接显示为 `local` 或 `unknown`。

### 每条记录

请求进入 worker 队列时分配单调递增 `request_id` 和开始时间；请求完成或失败时补齐结束信息。记录：

- 请求 ID、直连 IP、协议（OpenAI / Responses / Anthropic）、请求类型、stream/tools；
- 开始时间、耗时、prompt/cached/cache-write/output token；
- cache source、finish 原因和截断后的错误摘要；
- 完成、失败或仍在进行的状态。

历史只保存在服务进程内存，固定容量为 200。满时淘汰最旧的已完成记录；当前活动请求不得被淘汰。若 200 条全为活动请求，新的请求不写入历史窗口，但仍分配请求 ID，使其后续完成更新安全地成为无操作；窗口恢复空间后才记录新的请求。服务重启后清空。

### 聚合

按直连 IP 计算：总调用数、失败数、平均耗时、累计 prompt token、累计 cached token、最近活动时间。聚合基于当前环形历史，明确标注“最近 200 条窗口”，不假装是永久审计数据。

## 主机资源

`host` 状态对象包含：

- `memory_total_bytes`、`memory_used_bytes`、`memory_available_bytes`；
- `memory_pressure`：`normal`、`warning`、`critical` 或 `unknown`；
- `swap_total_bytes`、`swap_used_bytes`；
- `process_rss_bytes`（DS4 server 进程 RSS）；
- `sampled_at`。

macOS 使用 Mach/sysctl 的系统统计和 `task_info`；Linux 使用 `/proc/meminfo`、`/proc/pressure/memory`（可用时）及 `/proc/self/status`。不支持的平台返回可用字段，并为缺失值输出 `unknown`/`null`。采样节流为最多每秒一次，状态轮询不会因读取系统指标而阻塞推理 worker。

## API 与错误行为

`/ds4/status` 只新增字段，保持既有字段兼容。调用历史在 `calls` 对象中返回：

```json
{
  "capacity": 200,
  "records": [],
  "callers": [],
  "active_request_id": 42
}
```

Context 保存使用 `POST /ds4/admin/context`，响应具有 KV 管理接口同等的 `ok`、模式、持久化 committed/durable、错误代码和人类可读消息。错误包括 `invalid_context_limit`、`context_persist_failed`、`admin_forbidden` 和 `admin_csrf_required`。

调用记录内的错误文本截断为 160 字节并按 JSON 转义；看板只使用 `textContent`/DOM 节点渲染服务数据，避免 XSS。

## 前端交互

- 主题切换即时生效并写入 localStorage；
- Context 保存按钮不改变当前运行 Context；成功后显示“下次启动：N token，需要重启”；
- 调用表默认显示最近记录，支持仅在前端按 IP、协议和结果过滤；
- 主机资源异常使用主题内已有的错误/告警色，并给出文本原因；
- 网络断开时保留最后快照并标记为“数据已过期”；
- 中文移动端正文不小于 16px，控件至少 44px，表格在窄屏切换为纵向条目。

## 并发与安全

调用历史由专用 mutex 保护；状态序列化复制快照后释放锁，不在 HTTP 线程持锁渲染或枚举系统资源。记录写入不会持有推理 session/KV 锁。Context 管理接口在读取 body 前完成 loopback、CSRF header、Content-Type 和小 body 上限检查。

## 测试与验证

新增/扩展 C 测试覆盖：

- Context 状态、保存校验、文件原子性、环境变量优先级和本机管理安全；
- IPv4/IPv6 调用方记录、环形容量、活动记录保护、完成/失败更新、聚合；
- 主机指标解析和不可用回退；
- `/ds4/status` 的兼容 JSON 字段与敏感 header 不被信任；
- 中文主题 DOM 契约、localStorage 选择、Context 保存提示、调用过滤与过期状态。

浏览器 harness 覆盖三主题切换、中文移动/桌面无横向溢出、调用历史过滤、Context 保存、断线状态及控制台错误。运行 `make ds4_test && ./ds4_test --server`、`tests/run_dashboard_ui_test.sh`、`bash -n start-server.sh`、`make cpu`；模型相关回归继续使用与官方向量匹配的 GGUF。
