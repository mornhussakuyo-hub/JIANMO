from __future__ import annotations

import os
from collections import Counter
from datetime import datetime
from pathlib import Path

from .log_utils import log
from .reporting import Q1ReportBuilder
from .solver import Q1Solver


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    data_dir = Path(os.environ.get("Q1_DATA_DIR", "") or (repo_root / "cleaned_data"))

    result = Q1Solver(data_dir=data_dir).solve_with_context()
    solution = result.solution

    output_root = Path(os.environ.get("Q1_OUTPUT_DIR", "") or (repo_root / "outputs" / "q1"))
    if os.environ.get("Q1_OUTPUT_TIMESTAMP", "1") != "0":
        output_dir = output_root / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    else:
        output_dir = output_root

    report_builder = Q1ReportBuilder(route_evaluator=result.route_evaluator)
    output_paths = report_builder.write_all(solution, output_dir)

    log("========== 最终结果摘要 ==========")
    log(f"路线数: {len(solution.routes)}", indent=1)
    log(f"未分配 ServiceUnit: {len(solution.unassigned_units)}", indent=1)
    log(f"总成本: {solution.metrics.total_cost:.2f}", indent=1)
    log(f"总距离: {solution.metrics.total_distance_km:.2f} km", indent=1)
    log(f"能耗成本: {solution.metrics.total_energy_cost:.2f}", indent=1)
    log(f"碳成本: {solution.metrics.total_carbon_cost:.2f}", indent=1)
    log(f"等待成本: {solution.metrics.total_waiting_cost:.2f}", indent=1)
    log(f"迟到成本: {solution.metrics.total_late_cost:.2f}", indent=1)
    log(f"使用车辆数: {solution.metrics.used_vehicle_count}", indent=1)

    used_vehicle_type_by_id = {}
    for route in solution.routes:
        used_vehicle_type_by_id.setdefault(route.vehicle_id, route.vehicle_type_id)
    log(f"路线车型分布: {dict(Counter(route.vehicle_type_id for route in solution.routes))}", indent=1)
    log(f"使用车型分布: {dict(Counter(used_vehicle_type_by_id.values()))}", indent=1)
    log(f"正式结果输出目录: {output_dir}", indent=1)
    for name, path in output_paths.items():
        log(f"{name}: {path}", indent=2)

    if solution.unassigned_units:
        log("未分配任务列表:", indent=1)
        for unit in solution.unassigned_units:
            log(
                f"{unit.unit_id}: customer={unit.customer_id}, "
                f"weight={unit.weight:.3f}, volume={unit.volume:.3f}",
                indent=2,
            )


if __name__ == "__main__":
    main()
