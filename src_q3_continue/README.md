# Q3 连续滚动版求解

本目录从 `src_q3` 复制而来，作为“16 条事件串成同一天连续滚动状态”的实验版本。

当前目标不是独立事件场景，而是连续滚动：

1. 读取 Q1 初始执行方案。
2. 按 `event_time_min` 顺序处理事件序列。
3. 每次事件求解后，把新方案写回系统状态。
4. 下一条事件基于上一条事件后的真实残余状态继续滚动。
5. 最终输出整天连续演化后的方案链和各时点扰动结果。

当前仍处于改造阶段，默认输出目录已与 `src_q3` 分开，写到 `outputs/q3_continue`。

## 当前入口

PowerShell：

```powershell
$env:Q3_CONTINUE_OUTPUT_DIR="outputs/q3_continue"
python -m src_q3_continue.run_q3
```
