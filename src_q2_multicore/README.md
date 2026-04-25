# Q2 多核并行版说明

本目录从 `src_q2` 复制而来，用于在保留 Q2 绿色准入约束求解逻辑的前提下，通过多核并行优化墙钟时间。

当前并行化的重点与 Q1 多核版一致：

1. **初始解候选并行**  
   多个 `Giant Tour / insertion / Split DP` 候选并行构造，再统一择优。
2. **最终局部暴搜并行**  
   `final_polish` 中多个 cluster 的重构候选并行评估，以缩短末端精修耗时。

也就是说，Q2 多核版优化的是**单次求解墙钟时间**，不是外层多开几组不同解。

## 如何运行

PowerShell 快速试跑：

```powershell
$env:Q1_MC_ENABLE="1"
$env:Q1_MC_WORKERS="4"
$env:Q2_GREEN_POLICY_ENABLED="1"
$env:Q2_ALNS_ITERATIONS="2"
$env:Q2_ENABLE_FINAL_BRUTE="0"
python -m src_q2_multicore.run_q2
```

PowerShell 强档示例：

```powershell
$env:Q1_MC_ENABLE="1"
$env:Q1_MC_WORKERS="4"
$env:Q1_MC_INITIAL_WORKERS="4"
$env:Q1_MC_ENABLE_FINAL_POLISH="1"
$env:Q1_MC_FINAL_POLISH_WORKERS="4"
$env:Q1_MC_FINAL_POLISH_PASSES="2"

$env:Q2_ALLOW_VEHICLE_REUSE="1"
$env:Q2_SERVICE_UNIT_MODE="customer_sliced"
$env:Q2_SERVICE_UNIT_TARGET_WEIGHT="750"
$env:Q2_SERVICE_UNIT_TARGET_VOLUME="5.4"
$env:Q2_GREEN_POLICY_ENABLED="1"
$env:Q2_ALNS_ITERATIONS="20"
$env:Q2_ENABLE_FINAL_BRUTE="1"
$env:Q2_BRUTE_MAX_UNITS="13"
$env:Q2_BRUTE_MAX_ROUTES="4"
$env:Q2_BRUTE_MAX_SECONDS="120"

python -m src_q2_multicore.run_q2
```

Linux 示例：

```bash
Q1_MC_ENABLE=1 \
Q1_MC_WORKERS=4 \
Q1_MC_INITIAL_WORKERS=4 \
Q1_MC_ENABLE_FINAL_POLISH=1 \
Q1_MC_FINAL_POLISH_WORKERS=4 \
Q1_MC_FINAL_POLISH_PASSES=2 \
Q2_GREEN_POLICY_ENABLED=1 \
Q2_ALNS_ITERATIONS=20 \
Q2_ENABLE_FINAL_BRUTE=1 \
python -m src_q2_multicore.run_q2
```

## 多核相关环境变量

Q2 多核版沿用与 Q1 多核版相同的并行控制变量：

- `Q1_MC_ENABLE`
- `Q1_MC_WORKERS`
- `Q1_MC_ENABLE_INITIAL`
- `Q1_MC_INITIAL_WORKERS`
- `Q1_MC_ENABLE_FINAL_POLISH`
- `Q1_MC_FINAL_POLISH_WORKERS`
- `Q1_MC_FINAL_POLISH_PASSES`

之所以仍使用 `Q1_MC_*` 命名，是因为 Q2 的底层求解核心本来就复用了 Q1 的启发式模块。

## 其他常用环境变量

### 输入与输出

- `Q2_DATA_DIR`：数据目录，默认 `cleaned_data`
- `Q2_OUTPUT_DIR`：输出根目录，默认 `outputs/q2_multicore`
- `Q2_OUTPUT_TIMESTAMP`：是否自动创建时间戳子目录，默认 `1`
- `Q2_Q1_REFERENCE_JSON`：显式指定 Q1 参考结果 JSON，用于政策增量对比

### 绿色政策

- `Q2_GREEN_POLICY_ENABLED`：是否启用绿色准入政策，默认 `1`
- `Q2_GREEN_POLICY_START_MIN`：禁入开始时间，默认 `480`
- `Q2_GREEN_POLICY_END_MIN`：禁入结束时间，默认 `960`

### Q2 搜索与建模参数

Q2 入口会把 `Q2_*` 参数桥接到底层 Q1 共用求解核心，因此下面这些变量都可以直接用 `Q2_` 前缀设置：

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

## 输出位置

默认输出到 `outputs/q2_multicore/run_时间戳/`，常见文件包括：

- `q2_solution.json`
- `q2_kpi.csv`
- `q2_routes.csv`
- `q2_route_arcs.csv`
- `q2_route_stops.csv`
- `q2_customer_service.csv`
- `q2_green_policy_service.csv`
- `q2_vehicle_usage.csv`
- `q2_policy_compare.csv`
- `q2_report.md`

如果将 `Q2_OUTPUT_TIMESTAMP=0`，则结果会直接写入 `Q2_OUTPUT_DIR`。
