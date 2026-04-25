from __future__ import annotations

from collections.abc import Sequence

from .model import Route, RouteEvaluation, ServiceUnit, SolutionMetrics, VehicleInstance


def assign_route_ids(routes: Sequence[Route], prefix: str = "R") -> None:
    """给没有 route_id 或 route_id 冲突的路线补稳定唯一编号。"""

    seen: set[str] = set()
    next_index = 1
    for route in routes:
        if route.route_id and route.route_id not in seen:
            seen.add(route.route_id)
            continue

        while True:
            candidate = f"{prefix}{next_index:04d}"
            next_index += 1
            if candidate not in seen:
                route.route_id = candidate
                seen.add(candidate)
                break


def route_key(route: Route, index: int | None = None) -> str:
    """路线评价字典的主键。兼容旧路线缺少 route_id 的情况。"""

    if route.route_id:
        return route.route_id
    if index is None:
        return route.vehicle_id
    return f"{route.vehicle_id}#{index:04d}"


def evaluation_for(
    route_evaluations: dict[str, RouteEvaluation],
    route: Route,
    index: int | None = None,
) -> RouteEvaluation | None:
    """优先按 route_id 取评价，兼容旧的 vehicle_id 键。"""

    return route_evaluations.get(route_key(route, index)) or route_evaluations.get(route.vehicle_id)


def build_solution_metrics(
    routes: Sequence[Route],
    route_evaluations: dict[str, RouteEvaluation],
    unassigned_units: Sequence[ServiceUnit],
    vehicles_by_id: dict[str, VehicleInstance],
) -> SolutionMetrics:
    """
    汇总解指标。

    车辆允许复用后，固定启动成本按唯一车辆计一次；
    能耗、碳排、等待、迟到仍按每条路线累计。
    """

    metrics = SolutionMetrics()
    metrics.used_vehicle_count = len({route.vehicle_id for route in routes})
    metrics.unassigned_unit_count = len(unassigned_units)

    used_vehicle_ids: set[str] = set()
    for route in routes:
        used_vehicle_ids.add(route.vehicle_id)
        evaluation = evaluation_for(route_evaluations, route)
        if evaluation is None:
            continue

        metrics.total_energy_cost += evaluation.cost.energy_cost
        metrics.total_carbon_cost += evaluation.cost.carbon_cost
        metrics.total_waiting_cost += evaluation.cost.waiting_cost
        metrics.total_late_cost += evaluation.cost.late_cost
        metrics.total_distance_km += sum(leg.distance_km for leg in evaluation.leg_records)

    startup_cost = 0.0
    for vehicle_id in used_vehicle_ids:
        vehicle = vehicles_by_id.get(vehicle_id)
        if vehicle is not None:
            startup_cost += vehicle.vehicle_type.startup_cost

    metrics.total_cost = (
        startup_cost
        + metrics.total_energy_cost
        + metrics.total_carbon_cost
        + metrics.total_waiting_cost
        + metrics.total_late_cost
    )
    return metrics
