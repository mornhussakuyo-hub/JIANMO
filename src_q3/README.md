# Q3 动态重优化求解说明

本目录从 Q1 定稿代码复制而来，新增 `dynamic_solver.py` 和 `run_q3.py`，用于处理 Q3 的动态扰动事件。

当前这版是**独立事件版**：

1. 读取 Q1 基准结果 `outputs/q1/run_20260425_182112`。
2. 将每条 Q3 事件样例视为一个独立扰动场景。
3. 对每个事件单独切片执行状态，冻结已完成或已出发部分。
4. 对新增、取消、地址变化、时间窗变化等事件构造残余任务。
5. 使用安全兜底路线保证每个事件场景都能稳定给出可行解。

它**不是**“16 条事件串成一天连续滚动状态”的版本；那个版本在 `src_q3_continue`。

## 如何运行

PowerShell：

```powershell
$env:Q3_PARALLEL_WORKERS="1"
python -m src_q3.run_q3
```

Linux：

```bash
Q3_PARALLEL_WORKERS=1 python -m src_q3.run_q3
```

## 多核优化

本版本支持**事件级多核并行**。因为每个事件场景彼此独立，所以可以同时分发到多个进程计算：

```bash
Q3_PARALLEL_WORKERS=4 python -m src_q3.run_q3
```

如果机器核心数较多，可以把 `Q3_PARALLEL_WORKERS` 调到 `4`、`8` 或更高；如果只做调试，设为 `1` 最直观。

## 常用环境变量

### 输入与输出

- `Q3_DATA_DIR`：数据目录，默认 `cleaned_data`
- `Q3_Q1_RUN_DIR`：Q1 基准输出目录，默认 `outputs/q1/run_20260425_182112`
- `Q3_EVENTS_PATH`：Q3 事件文件路径
- `Q3_OUTPUT_DIR`：输出根目录，默认 `outputs/q3`
- `Q3_OUTPUT_TIMESTAMP`：是否创建时间戳子目录，默认 `1`

### 并行与动态调度

- `Q3_PARALLEL_WORKERS`：事件级并行进程数，默认 `1`
- `Q3_VEHICLE_TURNAROUND_MIN`：同一物理车辆两趟之间的最小周转时间，单位分钟，默认 `0`
- `Q3_SINGLE_ROUTE_DEPARTURE_STEP`：单任务安全路线发车时间搜索步长，单位分钟，默认 `15`

### 服务单元划分

Q3 的服务单元切分沿用 Q1 的构造逻辑，因此仍使用以下环境变量：

- `Q1_SERVICE_UNIT_MODE`
- `Q1_SERVICE_UNIT_TARGET_WEIGHT`
- `Q1_SERVICE_UNIT_TARGET_VOLUME`

## 运行后输出在哪

默认输出到 `outputs/q3/run_时间戳/`，常见文件包括：

- `q3_cases.json`：每个事件场景的完整结果
- `q3_case_summary.csv`：事件横向汇总
- `q3_routes.csv`：路线汇总表
- `q3_route_stops.csv`：停靠点明细
- `q3_report.md`：结果报告

如果将 `Q3_OUTPUT_TIMESTAMP=0`，则结果会直接写入 `Q3_OUTPUT_DIR` 指定目录。
