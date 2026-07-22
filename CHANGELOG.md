# Changelog

本文件记录 DwarfStar4 的用户可见变更。

## [0.0.1.0] - 2026-07-17

### Changed

- 分布式推理现在能在本地 prefill 层组之间和等待远端结果时响应取消；中断后的部分状态会被丢弃，并在下一次同步时安全重建。
- Metal 的可取消 prefill 以四层为一组限制中断延迟；CUDA/ROCm 保持单次设备同步，避免正常 prefill 吞吐回退；单 token decode 不做分组。

### Fixed

- 修复 coordinator 在路由失败或 worker 重连时错误关闭、移除新控制连接，以及注册日志可能解引用已释放 worker 的并发问题。
- 修复 pipelined prefill 将取消覆盖成传输错误，以及分布式普通失败后残留 checkpoint 可能暴露旧 logits/KV 的问题。
- 修复取消 pipeline 时将健康 worker 的控制连接一并关闭，导致下一次请求短暂缺少完整 route 的问题。
- 增加控制连接所有权、work/control 连接隔离、重连代际、取消优先级、logits/checkpoint 失效和后端取消策略的回归测试。
