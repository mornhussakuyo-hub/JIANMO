from __future__ import annotations

import itertools
import math
import multiprocessing as mp
import os
import random
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .log_utils import log
from .model import Route, RouteEvaluation, RouteStop, ServiceUnit, Solution, SolutionMetrics, VehicleInstance
from .route_evaluator import RouteEvaluator
from .solution_utils import (
    assign_reusable_vehicle_schedules,
    assign_route_ids,
    build_solution_metrics,
    evaluation_for,
    route_key,
)
from .validator import SolutionValidator


@dataclass(slots=True)
class _RouteCandidate:
    route: Route
    evaluation: RouteEvaluation
    variable_cost: float
    total_cost: float


def _final_polish_cluster_worker(
    route_evaluator: RouteEvaluator,
    solution: Solution,
    cluster_indexes: tuple[int, ...],
    config: dict[str, int | float | bool],
) -> Solution | None:
    """最终暴搜单个 cluster 的进程 worker。"""

    polisher = FinalPolisher(route_evaluator=route_evaluator)
    polisher.enabled = True
    polisher.max_units = int(config["max_units"])
    polisher.max_routes = int(config["max_routes"])
    polisher.max_seconds = float(config["max_seconds"])
    polisher.max_clusters = int(config["max_clusters"])
    polisher.random_orders = int(config["random_orders"])
    polisher.permute_units = int(config["permute_units"])
    polisher.allow_vehicle_reuse = bool(config["allow_vehicle_reuse"])
    polisher.turnaround_min = float(config["turnaround_min"])
    polisher.random = random.Random(int(config["random_seed"]) + sum(cluster_indexes))

    validator = SolutionValidator(
        route_evaluator=route_evaluator,
        allow_vehicle_reuse=polisher.allow_vehicle_reuse,
        vehicle_turnaround_min=polisher.turnaround_min,
    )
    return polisher._try_rebuild_cluster(
        solution=solution,
        cluster_indexes=cluster_indexes,
        start_time=time.perf_counter(),
        validator=validator,
    )


class FinalPolisher:
    """ALNS 后的安全型局部暴搜精修。

    设计原则：
    - 不做全局暴搜，只选少数相邻路线构成 cluster；
    - cluster 外的路线保持不变；
    - cluster 内 ServiceUnit 重新排序、重新切段、重新选原 cluster 车辆；
    - 只有完整解通过 validator 且总成本下降，才替换原解。
    """

    DEFAULT_ENABLE = 0
    DEFAULT_MAX_UNITS = 12
    DEFAULT_MAX_ROUTES = 3
    DEFAULT_MAX_SECONDS = 20.0
    DEFAULT_MAX_CLUSTERS = 8
    DEFAULT_RANDOM_ORDERS = 16
    DEFAULT_PERMUTE_UNITS = 8
    DEFAULT_RANDOM_SEED = 20260425

    def __init__(self, route_evaluator: RouteEvaluator) -> None:
        self.route_evaluator = route_evaluator
        self.enabled = self._env_int("Q1_ENABLE_FINAL_BRUTE", self.DEFAULT_ENABLE) > 0
        self.max_units = self._env_int("Q1_BRUTE_MAX_UNITS", self.DEFAULT_MAX_UNITS)
        self.max_routes = self._env_int("Q1_BRUTE_MAX_ROUTES", self.DEFAULT_MAX_ROUTES)
        self.max_seconds = self._env_float("Q1_BRUTE_MAX_SECONDS", self.DEFAULT_MAX_SECONDS)
        self.max_clusters = self._env_int("Q1_BRUTE_MAX_CLUSTERS", self.DEFAULT_MAX_CLUSTERS)
        self.random_orders = self._env_int("Q1_BRUTE_RANDOM_ORDERS", self.DEFAULT_RANDOM_ORDERS)
        self.permute_units = self._env_int("Q1_BRUTE_PERMUTE_UNITS", self.DEFAULT_PERMUTE_UNITS)
        self.random = random.Random(self._env_int("Q1_BRUTE_RANDOM_SEED", self.DEFAULT_RANDOM_SEED))
        self.allow_vehicle_reuse = os.environ.get("Q1_ALLOW_VEHICLE_REUSE", "1") != "0"
        self.turnaround_min = self._env_float("Q1_VEHICLE_TURNAROUND_MIN", 0.0)
        self.parallel_enabled = os.environ.get(
            "Q1_MC_ENABLE_FINAL_POLISH",
            os.environ.get("Q1_MC_ENABLE", "1"),
        ) != "0"
        self.parallel_workers = max(
            1,
            self._env_int("Q1_MC_FINAL_POLISH_WORKERS", self._env_int("Q1_MC_WORKERS", 4)),
        )
        self.parallel_passes = max(1, self._env_int("Q1_MC_FINAL_POLISH_PASSES", 2))

    def polish(self, solution: Solution) -> Solution:
        if not self.enabled:
            return solution
        if len(solution.routes) <= 1:
            return solution

        start_time = time.perf_counter()
        best = self._clone_solution(solution)
        if not self._refresh(best):
            log("最终局部暴搜跳过: 输入解真实车辆排班不可行", indent=1)
            return solution
        validator = SolutionValidator(
            route_evaluator=self.route_evaluator,
            allow_vehicle_reuse=self.allow_vehicle_reuse,
            vehicle_turnaround_min=self.turnaround_min,
        )

        log(
            f"最终局部暴搜启动: max_units={self.max_units}, max_routes={self.max_routes}, "
            f"max_clusters={self.max_clusters}, max_seconds={self.max_seconds:.1f}",
            indent=1,
        )

        if self.parallel_enabled:
            best, tried, improved = self._polish_parallel(best, start_time)
        else:
            tried = 0
            improved = 0
            for cluster_indexes in self._cluster_index_candidates(best):
                if time.perf_counter() - start_time > self.max_seconds:
                    break
                if tried >= self.max_clusters:
                    break
                tried += 1

                trial = self._try_rebuild_cluster(best, cluster_indexes, start_time, validator)
                if trial is None:
                    continue
                if trial.metrics.total_cost + 1e-6 < best.metrics.total_cost:
                    old_cost = best.metrics.total_cost
                    best = trial
                    improved += 1
                    log(
                        f"局部暴搜改进: cluster={cluster_indexes}, 成本 {old_cost:.2f} -> {best.metrics.total_cost:.2f}",
                        indent=2,
                    )

        log(
            f"最终局部暴搜结束: 尝试 {tried} 个 cluster, 改进 {improved} 次, "
            f"最终成本 {best.metrics.total_cost:.2f}",
            indent=1,
        )
        return best

    def _polish_parallel(self, best: Solution, start_time: float) -> tuple[Solution, int, int]:
        """并行评估多个 cluster 重构候选。"""

        tried = 0
        improved = 0
        current = self._clone_solution(best)
        passes = 0

        while passes < self.parallel_passes and time.perf_counter() - start_time < self.max_seconds:
            cluster_candidates = self._cluster_index_candidates(current)[: self.max_clusters]
            if not cluster_candidates:
                break

            remaining_seconds = self.max_seconds - (time.perf_counter() - start_time)
            worker_count = min(self.parallel_workers, len(cluster_candidates))
            tried += len(cluster_candidates)
            log(
                f"最终局部暴搜并行评估: pass={passes + 1}, clusters={len(cluster_candidates)}, workers={worker_count}",
                indent=2,
            )

            config = {
                "max_units": self.max_units,
                "max_routes": self.max_routes,
                "max_seconds": max(1.0, remaining_seconds),
                "max_clusters": self.max_clusters,
                "random_orders": self.random_orders,
                "permute_units": self.permute_units,
                "allow_vehicle_reuse": self.allow_vehicle_reuse,
                "turnaround_min": self.turnaround_min,
                "random_seed": self._env_int("Q1_BRUTE_RANDOM_SEED", self.DEFAULT_RANDOM_SEED) + passes * 1000,
            }

            best_trial: Solution | None = None
            best_cluster: tuple[int, ...] | None = None
            with ProcessPoolExecutor(
                max_workers=worker_count,
                mp_context=mp.get_context("spawn"),
            ) as executor:
                future_map = {
                    executor.submit(
                        _final_polish_cluster_worker,
                        self.route_evaluator,
                        self._clone_solution(current),
                        cluster_indexes,
                        config,
                    ): cluster_indexes
                    for cluster_indexes in cluster_candidates
                }
                for future in as_completed(future_map):
                    cluster_indexes = future_map[future]
                    try:
                        trial = future.result()
                    except Exception as exc:
                        log(f"并行 cluster 失败: {cluster_indexes}, 原因={exc}", indent=3)
                        continue
                    if trial is None:
                        continue
                    if best_trial is None or trial.metrics.total_cost + 1e-6 < best_trial.metrics.total_cost:
                        best_trial = trial
                        best_cluster = cluster_indexes

            if best_trial is None or best_trial.metrics.total_cost + 1e-6 >= current.metrics.total_cost:
                break

            old_cost = current.metrics.total_cost
            current = best_trial
            improved += 1
            log(
                f"并行局部暴搜改进: cluster={best_cluster}, 成本 {old_cost:.2f} -> {current.metrics.total_cost:.2f}",
                indent=2,
            )
            passes += 1

        return current, tried, improved

    def _try_rebuild_cluster(
        self,
        solution: Solution,
        cluster_indexes: tuple[int, ...],
        start_time: float,
        validator: SolutionValidator,
    ) -> Solution | None:
        cluster_routes = [solution.routes[index] for index in cluster_indexes]
        units = self._units_from_routes(cluster_routes)
        if not units or len(units) > self.max_units:
            return None

        outside_routes = [
            self._clone_route(route)
            for index, route in enumerate(solution.routes)
            if index not in set(cluster_indexes)
        ]
        cluster_vehicles = self._cluster_vehicle_pool(cluster_routes)
        if not cluster_vehicles:
            return None

        original_cluster_count = len(cluster_routes)
        max_new_routes = min(original_cluster_count, self.max_routes, len(units))
        best_trial: Solution | None = None

        for ordered_units in self._candidate_orders(units):
            if time.perf_counter() - start_time > self.max_seconds:
                break
            for route_count in range(1, max_new_routes + 1):
                for parts in self._contiguous_partitions(ordered_units, route_count):
                    if time.perf_counter() - start_time > self.max_seconds:
                        break
                    new_routes = self._best_routes_for_parts(parts, cluster_vehicles)
                    if new_routes is None:
                        continue

                    trial = Solution(
                        routes=[*outside_routes, *[self._clone_route(route) for route in new_routes]],
                        unassigned_units=list(solution.unassigned_units),
                        route_evaluations={},
                        metrics=SolutionMetrics(),
                    )
                    if not self._refresh(trial):
                        continue

                    check = validator.validate(trial)
                    if not check["ok"]:
                        continue
                    if best_trial is None or trial.metrics.total_cost + 1e-6 < best_trial.metrics.total_cost:
                        best_trial = trial

        return best_trial

    def _candidate_orders(self, units: Sequence[ServiceUnit]) -> Iterable[list[ServiceUnit]]:
        seen: set[tuple[str, ...]] = set()

        def emit(order: Sequence[ServiceUnit]) -> Iterable[list[ServiceUnit]]:
            signature = tuple(unit.unit_id for unit in order)
            if signature in seen:
                return []
            seen.add(signature)
            return [list(order)]

        base = list(units)
        for order in emit(base):
            yield order
        for order in emit(list(reversed(base))):
            yield order

        angle_sorted = sorted(base, key=lambda unit: self._angle_key(unit))
        for order in emit(angle_sorted):
            yield order

        time_sorted = sorted(base, key=lambda unit: (unit.time_window.end_min, unit.time_window.start_min, unit.customer_id, unit.unit_id))
        for order in emit(time_sorted):
            yield order

        nn = self._nearest_neighbor(base)
        for order in emit(nn):
            yield order

        if len(base) <= self.permute_units:
            for permutation in itertools.permutations(base):
                for order in emit(permutation):
                    yield order
        else:
            for _ in range(max(0, self.random_orders)):
                order = list(base)
                self.random.shuffle(order)
                for emitted in emit(order):
                    yield emitted

    def _contiguous_partitions(
        self,
        units: Sequence[ServiceUnit],
        route_count: int,
    ) -> Iterable[list[list[ServiceUnit]]]:
        n = len(units)
        if route_count <= 0 or route_count > n:
            return
        if route_count == 1:
            yield [list(units)]
            return
        for cuts in itertools.combinations(range(1, n), route_count - 1):
            last = 0
            parts: list[list[ServiceUnit]] = []
            for cut in cuts:
                parts.append(list(units[last:cut]))
                last = cut
            parts.append(list(units[last:]))
            yield parts

    def _best_routes_for_parts(
        self,
        parts: Sequence[Sequence[ServiceUnit]],
        cluster_vehicles: Sequence[VehicleInstance],
    ) -> list[Route] | None:
        used_vehicle_ids: set[str] = set()
        chosen_routes: list[Route] = []

        for part_index, part in enumerate(parts, start=1):
            candidates: list[_RouteCandidate] = []
            for vehicle in cluster_vehicles:
                if vehicle.vehicle_id in used_vehicle_ids:
                    continue
                route = Route(
                    vehicle_id=vehicle.vehicle_id,
                    vehicle_type_id=vehicle.vehicle_type.type_id,
                    departure_min=480,
                    stops=self._merge_units_to_stops(part),
                    route_id=f"B{part_index:04d}",
                )
                route, evaluation = self._retime_route(route)
                if not evaluation.feasible:
                    continue
                candidates.append(
                    _RouteCandidate(
                        route=route,
                        evaluation=evaluation,
                        variable_cost=(
                            evaluation.cost.energy_cost
                            + evaluation.cost.carbon_cost
                            + evaluation.cost.waiting_cost
                            + evaluation.cost.late_cost
                        ),
                        total_cost=evaluation.cost.total_cost,
                    )
                )
            if not candidates:
                return None
            candidates.sort(key=lambda item: (item.total_cost, item.route.vehicle_type_id, item.route.vehicle_id))
            selected = candidates[0]
            used_vehicle_ids.add(selected.route.vehicle_id)
            chosen_routes.append(selected.route)

        return chosen_routes

    def _merge_units_to_stops(self, units: Sequence[ServiceUnit]) -> list[RouteStop]:
        stops: list[RouteStop] = []
        by_customer: dict[int, RouteStop] = {}
        for unit in units:
            stop = by_customer.get(unit.customer_id)
            if stop is None:
                stop = RouteStop(
                    service_unit_ids=[],
                    customer_id=unit.customer_id,
                    delivered_weight=0.0,
                    delivered_volume=0.0,
                )
                by_customer[unit.customer_id] = stop
                stops.append(stop)
            stop.service_unit_ids.append(unit.unit_id)
            stop.delivered_weight += unit.weight
            stop.delivered_volume += unit.volume
        return stops

    def _retime_route(self, route: Route) -> tuple[Route, RouteEvaluation]:
        candidates = self._departure_candidates(route)
        best_route = route
        best_eval = self.route_evaluator.evaluate(route)

        for departure_min in candidates:
            candidate_route = Route(route.vehicle_id, route.vehicle_type_id, departure_min, route.stops, route.route_id)
            evaluation = self.route_evaluator.evaluate(candidate_route)
            if evaluation.feasible and ((not best_eval.feasible) or evaluation.cost.total_cost < best_eval.cost.total_cost):
                best_route = candidate_route
                best_eval = evaluation

        fine_candidates = range(max(480, best_route.departure_min - 10), best_route.departure_min + 11)
        for departure_min in fine_candidates:
            candidate_route = Route(route.vehicle_id, route.vehicle_type_id, departure_min, route.stops, route.route_id)
            evaluation = self.route_evaluator.evaluate(candidate_route)
            if evaluation.feasible and ((not best_eval.feasible) or evaluation.cost.total_cost < best_eval.cost.total_cost):
                best_route = candidate_route
                best_eval = evaluation
        return best_route, best_eval

    def _departure_candidates(self, route: Route) -> list[int]:
        latest_window_end = 1020
        for stop in route.stops:
            customer = self.route_evaluator.customers[stop.customer_id]
            latest_window_end = max(latest_window_end, customer.time_window.end_min)
        upper = min(24 * 60 - 1, latest_window_end)
        candidates: set[int] = set()
        for value in [480, 540, 600, 690, 780, 900, 1020]:
            if 480 <= value <= upper:
                candidates.add(value)
        for value in range(480, upper + 1, 30):
            candidates.add(value)
        for stop in route.stops:
            customer = self.route_evaluator.customers[stop.customer_id]
            for value in [
                customer.time_window.start_min - 120,
                customer.time_window.start_min - 60,
                customer.time_window.start_min - 30,
                customer.time_window.start_min,
                customer.time_window.end_min - 60,
                customer.time_window.end_min - 30,
            ]:
                if value >= 480:
                    candidates.add(min(upper, int(value)))
        return sorted(candidates)

    def _cluster_index_candidates(self, solution: Solution) -> list[tuple[int, ...]]:
        scored: list[tuple[float, int]] = []
        for index, route in enumerate(solution.routes):
            evaluation = evaluation_for(solution.route_evaluations, route, index) or self.route_evaluator.evaluate(route)
            unit_count = max(1, sum(len(stop.service_unit_ids) for stop in route.stops))
            scored.append((evaluation.cost.total_cost / unit_count, index))
        scored.sort(reverse=True)

        clusters: list[tuple[int, ...]] = []
        seen: set[tuple[int, ...]] = set()
        for _, seed_index in scored:
            neighbors = self._nearest_route_indexes(solution, seed_index, limit=max(1, self.max_routes - 1))
            cluster = tuple(sorted([seed_index, *neighbors]))
            if cluster in seen:
                continue
            seen.add(cluster)
            clusters.append(cluster)
        return clusters

    def _nearest_route_indexes(self, solution: Solution, seed_index: int, limit: int) -> list[int]:
        seed = solution.routes[seed_index]
        scored: list[tuple[float, int]] = []
        for index, route in enumerate(solution.routes):
            if index == seed_index:
                continue
            scored.append((self._route_distance(seed, route), index))
        scored.sort(key=lambda item: (item[0], item[1]))
        return [index for _, index in scored[:limit]]

    def _route_distance(self, left: Route, right: Route) -> float:
        if not left.stops or not right.stops:
            return float("inf")
        return min(
            self.route_evaluator.distance_matrix[left_stop.customer_id][right_stop.customer_id]
            for left_stop in left.stops
            for right_stop in right.stops
        )

    def _units_from_routes(self, routes: Sequence[Route]) -> list[ServiceUnit]:
        units: list[ServiceUnit] = []
        seen: set[str] = set()
        for route in routes:
            for stop in route.stops:
                for unit_id in stop.service_unit_ids:
                    if unit_id in seen:
                        continue
                    unit = self.route_evaluator.service_units.get(unit_id)
                    if unit is not None:
                        units.append(unit)
                        seen.add(unit_id)
        return units

    def _cluster_vehicle_pool(self, routes: Sequence[Route]) -> list[VehicleInstance]:
        vehicle_ids = []
        seen: set[str] = set()
        for route in routes:
            if route.vehicle_id in self.route_evaluator.vehicles and route.vehicle_id not in seen:
                vehicle_ids.append(route.vehicle_id)
                seen.add(route.vehicle_id)
        return [self.route_evaluator.vehicles[vehicle_id] for vehicle_id in vehicle_ids]

    def _nearest_neighbor(self, units: Sequence[ServiceUnit]) -> list[ServiceUnit]:
        if not units:
            return []
        unvisited = list(units)
        current = min(unvisited, key=lambda unit: (unit.time_window.end_min, -unit.weight, unit.unit_id))
        order = [current]
        unvisited.remove(current)
        while unvisited:
            nxt = min(unvisited, key=lambda unit: (self._unit_distance(current, unit), unit.time_window.end_min, unit.unit_id))
            order.append(nxt)
            unvisited.remove(nxt)
            current = nxt
        return order

    def _unit_distance(self, left: ServiceUnit, right: ServiceUnit) -> float:
        return self.route_evaluator.distance_matrix[left.customer_id][right.customer_id]

    def _angle_key(self, unit: ServiceUnit) -> tuple[float, int, str]:
        customer = self.route_evaluator.customers[unit.customer_id]
        return (math.atan2(customer.y, customer.x), customer.time_window.end_min, unit.unit_id)

    def _refresh(self, solution: Solution) -> bool:
        solution.routes = [route for route in solution.routes if route.stops]
        assign_route_ids(solution.routes, prefix="F")
        schedule_ok = True
        if self.allow_vehicle_reuse:
            schedule_ok = assign_reusable_vehicle_schedules(
                routes=solution.routes,
                vehicles_by_id=self.route_evaluator.vehicles,
                route_evaluator=self.route_evaluator,
                turnaround_min=self.turnaround_min,
            )
        evaluations: dict[str, RouteEvaluation] = {}
        for index, route in enumerate(solution.routes, start=1):
            evaluations[route_key(route, index)] = self.route_evaluator.evaluate(route)
        solution.route_evaluations = evaluations
        solution.metrics = build_solution_metrics(
            routes=solution.routes,
            route_evaluations=evaluations,
            unassigned_units=solution.unassigned_units,
            vehicles_by_id=self.route_evaluator.vehicles,
        )
        return schedule_ok

    def _clone_solution(self, solution: Solution) -> Solution:
        return Solution(
            routes=[self._clone_route(route) for route in solution.routes],
            unassigned_units=list(solution.unassigned_units),
            route_evaluations=dict(solution.route_evaluations),
            metrics=SolutionMetrics(
                total_cost=solution.metrics.total_cost,
                total_distance_km=solution.metrics.total_distance_km,
                total_energy_cost=solution.metrics.total_energy_cost,
                total_carbon_cost=solution.metrics.total_carbon_cost,
                total_waiting_cost=solution.metrics.total_waiting_cost,
                total_late_cost=solution.metrics.total_late_cost,
                used_vehicle_count=solution.metrics.used_vehicle_count,
                unassigned_unit_count=solution.metrics.unassigned_unit_count,
            ),
        )

    def _clone_route(self, route: Route) -> Route:
        return Route(
            vehicle_id=route.vehicle_id,
            vehicle_type_id=route.vehicle_type_id,
            departure_min=route.departure_min,
            stops=[
                RouteStop(
                    service_unit_ids=list(stop.service_unit_ids),
                    customer_id=stop.customer_id,
                    delivered_weight=stop.delivered_weight,
                    delivered_volume=stop.delivered_volume,
                )
                for stop in route.stops
            ],
            route_id=route.route_id,
        )

    @staticmethod
    def _env_int(name: str, default: int) -> int:
        value = os.environ.get(name)
        if value is None or value == "":
            return default
        return int(value)

    @staticmethod
    def _env_float(name: str, default: float) -> float:
        value = os.environ.get(name)
        if value is None or value == "":
            return default
        return float(value)
