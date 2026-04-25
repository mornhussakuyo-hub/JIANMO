from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
import os

from .log_utils import log
from .model import Route, RouteEvaluation, RouteStop, ServiceUnit, Solution, SolutionMetrics, VehicleInstance
from .route_evaluator import RouteEvaluator
from .solution_utils import assign_route_ids, build_solution_metrics, departure_candidates_for_route, route_key


@dataclass(slots=True)
class SplitRouteCandidate:
    """一个 giant tour 连续片段对应的一条候选车辆路线。"""

    start_index: int
    end_index: int
    vehicle_type_id: int
    representative_vehicle_id: str
    route: Route
    evaluation: RouteEvaluation


@dataclass(slots=True)
class SplitArc:
    """Split DP 转移弧：tour[start:end] 被切成一条路线。"""

    start_index: int
    end_index: int
    candidates: list[SplitRouteCandidate]
    large_vehicle_required: bool
    non_small_vehicle_required: bool

    @property
    def best_cost(self) -> float:
        return self.candidates[0].evaluation.cost.total_cost


class SplitDPBuilder:
    """
    Giant Tour 的 Split DP 切分器。

    状态转移：
        dp[0] = 0
        dp[j] = min_{0 <= i < j} dp[i] + route_cost(i, j)

    其中 route_cost(i, j) 表示把 tour[i:j] 作为一条完整路线
    0 -> segment -> 0 后，在可行车型和发车时刻中取得的最低路线成本。
    """

    def __init__(self, route_evaluator: RouteEvaluator) -> None:
        self.route_evaluator = route_evaluator
        self._route_cost_cache: dict[tuple[str, ...], list[SplitRouteCandidate]] = {}
        self.allow_vehicle_reuse = os.environ.get("Q1_ALLOW_VEHICLE_REUSE", "1") != "0"
        self.vehicle_turnaround_min = float(os.environ.get("Q1_VEHICLE_TURNAROUND_MIN", "0"))

    def build_solution(
        self,
        tour: Sequence[ServiceUnit],
        vehicles: Sequence[VehicleInstance],
    ) -> Solution:
        """对一条 giant tour 运行 Split DP，并分配具体车辆实例。"""

        units = list(tour)
        n = len(units)
        if n == 0:
            return Solution()

        log(f"Split DP 启动: tour 长度 {n}", indent=3)
        vehicles_by_type = self._vehicles_by_type(vehicles)
        max_weight = max(vehicle.vehicle_type.max_weight for vehicle in vehicles)
        max_volume = max(vehicle.vehicle_type.max_volume for vehicle in vehicles)

        large_vehicle_type_ids = self._large_vehicle_type_ids(vehicles_by_type)
        large_vehicle_limit = sum(len(vehicles_by_type[type_id]) for type_id in large_vehicle_type_ids)
        small_vehicle_type_ids = self._small_vehicle_type_ids(vehicles_by_type)
        non_small_vehicle_limit = sum(
            len(vehicle_list)
            for type_id, vehicle_list in vehicles_by_type.items()
            if type_id not in small_vehicle_type_ids
        )
        if self.allow_vehicle_reuse:
            large_vehicle_limit = 10_000
            non_small_vehicle_limit = 10_000
        log(
            f"车辆资源识别: 大车车型 {sorted(large_vehicle_type_ids)} 上限 {large_vehicle_limit}, "
            f"小车车型 {sorted(small_vehicle_type_ids)}, 非小车资源上限 {non_small_vehicle_limit}, "
            f"车辆复用 {self.allow_vehicle_reuse}",
            indent=4,
        )

        dp: list[dict[tuple[int, int], float]] = [dict() for _ in range(n + 1)]
        prev: list[dict[tuple[int, int], tuple[SplitArc, tuple[int, int]]]] = [dict() for _ in range(n + 1)]
        dp[0][(0, 0)] = 0.0

        evaluated_segment_count = 0
        feasible_segment_count = 0
        for start in range(n):
            if start == 0 or (start + 1) % 25 == 0 or start == n - 1:
                active_states = sum(len(states) for states in dp[: start + 1])
                log(
                    f"Split DP 扫描起点 {start + 1}/{n}: 当前累计状态 {active_states}",
                    indent=4,
                )

            total_weight = 0.0
            total_volume = 0.0
            for end in range(start + 1, n + 1):
                unit = units[end - 1]
                total_weight += unit.weight
                total_volume += unit.volume

                if total_weight > max_weight + 1e-9 or total_volume > max_volume + 1e-9:
                    break

                evaluated_segment_count += 1
                candidates = self._route_candidates_for_segment(
                    segment=units[start:end],
                    vehicles_by_type=vehicles_by_type,
                    start_index=start,
                    end_index=end,
                )
                if not candidates:
                    continue
                feasible_segment_count += 1

                arc = SplitArc(
                    start_index=start,
                    end_index=end,
                    candidates=candidates,
                    large_vehicle_required=self._requires_large_vehicle(candidates, large_vehicle_type_ids),
                    non_small_vehicle_required=self._requires_non_small_vehicle(
                        candidates,
                        small_vehicle_type_ids,
                    ),
                )
                large_increment = 1 if arc.large_vehicle_required else 0
                non_small_increment = 1 if arc.non_small_vehicle_required else 0

                for state, current_cost in list(dp[start].items()):
                    used_large, used_non_small = state
                    new_used_large = used_large + large_increment
                    new_used_non_small = used_non_small + non_small_increment
                    if new_used_large > large_vehicle_limit:
                        continue
                    if new_used_non_small > non_small_vehicle_limit:
                        continue

                    new_state = (new_used_large, new_used_non_small)
                    new_cost = current_cost + arc.best_cost
                    if new_cost < dp[end].get(new_state, float("inf")):
                        dp[end][new_state] = new_cost
                        prev[end][new_state] = (arc, state)

        if not dp[n]:
            log(
                f"Split DP 失败: 评价片段 {evaluated_segment_count} 个, 可行片段 {feasible_segment_count} 个, "
                "终点没有可行状态",
                indent=4,
            )
            return Solution(unassigned_units=units)

        best_state = min(dp[n], key=lambda state: dp[n][state])
        log(
            f"Split DP 转移完成: 评价片段 {evaluated_segment_count} 个, 可行片段 {feasible_segment_count} 个, "
            f"终点状态 {len(dp[n])} 个, 最优资源状态 large/non_small={best_state}, "
            f"DP成本 {dp[n][best_state]:.2f}",
            indent=4,
        )
        arcs = self._backtrack_arcs(prev, best_state)
        log(f"Split DP 回溯完成: 切出 {len(arcs)} 条路线片段", indent=4)
        return self._materialize_solution(
            arcs=arcs,
            vehicles_by_type=vehicles_by_type,
            all_units=units,
            large_vehicle_type_ids=large_vehicle_type_ids,
            small_vehicle_type_ids=small_vehicle_type_ids,
        )

    def _route_candidates_for_segment(
        self,
        segment: Sequence[ServiceUnit],
        vehicles_by_type: dict[int, list[VehicleInstance]],
        start_index: int,
        end_index: int,
    ) -> list[SplitRouteCandidate]:
        """计算 tour 连续片段的可行车型路线候选，并按成本升序缓存。"""

        cache_key = tuple(unit.unit_id for unit in segment)
        cached = self._route_cost_cache.get(cache_key)
        if cached is not None:
            return [
                SplitRouteCandidate(
                    start_index=start_index,
                    end_index=end_index,
                    vehicle_type_id=candidate.vehicle_type_id,
                    representative_vehicle_id=candidate.representative_vehicle_id,
                    route=candidate.route,
                    evaluation=candidate.evaluation,
                )
                for candidate in cached
            ]

        stops = self._merge_segment_to_stops(segment)
        total_weight = sum(stop.delivered_weight for stop in stops)
        total_volume = sum(stop.delivered_volume for stop in stops)

        candidates: list[SplitRouteCandidate] = []
        for vehicle_type_id, vehicles in sorted(vehicles_by_type.items()):
            representative = vehicles[0]
            if total_weight > representative.vehicle_type.max_weight + 1e-9:
                continue
            if total_volume > representative.vehicle_type.max_volume + 1e-9:
                continue

            route = Route(
                vehicle_id=representative.vehicle_id,
                vehicle_type_id=vehicle_type_id,
                departure_min=480,
                stops=stops,
            )
            route, evaluation = self._retime_route(route)
            if not evaluation.feasible:
                continue

            candidates.append(
                SplitRouteCandidate(
                    start_index=start_index,
                    end_index=end_index,
                    vehicle_type_id=vehicle_type_id,
                    representative_vehicle_id=representative.vehicle_id,
                    route=route,
                    evaluation=evaluation,
                )
            )

        candidates.sort(key=lambda candidate: candidate.evaluation.cost.total_cost)
        self._route_cost_cache[cache_key] = candidates
        return candidates

    def _merge_segment_to_stops(self, segment: Sequence[ServiceUnit]) -> list[RouteStop]:
        """把 segment 内同客户 ServiceUnit 合并成一个 RouteStop，顺序按首次出现。"""

        stops: list[RouteStop] = []
        stop_by_customer: dict[int, RouteStop] = {}

        for unit in segment:
            stop = stop_by_customer.get(unit.customer_id)
            if stop is None:
                stop = RouteStop(
                    service_unit_ids=[unit.unit_id],
                    customer_id=unit.customer_id,
                    delivered_weight=unit.weight,
                    delivered_volume=unit.volume,
                )
                stop_by_customer[unit.customer_id] = stop
                stops.append(stop)
            else:
                stop.service_unit_ids.append(unit.unit_id)
                stop.delivered_weight += unit.weight
                stop.delivered_volume += unit.volume

        return stops

    def _requires_large_vehicle(
        self,
        candidates: Sequence[SplitRouteCandidate],
        large_vehicle_type_ids: set[int],
    ) -> bool:
        """若没有任何非大车候选能承运该片段，则该 DP 弧消耗一个大车资源。"""

        return all(candidate.vehicle_type_id in large_vehicle_type_ids for candidate in candidates)

    def _requires_non_small_vehicle(
        self,
        candidates: Sequence[SplitRouteCandidate],
        small_vehicle_type_ids: set[int],
    ) -> bool:
        """若没有任何小车候选能承运该片段，则该 DP 弧消耗一个非小车资源。"""

        return all(candidate.vehicle_type_id not in small_vehicle_type_ids for candidate in candidates)

    def _backtrack_arcs(
        self,
        prev: Sequence[dict[tuple[int, int], tuple[SplitArc, tuple[int, int]]]],
        state: tuple[int, int],
    ) -> list[SplitArc]:
        arcs: list[SplitArc] = []
        cursor = len(prev) - 1
        state_cursor = state
        while cursor > 0:
            item = prev[cursor].get(state_cursor)
            if item is None:
                break
            arc, previous_state = item
            arcs.append(arc)
            cursor = arc.start_index
            state_cursor = previous_state
        arcs.reverse()
        return arcs

    def _materialize_solution(
        self,
        arcs: Sequence[SplitArc],
        vehicles_by_type: dict[int, list[VehicleInstance]],
        all_units: Sequence[ServiceUnit],
        large_vehicle_type_ids: set[int],
        small_vehicle_type_ids: set[int],
    ) -> Solution:
        """把 DP 弧转成具体车辆路线，若首选车型用完则尝试备用车型。"""

        next_vehicle_index = {vehicle_type_id: 0 for vehicle_type_id in vehicles_by_type}
        vehicle_schedules: dict[str, list[tuple[float, float]]] = defaultdict(list)
        routes: list[Route] = []
        route_evaluations: dict[str, RouteEvaluation] = {}
        assigned_unit_ids: set[str] = set()

        for arc in arcs:
            assigned = False
            ordered_candidates = sorted(
                arc.candidates,
                key=lambda candidate: (
                    self._vehicle_assignment_priority(
                        candidate.vehicle_type_id,
                        arc,
                        large_vehicle_type_ids,
                        small_vehicle_type_ids,
                    ),
                    candidate.evaluation.cost.total_cost,
                ),
            )

            for candidate in ordered_candidates:
                available_vehicles = vehicles_by_type[candidate.vehicle_type_id]
                if self.allow_vehicle_reuse:
                    vehicle = self._choose_reusable_vehicle(
                        available_vehicles=available_vehicles,
                        route=candidate.route,
                        evaluation=candidate.evaluation,
                        vehicle_schedules=vehicle_schedules,
                    )
                    if vehicle is None:
                        continue
                else:
                    vehicle_index = next_vehicle_index[candidate.vehicle_type_id]
                    if vehicle_index >= len(available_vehicles):
                        continue
                    vehicle = available_vehicles[vehicle_index]

                route = Route(
                    vehicle_id=vehicle.vehicle_id,
                    vehicle_type_id=vehicle.vehicle_type.type_id,
                    departure_min=candidate.route.departure_min,
                    stops=[
                        RouteStop(
                            service_unit_ids=list(stop.service_unit_ids),
                            customer_id=stop.customer_id,
                            delivered_weight=stop.delivered_weight,
                            delivered_volume=stop.delivered_volume,
                        )
                        for stop in candidate.route.stops
                    ],
                    route_id=f"S{len(routes) + 1:04d}",
                )
                evaluation = self.route_evaluator.evaluate(route)
                if not evaluation.feasible:
                    continue

                if self.allow_vehicle_reuse:
                    self._add_vehicle_schedule(vehicle_schedules, route.vehicle_id, route, evaluation)
                else:
                    next_vehicle_index[candidate.vehicle_type_id] += 1
                routes.append(route)
                route_evaluations[route_key(route)] = evaluation
                for stop in route.stops:
                    assigned_unit_ids.update(stop.service_unit_ids)
                assigned = True
                break

            if not assigned:
                log(
                    f"Split DP 落车失败: segment [{arc.start_index}, {arc.end_index}) 没有可用车辆实例",
                    indent=4,
                )
                break

            if len(routes) == 1 or len(routes) % 25 == 0 or len(routes) == len(arcs):
                log(
                    f"Split DP 落车进度 {len(routes)}/{len(arcs)}: "
                    f"当前车辆 {routes[-1].vehicle_id}, 车型 {routes[-1].vehicle_type_id}",
                    indent=4,
                )

        unassigned_units = [unit for unit in all_units if unit.unit_id not in assigned_unit_ids]
        assign_route_ids(routes, prefix="S")
        if self.allow_vehicle_reuse:
            self._reassign_reusable_vehicle_schedules(routes)
            route_evaluations = {
                route_key(route, index): self.route_evaluator.evaluate(route)
                for index, route in enumerate(routes, start=1)
            }
        solution = Solution(
            routes=routes,
            unassigned_units=unassigned_units,
            route_evaluations=route_evaluations,
            metrics=self._build_metrics(routes, route_evaluations, unassigned_units),
        )
        log(
            f"Split DP 完成: 路线 {len(solution.routes)} 条, 未分配 {len(solution.unassigned_units)} 个, "
            f"成本 {solution.metrics.total_cost:.2f}",
            indent=4,
        )
        return solution

    def _choose_reusable_vehicle(
        self,
        available_vehicles: Sequence[VehicleInstance],
        route: Route,
        evaluation: RouteEvaluation,
        vehicle_schedules: dict[str, list[tuple[float, float]]],
    ) -> VehicleInstance | None:
        """在同车型车辆中选择一辆日程不冲突的真实车辆。"""

        if evaluation.return_to_depot_min is None:
            return None

        best_vehicle: VehicleInstance | None = None
        best_score: tuple[int, float, str] | None = None
        for vehicle in available_vehicles:
            if not self._schedule_can_accept(
                schedules=vehicle_schedules[vehicle.vehicle_id],
                start_min=float(route.departure_min),
                end_min=evaluation.return_to_depot_min,
            ):
                continue

            score = (
                0 if vehicle_schedules[vehicle.vehicle_id] else 1,
                self._latest_finish(vehicle_schedules[vehicle.vehicle_id]),
                vehicle.vehicle_id,
            )
            if best_score is None or score < best_score:
                best_vehicle = vehicle
                best_score = score

        return best_vehicle

    def _schedule_can_accept(
        self,
        schedules: Sequence[tuple[float, float]],
        start_min: float,
        end_min: float,
    ) -> bool:
        for existing_start, existing_end in schedules:
            if start_min < existing_end + self.vehicle_turnaround_min and end_min + self.vehicle_turnaround_min > existing_start:
                return False
        return True

    @staticmethod
    def _latest_finish(schedules: Sequence[tuple[float, float]]) -> float:
        if not schedules:
            return 0.0
        return max(end for _, end in schedules)

    def _add_vehicle_schedule(
        self,
        vehicle_schedules: dict[str, list[tuple[float, float]]],
        vehicle_id: str,
        route: Route,
        evaluation: RouteEvaluation,
    ) -> None:
        if evaluation.return_to_depot_min is None:
            return
        vehicle_schedules[vehicle_id].append((float(route.departure_min), evaluation.return_to_depot_min))
        vehicle_schedules[vehicle_id].sort()

    def _reassign_reusable_vehicle_schedules(self, routes: Sequence[Route]) -> None:
        """落车结束后按时间顺序重新压缩真实车辆使用数。"""

        vehicles_by_type = self._vehicles_by_type(self.route_evaluator.vehicles.values())
        schedules: dict[str, list[tuple[float, float]]] = defaultdict(list)

        for route in sorted(routes, key=lambda item: (item.departure_min, item.route_id, item.vehicle_id)):
            available_vehicles = vehicles_by_type.get(route.vehicle_type_id, [])
            chosen_vehicle: VehicleInstance | None = None
            chosen_eval: RouteEvaluation | None = None
            chosen_score: tuple[int, float, str] | None = None

            for vehicle in available_vehicles:
                candidate_route = Route(
                    vehicle_id=vehicle.vehicle_id,
                    vehicle_type_id=vehicle.vehicle_type.type_id,
                    departure_min=route.departure_min,
                    stops=route.stops,
                    route_id=route.route_id,
                )
                evaluation = self.route_evaluator.evaluate(candidate_route)
                if not evaluation.feasible or evaluation.return_to_depot_min is None:
                    continue
                if not self._schedule_can_accept(
                    schedules=schedules[vehicle.vehicle_id],
                    start_min=float(route.departure_min),
                    end_min=evaluation.return_to_depot_min,
                ):
                    continue

                score = (
                    0 if schedules[vehicle.vehicle_id] else 1,
                    self._latest_finish(schedules[vehicle.vehicle_id]),
                    vehicle.vehicle_id,
                )
                if chosen_score is None or score < chosen_score:
                    chosen_vehicle = vehicle
                    chosen_eval = evaluation
                    chosen_score = score

            if chosen_vehicle is None or chosen_eval is None:
                continue

            route.vehicle_id = chosen_vehicle.vehicle_id
            route.vehicle_type_id = chosen_vehicle.vehicle_type.type_id
            schedules[route.vehicle_id].append((float(route.departure_min), chosen_eval.return_to_depot_min))
            schedules[route.vehicle_id].sort()

    def _vehicles_by_type(self, vehicles: Sequence[VehicleInstance]) -> dict[int, list[VehicleInstance]]:
        grouped: dict[int, list[VehicleInstance]] = defaultdict(list)
        for vehicle in vehicles:
            grouped[vehicle.vehicle_type.type_id].append(vehicle)
        for vehicle_list in grouped.values():
            vehicle_list.sort(key=lambda vehicle: vehicle.vehicle_id)
        return dict(grouped)

    def _vehicle_assignment_priority(
        self,
        vehicle_type_id: int,
        arc: SplitArc,
        large_vehicle_type_ids: set[int],
        small_vehicle_type_ids: set[int],
    ) -> int:
        """落车时优先使用满足该片段所需的最小车辆等级。"""

        is_large = vehicle_type_id in large_vehicle_type_ids
        is_small = vehicle_type_id in small_vehicle_type_ids

        if arc.large_vehicle_required:
            return 0 if is_large else 1
        if arc.non_small_vehicle_required:
            if not is_large and not is_small:
                return 0
            if is_large:
                return 1
            return 2
        if is_small:
            return 0
        if not is_large:
            return 1
        return 2

    def _large_vehicle_type_ids(self, vehicles_by_type: dict[int, list[VehicleInstance]]) -> set[int]:
        """
        识别大车车型。

        当前 Q1 数据中，车型 1/4 是 3000kg 级大车。这里不硬编码车型号，
        而是用车型二安全容量 1500kg / 10.8m3 作为普通车边界。
        """

        large_type_ids: set[int] = set()
        for vehicle_type_id, vehicles in vehicles_by_type.items():
            vehicle_type = vehicles[0].vehicle_type
            if vehicle_type.max_weight > 1500.0 + 1e-9 or vehicle_type.max_volume > 10.8 + 1e-9:
                large_type_ids.add(vehicle_type_id)
        return large_type_ids

    def _small_vehicle_type_ids(self, vehicles_by_type: dict[int, list[VehicleInstance]]) -> set[int]:
        """识别小车车型，当前 Q1 数据中对应 1250kg / 8.5m3 及以下车辆。"""

        small_type_ids: set[int] = set()
        for vehicle_type_id, vehicles in vehicles_by_type.items():
            vehicle_type = vehicles[0].vehicle_type
            if vehicle_type.max_weight <= 1250.0 + 1e-9 and vehicle_type.max_volume <= 8.5 + 1e-9:
                small_type_ids.add(vehicle_type_id)
        return small_type_ids

    def _retime_route(self, route: Route) -> tuple[Route, RouteEvaluation]:
        """搜索该路线较好的实际发车时刻。"""

        candidates = self._departure_candidates(route)
        best_route = route
        best_eval = self.route_evaluator.evaluate(route)

        for departure_min in candidates:
            candidate_route = Route(
                vehicle_id=route.vehicle_id,
                vehicle_type_id=route.vehicle_type_id,
                departure_min=departure_min,
                stops=route.stops,
                route_id=route.route_id,
            )
            evaluation = self.route_evaluator.evaluate(candidate_route)
            if not evaluation.feasible:
                continue
            if (not best_eval.feasible) or evaluation.cost.total_cost < best_eval.cost.total_cost:
                best_route = candidate_route
                best_eval = evaluation

        fine_candidates = range(max(480, best_route.departure_min - 10), best_route.departure_min + 11)
        for departure_min in fine_candidates:
            candidate_route = Route(
                vehicle_id=route.vehicle_id,
                vehicle_type_id=route.vehicle_type_id,
                departure_min=departure_min,
                stops=route.stops,
                route_id=route.route_id,
            )
            evaluation = self.route_evaluator.evaluate(candidate_route)
            if not evaluation.feasible:
                continue
            if (not best_eval.feasible) or evaluation.cost.total_cost < best_eval.cost.total_cost:
                best_route = candidate_route
                best_eval = evaluation

        return best_route, best_eval

    def _departure_candidates(self, route: Route) -> list[int]:
        return departure_candidates_for_route(route, self.route_evaluator)

    def _build_metrics(
        self,
        routes: Sequence[Route],
        route_evaluations: dict[str, RouteEvaluation],
        unassigned_units: Sequence[ServiceUnit],
    ) -> SolutionMetrics:
        return build_solution_metrics(
            routes=routes,
            route_evaluations=route_evaluations,
            unassigned_units=unassigned_units,
            vehicles_by_id=self.route_evaluator.vehicles,
        )
