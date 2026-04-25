from __future__ import annotations

from collections import defaultdict
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


def assign_reusable_vehicle_schedules(
    routes: Sequence[Route],
    vehicles_by_id: dict[str, VehicleInstance],
    route_evaluator,
    turnaround_min: float = 0.0,
) -> bool:
    """
    在允许真实车辆复用时，为路线重新分配具体车辆实例。

    返回 False 表示当前路线集合无法排成一张无时间重叠的真实车辆时间表。
    这个状态必须被搜索过程当成硬约束处理，不能静默保留旧 vehicle_id。
    """

    vehicles_by_type: dict[int, list[VehicleInstance]] = defaultdict(list)
    for vehicle in vehicles_by_id.values():
        vehicles_by_type[vehicle.vehicle_type.type_id].append(vehicle)
    for vehicles in vehicles_by_type.values():
        vehicles.sort(key=lambda item: item.vehicle_id)

    schedules: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for route in sorted(routes, key=lambda item: (item.route_id, item.departure_min, item.vehicle_id)):
        route_weight = sum(stop.delivered_weight for stop in route.stops)
        route_volume = sum(stop.delivered_volume for stop in route.stops)
        compatible_vehicles = [
            vehicle
            for vehicles in vehicles_by_type.values()
            for vehicle in vehicles
            if route_weight <= vehicle.vehicle_type.max_weight + 1e-9
            and route_volume <= vehicle.vehicle_type.max_volume + 1e-9
        ]
        if not compatible_vehicles:
            return False

        chosen_vehicle: VehicleInstance | None = None
        chosen_eval: RouteEvaluation | None = None
        chosen_departure_min: int | None = None
        chosen_score: tuple[float, float, float, int, int, str] | None = None
        departure_candidates = departure_candidates_for_route(route, route_evaluator)

        for vehicle in compatible_vehicles:
            for departure_min in departure_candidates:
                candidate_route = Route(
                    vehicle_id=vehicle.vehicle_id,
                    vehicle_type_id=vehicle.vehicle_type.type_id,
                    departure_min=departure_min,
                    stops=route.stops,
                    route_id=route.route_id,
                )
                evaluation = route_evaluator.evaluate(candidate_route)
                if not evaluation.feasible or evaluation.return_to_depot_min is None:
                    continue
                if not _schedule_can_accept(
                    schedules=schedules[vehicle.vehicle_id],
                    start_min=float(departure_min),
                    end_min=evaluation.return_to_depot_min,
                    turnaround_min=turnaround_min,
                ):
                    continue

                is_new_vehicle = not schedules[vehicle.vehicle_id]
                startup_delta = vehicle.vehicle_type.startup_cost if is_new_vehicle else 0.0
                variable_cost = (
                    evaluation.cost.energy_cost
                    + evaluation.cost.carbon_cost
                    + evaluation.cost.waiting_cost
                    + evaluation.cost.late_cost
                )
                latest_finish = max((end for _, end in schedules[vehicle.vehicle_id]), default=0.0)
                score = (
                    variable_cost + startup_delta,
                    evaluation.cost.total_cost,
                    latest_finish,
                    abs(departure_min - route.departure_min),
                    vehicle.vehicle_type.type_id,
                    vehicle.vehicle_id,
                )
                if chosen_score is None or score < chosen_score:
                    chosen_vehicle = vehicle
                    chosen_eval = evaluation
                    chosen_departure_min = departure_min
                    chosen_score = score

        if chosen_vehicle is None or chosen_eval is None or chosen_departure_min is None:
            return False

        route.vehicle_id = chosen_vehicle.vehicle_id
        route.vehicle_type_id = chosen_vehicle.vehicle_type.type_id
        route.departure_min = chosen_departure_min
        schedules[route.vehicle_id].append((float(route.departure_min), chosen_eval.return_to_depot_min))
        schedules[route.vehicle_id].sort()

    return True


def has_vehicle_schedule_conflict(
    routes: Sequence[Route],
    route_evaluations: dict[str, RouteEvaluation],
    route_evaluator,
    allow_vehicle_reuse: bool = True,
    turnaround_min: float = 0.0,
) -> bool:
    """检查同一真实车辆是否被安排了冲突路线。"""

    grouped: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for index, route in enumerate(routes, start=1):
        if route.vehicle_id not in route_evaluator.vehicles:
            return True
        evaluation = evaluation_for(route_evaluations, route, index)
        if evaluation is None:
            evaluation = route_evaluator.evaluate(route)
        if not evaluation.feasible or evaluation.return_to_depot_min is None:
            return True
        grouped[route.vehicle_id].append((float(route.departure_min), evaluation.return_to_depot_min))

    if not allow_vehicle_reuse:
        return any(len(schedules) > 1 for schedules in grouped.values())

    for schedules in grouped.values():
        schedules.sort()
        for left, right in zip(schedules, schedules[1:]):
            left_start, left_end = left
            right_start, right_end = right
            if _time_windows_overlap(left_start, left_end, right_start, right_end, turnaround_min):
                return True
    return False


def _schedule_can_accept(
    schedules: Sequence[tuple[float, float]],
    start_min: float,
    end_min: float,
    turnaround_min: float,
) -> bool:
    return not any(
        _time_windows_overlap(start_min, end_min, existing_start, existing_end, turnaround_min)
        for existing_start, existing_end in schedules
    )


def departure_candidates_for_route(route: Route, route_evaluator) -> list[int]:
    """构造通用发车候选集，供路线重计时和车辆复用排班共用。"""

    candidates: set[int] = {int(route.departure_min)}
    latest_window_end = 1020

    for stop in route.stops:
        customer = route_evaluator.customers[stop.customer_id]
        latest_window_end = max(latest_window_end, customer.time_window.end_min)
        for value in [
            customer.time_window.start_min - 120,
            customer.time_window.start_min - 60,
            customer.time_window.start_min - 30,
            customer.time_window.start_min,
            customer.time_window.end_min - 60,
            customer.time_window.end_min - 30,
            customer.time_window.end_min,
        ]:
            if value >= 480:
                candidates.add(int(value))

    upper = min(24 * 60 - 1, max(1020, latest_window_end + 120))
    for value in [480, 540, 600, 690, 780, 900, 1020, 1050, 1080]:
        if 480 <= value <= upper:
            candidates.add(value)

    for value in range(480, upper + 1, 30):
        candidates.add(value)
    return sorted(candidates)


def _time_windows_overlap(
    left_start: float,
    left_end: float,
    right_start: float,
    right_end: float,
    turnaround_min: float,
) -> bool:
    return left_start < right_end + turnaround_min and left_end + turnaround_min > right_start
