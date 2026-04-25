from __future__ import annotations

from collections import Counter
from pathlib import Path

from .log_utils import log
from .solver import Q1Solver


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    data_dir = repo_root / "cleaned_data"

    solution = Q1Solver(data_dir=data_dir).solve()

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
    log(f"使用车型分布: {dict(Counter(route.vehicle_type_id for route in solution.routes))}", indent=1)

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
