from __future__ import annotations

import csv
import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from .log_utils import log
from .reporting import Q2ReportBuilder
from .solver import Q2Solver


def main() -> None:
    _bridge_q2_env_to_q1_algorithm_env()
    repo_root = Path(__file__).resolve().parents[1]
    data_dir = Path(os.environ.get("Q2_DATA_DIR", "") or os.environ.get("Q1_DATA_DIR", "") or (repo_root / "cleaned_data"))

    result = Q2Solver(data_dir=data_dir).solve_with_context()
    solution = result.solution

    output_root = Path(os.environ.get("Q2_OUTPUT_DIR", "") or (repo_root / "outputs" / "q2_multicore"))
    if os.environ.get("Q2_OUTPUT_TIMESTAMP", "1") != "0":
        output_dir = output_root / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    else:
        output_dir = output_root

    report_builder = Q2ReportBuilder(route_evaluator=result.route_evaluator)
    output_paths = report_builder.write_all(solution, output_dir)

    compare_path = _write_policy_compare_if_possible(
        repo_root=repo_root,
        output_dir=output_dir,
        q2_payload=report_builder.build_summary_dict(solution),
    )
    if compare_path is not None:
        output_paths["policy_compare_csv"] = compare_path

    log("========== Q2 最终结果摘要 ==========")
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


def _bridge_q2_env_to_q1_algorithm_env() -> None:
    """
    Q2 复用 Q1 的算法模块；这里允许控制台使用 Q2_* 参数名，
    再映射到底层算法已经支持的 Q1_* 环境变量。
    """

    mappings = {
        "Q2_ALLOW_VEHICLE_REUSE": "Q1_ALLOW_VEHICLE_REUSE",
        "Q2_VEHICLE_TURNAROUND_MIN": "Q1_VEHICLE_TURNAROUND_MIN",
        "Q2_SERVICE_UNIT_MODE": "Q1_SERVICE_UNIT_MODE",
        "Q2_SERVICE_UNIT_TARGET_WEIGHT": "Q1_SERVICE_UNIT_TARGET_WEIGHT",
        "Q2_SERVICE_UNIT_TARGET_VOLUME": "Q1_SERVICE_UNIT_TARGET_VOLUME",
        "Q2_ALNS_ITERATIONS": "Q1_ALNS_ITERATIONS",
        "Q2_ALNS_DESTROY_MIN_RATIO": "Q1_ALNS_DESTROY_MIN_RATIO",
        "Q2_ALNS_DESTROY_MAX_RATIO": "Q1_ALNS_DESTROY_MAX_RATIO",
        "Q2_ALNS_MAX_REPAIR_ROUTES": "Q1_ALNS_MAX_REPAIR_ROUTES",
        "Q2_ALNS_MAX_POSITION_NEIGHBORS": "Q1_ALNS_MAX_POSITION_NEIGHBORS",
        "Q2_ALNS_ROUTE_ELIMINATION_PERIOD": "Q1_ALNS_ROUTE_ELIMINATION_PERIOD",
        "Q2_ALNS_ROUTE_ELIMINATION_CANDIDATES": "Q1_ALNS_ROUTE_ELIMINATION_CANDIDATES",
        "Q2_ALNS_ENABLE_RELATED_ROUTE_REMOVAL": "Q1_ALNS_ENABLE_RELATED_ROUTE_REMOVAL",
        "Q2_ALNS_RANDOM_SEED": "Q1_ALNS_RANDOM_SEED",
        "Q2_POST_ROUTE_ELIMINATION_PASSES": "Q1_POST_ROUTE_ELIMINATION_PASSES",
        "Q2_POST_2OPT_MAX_ROUTE_SIZE": "Q1_POST_2OPT_MAX_ROUTE_SIZE",
        "Q2_POST_2OPT_PASSES": "Q1_POST_2OPT_PASSES",
        "Q2_ENABLE_FINAL_BRUTE": "Q1_ENABLE_FINAL_BRUTE",
        "Q2_BRUTE_MAX_UNITS": "Q1_BRUTE_MAX_UNITS",
        "Q2_BRUTE_MAX_ROUTES": "Q1_BRUTE_MAX_ROUTES",
        "Q2_BRUTE_MAX_SECONDS": "Q1_BRUTE_MAX_SECONDS",
        "Q2_BRUTE_MAX_CLUSTERS": "Q1_BRUTE_MAX_CLUSTERS",
        "Q2_BRUTE_RANDOM_ORDERS": "Q1_BRUTE_RANDOM_ORDERS",
        "Q2_BRUTE_PERMUTE_UNITS": "Q1_BRUTE_PERMUTE_UNITS",
        "Q2_BRUTE_RANDOM_SEED": "Q1_BRUTE_RANDOM_SEED",
    }
    for q2_name, q1_name in mappings.items():
        if q2_name in os.environ:
            os.environ[q1_name] = os.environ[q2_name]


def _write_policy_compare_if_possible(
    repo_root: Path,
    output_dir: Path,
    q2_payload: dict[str, Any],
) -> Path | None:
    q1_json = _find_q1_reference_json(repo_root)
    if q1_json is None:
        log("未找到 Q1 参考 q1_solution.json，跳过政策增量对比表", indent=1)
        return None

    q1_payload = json.loads(q1_json.read_text(encoding="utf-8"))
    q1_kpi = q1_payload.get("kpi", {})
    q2_kpi = q2_payload.get("kpi", {})

    row = {
        "q1_reference_json": str(q1_json),
        "q2_total_cost": q2_kpi.get("total_cost"),
        "q1_total_cost": q1_kpi.get("total_cost"),
        "delta_total_cost": _delta(q2_kpi, q1_kpi, "total_cost"),
        "delta_distance_km": _delta(q2_kpi, q1_kpi, "total_distance_km"),
        "delta_route_count": _delta(q2_kpi, q1_kpi, "route_count"),
        "delta_used_vehicle_count": _delta(q2_kpi, q1_kpi, "used_vehicle_count"),
        "delta_energy_cost": _delta(q2_kpi, q1_kpi, "total_energy_cost"),
        "delta_carbon_cost": _delta(q2_kpi, q1_kpi, "total_carbon_cost"),
        "delta_wait_cost": _delta(q2_kpi, q1_kpi, "total_waiting_cost"),
        "delta_late_cost": _delta(q2_kpi, q1_kpi, "total_late_cost"),
        "delta_late_stop_count": _delta(q2_kpi, q1_kpi, "late_stop_count"),
        "green_violation_count": q2_kpi.get("green_violation_count"),
        "green_fuel_service_count": q2_kpi.get("green_fuel_service_count"),
        "green_new_energy_service_count": q2_kpi.get("green_new_energy_service_count"),
    }

    output_path = output_dir / "q2_policy_compare.csv"
    with output_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    log(f"政策增量对比表已生成，参考 Q1: {q1_json}", indent=1)
    return output_path


def _find_q1_reference_json(repo_root: Path) -> Path | None:
    explicit = os.environ.get("Q2_Q1_REFERENCE_JSON", "")
    if explicit:
        path = Path(explicit)
        return path if path.exists() else None

    q1_root = repo_root / "outputs" / "q1"
    candidates = sorted(q1_root.glob("run_*/q1_solution.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _delta(left: dict[str, Any], right: dict[str, Any], key: str) -> float | None:
    if key not in left or key not in right:
        return None
    try:
        return round(float(left[key]) - float(right[key]), 6)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    main()
