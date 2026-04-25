# Q2 求解器说明

本目录对应题目 `Q2` 的求解代码，在 `Q1` 框架基础上加入绿色准入政策约束与对比分析输出。

## 原有复现命令

直接运行：

```shell
$env:Q2_ALLOW_VEHICLE_REUSE="1"
$env:Q2_SERVICE_UNIT_MODE="customer_sliced"
$env:Q2_SERVICE_UNIT_TARGET_WEIGHT="750"
$env:Q2_SERVICE_UNIT_TARGET_VOLUME="5.4"
$env:Q2_ALNS_ITERATIONS="2"
$env:Q2_ENABLE_FINAL_BRUTE="0"
$env:Q2_GREEN_POLICY_ENABLED="1"

python -m src_q2.run_q2
```

## 如何运行

PowerShell 快速试跑：

```powershell
$env:Q2_GREEN_POLICY_ENABLED="1"
$env:Q2_ALNS_ITERATIONS="2"
$env:Q2_ENABLE_FINAL_BRUTE="0"
python -m src_q2.run_q2
```

Linux 快速试跑：

```bash
Q2_GREEN_POLICY_ENABLED=1 Q2_ALNS_ITERATIONS=2 Q2_ENABLE_FINAL_BRUTE=0 python -m src_q2.run_q2
```

较强搜索示例：

```bash
Q2_ALLOW_VEHICLE_REUSE=1 \
Q2_SERVICE_UNIT_MODE=customer_sliced \
Q2_SERVICE_UNIT_TARGET_WEIGHT=750 \
Q2_SERVICE_UNIT_TARGET_VOLUME=5.4 \
Q2_GREEN_POLICY_ENABLED=1 \
Q2_ALNS_ITERATIONS=20 \
Q2_ENABLE_FINAL_BRUTE=1 \
Q2_BRUTE_MAX_UNITS=13 \
Q2_BRUTE_MAX_ROUTES=4 \
Q2_BRUTE_MAX_SECONDS=120 \
python -m src_q2.run_q2
```

## 常用环境变量

### 输入与输出

- `Q2_DATA_DIR`：数据目录，默认 `cleaned_data`
- `Q2_OUTPUT_DIR`：输出根目录，默认 `outputs/q2`
- `Q2_OUTPUT_TIMESTAMP`：是否自动创建时间戳子目录，默认 `1`
- `Q2_Q1_REFERENCE_JSON`：显式指定 Q1 参考结果 JSON，用于政策增量对比

### 绿色政策

- `Q2_GREEN_POLICY_ENABLED`：是否启用绿色准入政策，默认 `1`
- `Q2_GREEN_POLICY_START_MIN`：禁入开始时间，单位分钟，默认 `480`（08:00）
- `Q2_GREEN_POLICY_END_MIN`：禁入结束时间，单位分钟，默认 `960`（16:00）

### 服务单元、车辆复用与搜索

Q2 入口会把 `Q2_*` 参数自动映射到 Q1 共用求解核心，因此下面这些变量都可以直接用 `Q2_` 前缀设置：

- `Q2_ALLOW_VEHICLE_REUSE`
- `Q2_VEHICLE_TURNAROUND_MIN`
- `Q2_SERVICE_UNIT_MODE`
- `Q2_SERVICE_UNIT_TARGET_WEIGHT`
- `Q2_SERVICE_UNIT_TARGET_VOLUME`
- `Q2_ALNS_ITERATIONS`
- `Q2_ALNS_DESTROY_MIN_RATIO`
- `Q2_ALNS_DESTROY_MAX_RATIO`
- `Q2_ALNS_MAX_REPAIR_ROUTES`
- `Q2_ALNS_MAX_POSITION_NEIGHBORS`
- `Q2_ALNS_ROUTE_ELIMINATION_PERIOD`
- `Q2_ALNS_ROUTE_ELIMINATION_CANDIDATES`
- `Q2_ALNS_ENABLE_RELATED_ROUTE_REMOVAL`
- `Q2_ALNS_RANDOM_SEED`
- `Q2_POST_ROUTE_ELIMINATION_PASSES`
- `Q2_POST_2OPT_MAX_ROUTE_SIZE`
- `Q2_POST_2OPT_PASSES`
- `Q2_ENABLE_FINAL_BRUTE`
- `Q2_BRUTE_MAX_UNITS`
- `Q2_BRUTE_MAX_ROUTES`
- `Q2_BRUTE_MAX_SECONDS`
- `Q2_BRUTE_MAX_CLUSTERS`
- `Q2_BRUTE_RANDOM_ORDERS`
- `Q2_BRUTE_PERMUTE_UNITS`
- `Q2_BRUTE_RANDOM_SEED`

## 运行后输出在哪

默认输出到 `outputs/q2/run_时间戳/`，常见文件包括：

- `q2_solution.json`：完整求解结果
- `q2_summary.json`：汇总指标
- `q2_route_arcs.csv`：路线弧段明细
- `q2_route_stops.csv`：路线停靠点明细
- `q2_vehicle_usage.csv`：车辆使用明细
- `q2_green_policy_summary.csv`：绿色政策统计结果
- `q2_report.md`：结果报告

如果将 `Q2_OUTPUT_TIMESTAMP=0`，则结果会直接写入 `Q2_OUTPUT_DIR` 指定目录。
