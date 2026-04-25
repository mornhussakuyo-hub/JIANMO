from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from .model import Route, RouteEvaluation, Solution
from .route_evaluator import RouteEvaluator
from .solution_utils import build_solution_metrics, evaluation_for


class SolutionValidator:
    """Q2 最终解校验器。

    它只做校验，不修改 solution。返回的 dict 可以直接写入 report。
    """

    def __init__(
        self,
        route_evaluator: RouteEvaluator,
        allow_vehicle_reuse: bool = True,
        vehicle_turnaround_min: float = 0.0,
        tolerance: float = 1e-5,
    ) -> None:
        self.route_evaluator = route_evaluator
        self.allow_vehicle_reuse = allow_vehicle_reuse
        self.vehicle_turnaround_min = vehicle_turnaround_min
        self.tolerance = tolerance

    def validate(self, solution: Solution) -> dict[str, Any]:
        errors: list[str] = []
        warnings: list[str] = []

        served_unit_ids = [
            unit_id
            for route in solution.routes
            for stop in route.stops
            for unit_id in stop.service_unit_ids
        ]
        served_counter = Counter(served_unit_ids)
        all_unit_ids = set(self.route_evaluator.service_units)
        served_set = set(served_unit_ids)
        unassigned_ids = {unit.unit_id for unit in solution.unassigned_units}

        duplicate_unit_ids = sorted(unit_id for unit_id, count in served_counter.items() if count > 1)
        missing_unit_ids = sorted(all_unit_ids - served_set - unassigned_ids)
        unknown_served_unit_ids = sorted(served_set - all_unit_ids)
        served_and_unassigned = sorted(served_set & unassigned_ids)

        if duplicate_unit_ids:
            errors.append(f"ServiceUnit 重复服务: {duplicate_unit_ids[:20]}")
        if missing_unit_ids:
            errors.append(f"ServiceUnit 既未服务也未列入 unassigned: {missing_unit_ids[:20]}")
        if unknown_served_unit_ids:
            errors.append(f"路线中出现未知 ServiceUnit: {unknown_served_unit_ids[:20]}")
        if served_and_unassigned:
            errors.append(f"ServiceUnit 同时出现在已服务和未分配列表: {served_and_unassigned[:20]}")

        for route_index, route in enumerate(solution.routes, start=1):
            self._validate_route_shape(route, route_index, errors, warnings)
            evaluation = evaluation_for(solution.route_evaluations, route, route_index)
            if evaluation is None:
                warnings.append(f"路线 {route.route_id or route_index} 缺少缓存评价，已临时重算")
                evaluation = self.route_evaluator.evaluate(route)
            self._validate_route_evaluation(route, route_index, evaluation, errors)

        self._validate_vehicle_usage(solution, errors)
        self._validate_customer_conservation(solution, errors, warnings)
        self._validate_metrics(solution, errors, warnings)

        return {
            "ok": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "served_unit_count": len(served_unit_ids),
            "unique_served_unit_count": len(served_set),
            "all_unit_count": len(all_unit_ids),
            "unassigned_unit_count": len(solution.unassigned_units),
            "duplicate_unit_ids": duplicate_unit_ids,
            "missing_unit_ids": missing_unit_ids,
            "unknown_served_unit_ids": unknown_served_unit_ids,
            "served_and_unassigned_unit_ids": served_and_unassigned,
        }

    def _validate_route_shape(
        self,
        route: Route,
        route_index: int,
        errors: list[str],
        warnings: list[str],
    ) -> None:
        label = route.route_id or f"#{route_index}"
        if not route.vehicle_id:
            errors.append(f"路线 {label} 缺少 vehicle_id")
        elif route.vehicle_id not in self.route_evaluator.vehicles:
            errors.append(f"路线 {label} 使用未知车辆: {route.vehicle_id}")
        else:
            vehicle = self.route_evaluator.vehicles[route.vehicle_id]
            if route.vehicle_type_id != vehicle.vehicle_type.type_id:
                errors.append(
                    f"路线 {label} vehicle_type_id 不一致: "
                    f"route={route.vehicle_type_id}, vehicle={vehicle.vehicle_type.type_id}"
                )

        if route.departure_min < 480:
            errors.append(f"路线 {label} 发车早于 08:00: departure_min={route.departure_min}")

        for stop_index, stop in enumerate(route.stops, start=1):
            if stop.customer_id not in self.route_evaluator.customers:
                errors.append(f"路线 {label} 第 {stop_index} 站未知客户: {stop.customer_id}")
            if not stop.service_unit_ids:
                errors.append(f"路线 {label} 第 {stop_index} 站没有 service_unit_ids")
            if stop.delivered_weight < -self.tolerance:
                errors.append(f"路线 {label} 第 {stop_index} 站配送重量为负")
            if stop.delivered_volume < -self.tolerance:
                errors.append(f"路线 {label} 第 {stop_index} 站配送体积为负")

            expected_weight = 0.0
            expected_volume = 0.0
            for unit_id in stop.service_unit_ids:
                unit = self.route_evaluator.service_units.get(unit_id)
                if unit is None:
                    continue
                if unit.customer_id != stop.customer_id:
                    errors.append(
                        f"路线 {label} 第 {stop_index} 站客户与 ServiceUnit 不一致: "
                        f"stop={stop.customer_id}, unit={unit.unit_id}, unit_customer={unit.customer_id}"
                    )
                expected_weight += unit.weight
                expected_volume += unit.volume

            if abs(stop.delivered_weight - expected_weight) > self.tolerance:
                errors.append(
                    f"路线 {label} 第 {stop_index} 站重量不守恒: "
                    f"stop={stop.delivered_weight:.6f}, units={expected_weight:.6f}"
                )
            if abs(stop.delivered_volume - expected_volume) > self.tolerance:
                errors.append(
                    f"路线 {label} 第 {stop_index} 站体积不守恒: "
                    f"stop={stop.delivered_volume:.6f}, units={expected_volume:.6f}"
                )

    def _validate_route_evaluation(
        self,
        route: Route,
        route_index: int,
        evaluation: RouteEvaluation,
        errors: list[str],
    ) -> None:
        label = route.route_id or f"#{route_index}"
        if not evaluation.feasible:
            errors.append(f"路线 {label} RouteEvaluator 判定不可行: {evaluation.violations[:10]}")
        if evaluation.return_to_depot_min is None:
            errors.append(f"路线 {label} 缺少返仓时刻")

        if route.vehicle_id in self.route_evaluator.vehicles:
            vehicle = self.route_evaluator.vehicles[route.vehicle_id]
            total_weight = sum(stop.delivered_weight for stop in route.stops)
            total_volume = sum(stop.delivered_volume for stop in route.stops)
            if total_weight > vehicle.vehicle_type.max_weight + self.tolerance:
                errors.append(
                    f"路线 {label} 重量超载: {total_weight:.6f} > {vehicle.vehicle_type.max_weight:.6f}"
                )
            if total_volume > vehicle.vehicle_type.max_volume + self.tolerance:
                errors.append(
                    f"路线 {label} 体积超载: {total_volume:.6f} > {vehicle.vehicle_type.max_volume:.6f}"
                )

    def _validate_vehicle_usage(self, solution: Solution, errors: list[str]) -> None:
        grouped: dict[str, list[tuple[str, float, float]]] = defaultdict(list)
        for route_index, route in enumerate(solution.routes, start=1):
            evaluation = evaluation_for(solution.route_evaluations, route, route_index)
            if evaluation is None:
                evaluation = self.route_evaluator.evaluate(route)
            if evaluation.return_to_depot_min is None:
                continue
            grouped[route.vehicle_id].append(
                (
                    route.route_id or f"#{route_index}",
                    float(route.departure_min),
                    float(evaluation.return_to_depot_min),
                )
            )

        if not self.allow_vehicle_reuse:
            repeated = sorted(vehicle_id for vehicle_id, schedules in grouped.items() if len(schedules) > 1)
            if repeated:
                errors.append(f"不允许车辆复用时，以下车辆被多条路线使用: {repeated[:20]}")
            return

        for vehicle_id, schedules in grouped.items():
            schedules.sort(key=lambda item: item[1])
            for left, right in zip(schedules, schedules[1:]):
                left_label, left_start, left_end = left
                right_label, right_start, right_end = right
                if left_start < right_end + self.vehicle_turnaround_min and left_end + self.vehicle_turnaround_min > right_start:
                    errors.append(
                        f"车辆 {vehicle_id} 路线时间重叠: "
                        f"{left_label}[{left_start:.2f},{left_end:.2f}] 与 "
                        f"{right_label}[{right_start:.2f},{right_end:.2f}]"
                    )

    def _validate_customer_conservation(
        self,
        solution: Solution,
        errors: list[str],
        warnings: list[str],
    ) -> None:
        delivered_weight: dict[int, float] = defaultdict(float)
        delivered_volume: dict[int, float] = defaultdict(float)
        unassigned_weight: dict[int, float] = defaultdict(float)
        unassigned_volume: dict[int, float] = defaultdict(float)

        for route in solution.routes:
            for stop in route.stops:
                delivered_weight[stop.customer_id] += stop.delivered_weight
                delivered_volume[stop.customer_id] += stop.delivered_volume
        for unit in solution.unassigned_units:
            unassigned_weight[unit.customer_id] += unit.weight
            unassigned_volume[unit.customer_id] += unit.volume

        for customer_id, customer in self.route_evaluator.customers.items():
            total_weight = delivered_weight[customer_id] + unassigned_weight[customer_id]
            total_volume = delivered_volume[customer_id] + unassigned_volume[customer_id]
            if abs(total_weight - customer.demand_weight) > 1e-4:
                errors.append(
                    f"客户 {customer_id} 重量不守恒: served+unassigned={total_weight:.6f}, "
                    f"demand={customer.demand_weight:.6f}"
                )
            if abs(total_volume - customer.demand_volume) > 1e-4:
                errors.append(
                    f"客户 {customer_id} 体积不守恒: served+unassigned={total_volume:.6f}, "
                    f"demand={customer.demand_volume:.6f}"
                )
            if unassigned_weight[customer_id] > self.tolerance or unassigned_volume[customer_id] > self.tolerance:
                warnings.append(
                    f"客户 {customer_id} 仍有未分配需求: "
                    f"weight={unassigned_weight[customer_id]:.6f}, volume={unassigned_volume[customer_id]:.6f}"
                )

    def _validate_metrics(
        self,
        solution: Solution,
        errors: list[str],
        warnings: list[str],
    ) -> None:
        recalculated = build_solution_metrics(
            routes=solution.routes,
            route_evaluations=solution.route_evaluations,
            unassigned_units=solution.unassigned_units,
            vehicles_by_id=self.route_evaluator.vehicles,
        )
        checks = [
            ("total_cost", solution.metrics.total_cost, recalculated.total_cost),
            ("total_distance_km", solution.metrics.total_distance_km, recalculated.total_distance_km),
            ("total_energy_cost", solution.metrics.total_energy_cost, recalculated.total_energy_cost),
            ("total_carbon_cost", solution.metrics.total_carbon_cost, recalculated.total_carbon_cost),
            ("total_waiting_cost", solution.metrics.total_waiting_cost, recalculated.total_waiting_cost),
            ("total_late_cost", solution.metrics.total_late_cost, recalculated.total_late_cost),
        ]
        for name, old, new in checks:
            if abs(old - new) > 1e-4:
                warnings.append(f"solution.metrics.{name} 与重算值略有差异: {old:.6f} vs {new:.6f}")
        if solution.metrics.used_vehicle_count != recalculated.used_vehicle_count:
            warnings.append(
                f"used_vehicle_count 与重算值不同: "
                f"{solution.metrics.used_vehicle_count} vs {recalculated.used_vehicle_count}"
            )
        if solution.metrics.unassigned_unit_count != recalculated.unassigned_unit_count:
            warnings.append(
                f"unassigned_unit_count 与重算值不同: "
                f"{solution.metrics.unassigned_unit_count} vs {recalculated.unassigned_unit_count}"
            )
