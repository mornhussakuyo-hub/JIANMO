# Q1 多核并行版说明

本目录从 `src` 复制而来，用于在**不改变 Q1 求解框架主体**的前提下，通过多核并行降低墙钟时间。

当前并行化的重点是：

1. **初始解候选并行**  
   多个 `Giant Tour / insertion / Split DP` 候选会并行构造，再统一择优。
2. **最终局部暴搜并行**  
   `final_polish` 中多个 cluster 重构候选会并行评估，以缩短末端精修耗时。

核心目标不是换算法，而是让原有启发式在相同等待时间下完成更多有效搜索。

## 如何运行

PowerShell 快速试跑：

```powershell
$env:Q1_MC_ENABLE="1"
$env:Q1_MC_WORKERS="4"
$env:Q1_ALNS_ITERATIONS="2"
$env:Q1_ENABLE_FINAL_BRUTE="0"
python -m src_q1_multicore.run_q1
```

PowerShell 强档示例：

```powershell
$env:Q1_MC_ENABLE="1"
$env:Q1_MC_WORKERS="4"
$env:Q1_MC_INITIAL_WORKERS="4"
$env:Q1_MC_ENABLE_FINAL_POLISH="1"
$env:Q1_MC_FINAL_POLISH_WORKERS="4"
$env:Q1_MC_FINAL_POLISH_PASSES="2"

$env:Q1_ALLOW_VEHICLE_REUSE="1"
$env:Q1_SERVICE_UNIT_MODE="customer_sliced"
$env:Q1_SERVICE_UNIT_TARGET_WEIGHT="750"
$env:Q1_SERVICE_UNIT_TARGET_VOLUME="5.4"
$env:Q1_ALNS_ITERATIONS="50"
$env:Q1_ENABLE_FINAL_BRUTE="1"
$env:Q1_BRUTE_MAX_UNITS="14"
$env:Q1_BRUTE_MAX_ROUTES="4"
$env:Q1_BRUTE_MAX_SECONDS="120"

python -m src_q1_multicore.run_q1
```

Linux 示例：

```bash
Q1_MC_ENABLE=1 \
Q1_MC_WORKERS=4 \
Q1_MC_INITIAL_WORKERS=4 \
Q1_MC_ENABLE_FINAL_POLISH=1 \
Q1_MC_FINAL_POLISH_WORKERS=4 \
Q1_MC_FINAL_POLISH_PASSES=2 \
Q1_ALNS_ITERATIONS=50 \
Q1_ENABLE_FINAL_BRUTE=1 \
python -m src_q1_multicore.run_q1
```

## 多核相关环境变量

- `Q1_MC_ENABLE`：总开关，默认 `1`
- `Q1_MC_WORKERS`：默认 worker 数，默认 `4`
- `Q1_MC_ENABLE_INITIAL`：是否启用初始解候选并行，默认继承 `Q1_MC_ENABLE`
- `Q1_MC_INITIAL_WORKERS`：初始解候选并行 worker 数，默认继承 `Q1_MC_WORKERS`
- `Q1_MC_ENABLE_FINAL_POLISH`：是否启用最终暴搜并行，默认继承 `Q1_MC_ENABLE`
- `Q1_MC_FINAL_POLISH_WORKERS`：最终暴搜并行 worker 数，默认继承 `Q1_MC_WORKERS`
- `Q1_MC_FINAL_POLISH_PASSES`：并行 final polish 最多迭代轮数，默认 `2`

## 其他常用环境变量

### 输入与输出

- `Q1_DATA_DIR`：数据目录，默认 `cleaned_data`
- `Q1_OUTPUT_DIR`：输出根目录，默认 `outputs/q1_multicore`
- `Q1_OUTPUT_TIMESTAMP`：是否自动创建时间戳子目录，默认 `1`

### 服务单元与车辆复用

- `Q1_SERVICE_UNIT_MODE`：服务单元划分模式，默认 `customer_sliced`
- `Q1_SERVICE_UNIT_TARGET_WEIGHT`：服务单元目标重量，默认 `750`
- `Q1_SERVICE_UNIT_TARGET_VOLUME`：服务单元目标体积，默认 `5.4`
- `Q1_SKIP_INSERTION_WHEN_UNITS_GT`：当服务单元数超过阈值时跳过旧插入法，默认 `300`
- `Q1_ALLOW_VEHICLE_REUSE`：是否允许真实车辆复用，默认 `1`
- `Q1_VEHICLE_TURNAROUND_MIN`：同一车辆两趟之间的最小周转时间，单位分钟，默认 `0`

### ALNS 搜索

- `Q1_ALNS_ITERATIONS`
- `Q1_ALNS_DESTROY_MIN_RATIO`
- `Q1_ALNS_DESTROY_MAX_RATIO`
- `Q1_ALNS_MAX_REPAIR_ROUTES`
- `Q1_ALNS_MAX_POSITION_NEIGHBORS`
- `Q1_ALNS_ROUTE_ELIMINATION_PERIOD`
- `Q1_ALNS_ROUTE_ELIMINATION_CANDIDATES`
- `Q1_ALNS_ENABLE_RELATED_ROUTE_REMOVAL`
- `Q1_ALNS_RANDOM_SEED`
- `Q1_POST_ROUTE_ELIMINATION_PASSES`
- `Q1_POST_2OPT_MAX_ROUTE_SIZE`
- `Q1_POST_2OPT_PASSES`

### 最终局部暴搜

- `Q1_ENABLE_FINAL_BRUTE`
- `Q1_BRUTE_MAX_UNITS`
- `Q1_BRUTE_MAX_ROUTES`
- `Q1_BRUTE_MAX_SECONDS`
- `Q1_BRUTE_MAX_CLUSTERS`
- `Q1_BRUTE_RANDOM_ORDERS`
- `Q1_BRUTE_PERMUTE_UNITS`
- `Q1_BRUTE_RANDOM_SEED`

## 输出位置

默认输出到 `outputs/q1_multicore/run_时间戳/`，常见文件包括：

- `q1_solution.json`
- `q1_kpi.csv`
- `q1_routes.csv`
- `q1_route_arcs.csv`
- `q1_route_stops.csv`
- `q1_customer_service.csv`
- `q1_vehicle_usage.csv`
- `q1_report.md`

如果将 `Q1_OUTPUT_TIMESTAMP=0`，则结果会直接写入 `Q1_OUTPUT_DIR`。
