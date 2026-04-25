# Q2 绿色准入约束求解

Q2 代码从 Q1 的 `src` 副本独立演化，不再改动 Q1 定稿目录。

## 本地短测

```powershell
$env:Q2_ALLOW_VEHICLE_REUSE="1"
$env:Q2_SERVICE_UNIT_MODE="customer_sliced"
$env:Q2_SERVICE_UNIT_TARGET_WEIGHT="750"
$env:Q2_SERVICE_UNIT_TARGET_VOLUME="5.4"
$env:Q2_ALNS_ITERATIONS="2"
$env:Q2_ENABLE_FINAL_BRUTE="0"
$env:Q2_GREEN_POLICY_ENABLED="1"

python -m src_q2.run_q2
```

## 服务器正式计算

```bash
export Q2_ALLOW_VEHICLE_REUSE=1
export Q2_SERVICE_UNIT_MODE=customer_sliced
export Q2_SERVICE_UNIT_TARGET_WEIGHT=750
export Q2_SERVICE_UNIT_TARGET_VOLUME=5.4
export Q2_ALNS_ITERATIONS=10
export Q2_ENABLE_FINAL_BRUTE=1
export Q2_BRUTE_MAX_UNITS=13
export Q2_BRUTE_MAX_ROUTES=4
export Q2_BRUTE_MAX_SECONDS=120
export Q2_GREEN_POLICY_ENABLED=1

python -m src_q2.run_q2
```

## 输出

默认输出到 `outputs/q2/run_YYYYMMDD_HHMMSS/`：

- `q2_solution.json`
- `q2_kpi.csv`
- `q2_routes.csv`
- `q2_route_arcs.csv`
- `q2_route_stops.csv`
- `q2_green_policy_service.csv`
- `q2_customer_service.csv`
- `q2_vehicle_usage.csv`
- `q2_policy_compare.csv`
- `q2_report.md`

`q2_policy_compare.csv` 默认会自动选取最新的 `outputs/q1/run_*/q1_solution.json` 作为 Q1 参考；也可以手动指定：

```powershell
$env:Q2_Q1_REFERENCE_JSON="D:\...\outputs\q1\run_xxx\q1_solution.json"
```

```bash
export Q2_Q1_REFERENCE_JSON="/path/to/outputs/q1/run_xxx/q1_solution.json"
```
