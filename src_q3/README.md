# Q3 动态重优化求解

本目录从 Q1 定稿代码复制而来，新增 `dynamic_solver.py` 和 `run_q3.py`。

第一版采用稳定优先策略：

1. 读取 Q1 定稿输出 `outputs/q1/run_20260425_182112`。
2. 对每条 Q3 事件样例独立切片执行状态。
3. 冻结已完成、已出发或正在服务的服务单元。
4. 对新增、取消、地址变化、时间窗变化事件更新服务单元状态。
5. 将事件新增或变更的任务映射为 Q3 虚拟客户节点，避免污染原客户时间窗。
6. 使用事件后从仓库出发的单任务安全路线作为兜底。
7. 对同一物理车辆做无时间重叠校验，必要时保守换车。

## 直接运行

PowerShell：

```powershell
$env:Q3_PARALLEL_WORKERS="1"
python -m src_q3.run_q3
```

Linux：

```bash
Q3_PARALLEL_WORKERS=1 python -m src_q3.run_q3
```

## 多核运行

Q3 当前按事件样例并行，适合 16 个独立扰动场景：

```bash
Q3_PARALLEL_WORKERS=4 python -m src_q3.run_q3
```

## 常用环境变量

- `Q3_DATA_DIR`：数据目录，默认 `cleaned_data`
- `Q3_Q1_RUN_DIR`：Q1 基准输出目录，默认 `outputs/q1/run_20260425_182112`
- `Q3_EVENTS_PATH`：Q3 事件文件
- `Q3_OUTPUT_DIR`：输出根目录，默认 `outputs/q3`
- `Q3_OUTPUT_TIMESTAMP`：是否创建时间戳子目录，默认 `1`
- `Q3_PARALLEL_WORKERS`：事件级并行进程数，默认 `1`

## 输出文件

- `q3_cases.json`：每个事件场景的完整结果
- `q3_case_summary.csv`：事件横向汇总
- `q3_routes.csv`：Q3 路线表
- `q3_route_stops.csv`：Q3 停靠点表
- `q3_report.md`：简要报告
