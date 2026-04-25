# Q1 求解器说明

本目录对应题目 `Q1` 的主求解代码，当前实现采用“ServiceUnit 压缩 + 多种 Giant Tour + Split DP + ALNS + 车辆真实复用排班”的启发式框架。

## 原有复现命令

直接在终端执行如下命令：

```shell
$env:Q1_ALLOW_VEHICLE_REUSE='1'
$env:Q1_SERVICE_UNIT_MODE='customer_sliced'
$env:Q1_SERVICE_UNIT_TARGET_WEIGHT='750'
$env:Q1_SERVICE_UNIT_TARGET_VOLUME='5.4'
$env:Q1_ALNS_ITERATIONS='2'
$env:Q1_ENABLE_FINAL_BRUTE='0'
python -m src.run_q1
```
或

```shell
$env:Q1_ALLOW_VEHICLE_REUSE='1'
$env:Q1_SERVICE_UNIT_MODE='customer_sliced'
$env:Q1_SERVICE_UNIT_TARGET_WEIGHT='750'
$env:Q1_SERVICE_UNIT_TARGET_VOLUME='5.4'
$env:Q1_ALNS_ITERATIONS='50'
$env:Q1_ENABLE_FINAL_BRUTE='1'

$env:Q1_BRUTE_MAX_UNITS="14"
$env:Q1_BRUTE_MAX_ROUTES="4"
$env:Q1_BRUTE_MAX_SECONDS="120"
python -m src.run_q1
```

## 如何运行

PowerShell 快速试跑：

```powershell
$env:Q1_ALNS_ITERATIONS="2"
$env:Q1_ENABLE_FINAL_BRUTE="0"
python -m src.run_q1
```

Linux 快速试跑：

```bash
Q1_ALNS_ITERATIONS=2 Q1_ENABLE_FINAL_BRUTE=0 python -m src.run_q1
```

服务器强档示例：

```bash
Q1_ALLOW_VEHICLE_REUSE=1 \
Q1_SERVICE_UNIT_MODE=customer_sliced \
Q1_SERVICE_UNIT_TARGET_WEIGHT=750 \
Q1_SERVICE_UNIT_TARGET_VOLUME=5.4 \
Q1_ALNS_ITERATIONS=50 \
Q1_ENABLE_FINAL_BRUTE=1 \
Q1_BRUTE_MAX_UNITS=14 \
Q1_BRUTE_MAX_ROUTES=4 \
Q1_BRUTE_MAX_SECONDS=120 \
python -m src.run_q1
```

## 常用环境变量

### 输入与输出

- `Q1_DATA_DIR`：数据目录，默认 `cleaned_data`
- `Q1_OUTPUT_DIR`：输出根目录，默认 `outputs/q1`
- `Q1_OUTPUT_TIMESTAMP`：是否自动创建时间戳子目录，默认 `1`

### 服务单元与车辆复用

- `Q1_SERVICE_UNIT_MODE`：服务单元划分模式，默认 `customer_sliced`
- `Q1_SERVICE_UNIT_TARGET_WEIGHT`：服务单元目标重量，默认 `750`
- `Q1_SERVICE_UNIT_TARGET_VOLUME`：服务单元目标体积，默认 `5.4`
- `Q1_SKIP_INSERTION_WHEN_UNITS_GT`：当服务单元数超过阈值时跳过旧插入法，默认 `300`
- `Q1_ALLOW_VEHICLE_REUSE`：是否允许真实车辆复用，默认 `1`
- `Q1_VEHICLE_TURNAROUND_MIN`：同一车辆两趟之间的最小周转时间，单位分钟，默认 `0`

### ALNS 搜索

- `Q1_ALNS_ITERATIONS`：ALNS 迭代轮数
- `Q1_ALNS_DESTROY_MIN_RATIO`：最小破坏比例
- `Q1_ALNS_DESTROY_MAX_RATIO`：最大破坏比例
- `Q1_ALNS_MAX_REPAIR_ROUTES`：修复阶段最多尝试的路线数
- `Q1_ALNS_MAX_POSITION_NEIGHBORS`：插入时最多考虑的邻近位置数
- `Q1_ALNS_ROUTE_ELIMINATION_PERIOD`：路线消除触发周期
- `Q1_ALNS_ROUTE_ELIMINATION_CANDIDATES`：每次路线消除考虑的候选路线数
- `Q1_ALNS_ENABLE_RELATED_ROUTE_REMOVAL`：是否启用相关路线破坏算子，默认 `0`
- `Q1_ALNS_RANDOM_SEED`：ALNS 随机种子
- `Q1_POST_ROUTE_ELIMINATION_PASSES`：ALNS 后处理的路线消除轮数
- `Q1_POST_2OPT_MAX_ROUTE_SIZE`：进入 2-opt 的最大路线规模
- `Q1_POST_2OPT_PASSES`：路线内 2-opt 轮数

### 最终局部暴搜

- `Q1_ENABLE_FINAL_BRUTE`：是否启用最终局部暴搜，默认 `0`
- `Q1_BRUTE_MAX_UNITS`：单个 cluster 最多处理的服务单元数
- `Q1_BRUTE_MAX_ROUTES`：单次局部暴搜最多联动的路线数
- `Q1_BRUTE_MAX_SECONDS`：最终暴搜最长运行秒数
- `Q1_BRUTE_MAX_CLUSTERS`：最多尝试的 cluster 数
- `Q1_BRUTE_RANDOM_ORDERS`：每个 cluster 额外随机重排次数
- `Q1_BRUTE_PERMUTE_UNITS`：是否对服务单元顺序做排列搜索
- `Q1_BRUTE_RANDOM_SEED`：最终暴搜随机种子

## 运行后输出在哪

默认输出到 `outputs/q1/run_时间戳/`，常见文件包括：

- `q1_solution.json`：完整求解结果
- `q1_summary.json`：汇总指标
- `q1_route_arcs.csv`：路线弧段明细
- `q1_route_stops.csv`：路线停靠点明细
- `q1_vehicle_usage.csv`：车辆使用明细
- `q1_report.md`：结果报告

如果将 `Q1_OUTPUT_TIMESTAMP=0`，则结果会直接写入 `Q1_OUTPUT_DIR` 指定目录。
