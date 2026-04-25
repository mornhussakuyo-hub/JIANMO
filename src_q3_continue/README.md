# Q3 连续滚动版求解说明

本目录从 `src_q3` 复制而来，目标是把 `16` 条事件真正串成同一天的连续滚动状态。

与 `src_q3` 不同，这一版不是“每个事件单独算一次”，而是：

1. 先读取一次 Q1 初始执行方案。
2. 按 `event_time_min` 顺序逐条处理事件。
3. 每次事件求解后，把新的路线、客户、服务单元和车辆状态写回系统。
4. 下一条事件直接接在上一条事件之后继续滚动。
5. 最终得到的是整天连续演化后的方案链。

## 如何运行

PowerShell：

```powershell
$env:Q3_CONTINUE_OUTPUT_DIR="outputs/q3_continue"
python -m src_q3_continue.run_q3
```

Linux：

```bash
Q3_CONTINUE_OUTPUT_DIR=outputs/q3_continue python -m src_q3_continue.run_q3
```

指定随机事件文件的示例：

```bash
Q3_CONTINUE_EVENTS_PATH=cleaned_data/q3_events_reasonable_samples_random_times_from_q1_run_20260425_182112.json \
python -m src_q3_continue.run_q3
```

## 关于多核

连续滚动版当前**没有启用事件级多核并行**。原因是后一个事件必须依赖前一个事件更新后的真实系统状态，不能像 `src_q3` 那样并行拆开算。

如果后续要继续加速，方向会更偏向单次事件内部并行或更快的局部搜索，而不是多事件并行。

## 常用环境变量

### 输入与输出

- `Q3_CONTINUE_DATA_DIR`：连续版数据目录；若不设置，则回退到 `Q3_DATA_DIR`
- `Q3_CONTINUE_Q1_RUN_DIR`：连续版使用的 Q1 基准输出目录；若不设置，则回退到 `Q3_Q1_RUN_DIR`
- `Q3_CONTINUE_EVENTS_PATH`：连续版事件文件；若不设置，则回退到 `Q3_EVENTS_PATH`
- `Q3_CONTINUE_OUTPUT_DIR`：连续版输出根目录；若不设置，则回退到 `Q3_OUTPUT_DIR`，再默认到 `outputs/q3_continue`
- `Q3_CONTINUE_OUTPUT_TIMESTAMP`：是否自动创建时间戳子目录；若不设置，则回退到 `Q3_OUTPUT_TIMESTAMP`

### 动态调度

- `Q3_VEHICLE_TURNAROUND_MIN`：同一物理车辆两趟之间的最小周转时间，单位分钟，默认 `0`
- `Q3_SINGLE_ROUTE_DEPARTURE_STEP`：单任务安全路线发车时间搜索步长，单位分钟，默认 `15`

### 服务单元划分

连续版同样沿用 Q1 的服务单元构造逻辑：

- `Q1_SERVICE_UNIT_MODE`
- `Q1_SERVICE_UNIT_TARGET_WEIGHT`
- `Q1_SERVICE_UNIT_TARGET_VOLUME`

## 运行后输出在哪

默认输出到 `outputs/q3_continue/run_时间戳/`，常见文件包括：

- `q3_cases.json`：按时间顺序滚动后的各事件结果
- `q3_case_summary.csv`：事件汇总表
- `q3_routes.csv`：当前连续版路线汇总
- `q3_route_stops.csv`：停靠点明细
- `q3_report.md`：连续滚动版结果报告

如果将 `Q3_CONTINUE_OUTPUT_TIMESTAMP=0`，则结果会直接写入 `Q3_CONTINUE_OUTPUT_DIR` 指定目录。
