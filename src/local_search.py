from __future__ import annotations

import math
import os
import random
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from .log_utils import log
from .model import Route, RouteEvaluation, RouteStop, ServiceUnit, Solution, SolutionMetrics, VehicleInstance
from .route_evaluator import RouteEvaluator


@dataclass(slots=True)
class InsertionMove:
    """ALNS repair 阶段的一个插入动作。"""

    unit: ServiceUnit
    route_index: int | None
    insert_position: int
    route: Route
    evaluation: RouteEvaluation
    delta_cost: float


class LocalSearchEngine:
    """Q1 ALNS 主搜索器。最终精修/VND 暂不在这里实现。"""

    DEFAULT_ITERATIONS = 12
    DEFAULT_DESTROY_MIN_RATIO = 0.03
    DEFAULT_DESTROY_MAX_RATIO = 0.06
    DEFAULT_MAX_REPAIR_ROUTES = 24
    DEFAULT_MAX_POSITION_NEIGHBORS = 3
    DEFAULT_ROUTE_ELIMINATION_PERIOD = 5
    DEFAULT_ROUTE_ELIMINATION_CANDIDATES = 4
    DEFAULT_POST_ROUTE_ELIMINATION_PASSES = 2
    DEFAULT_POST_2OPT_MAX_ROUTE_SIZE = 10
    DEFAULT_POST_2OPT_PASSES = 1
    ACCEPTED_WORSE_SCORE = 1.0
    IMPROVED_CURRENT_SCORE = 4.0
    NEW_BEST_SCORE = 10.0
    WEIGHT_DECAY = 0.8
    WEIGHT_UPDATE_PERIOD = 25
    RANDOM_SEED = 20260425
    UNASSIGNED_PENALTY = 1_000_000.0

    def __init__(self, route_evaluator: RouteEvaluator) -> None:
        self.route_evaluator = route_evaluator
        self.iterations = self._env_int("Q1_ALNS_ITERATIONS", self.DEFAULT_ITERATIONS)
        self.destroy_min_ratio = self._env_float("Q1_ALNS_DESTROY_MIN_RATIO", self.DEFAULT_DESTROY_MIN_RATIO)
        self.destroy_max_ratio = self._env_float("Q1_ALNS_DESTROY_MAX_RATIO", self.DEFAULT_DESTROY_MAX_RATIO)
        self.max_repair_routes = self._env_int("Q1_ALNS_MAX_REPAIR_ROUTES", self.DEFAULT_MAX_REPAIR_ROUTES)
        self.max_position_neighbors = self._env_int(
            "Q1_ALNS_MAX_POSITION_NEIGHBORS",
            self.DEFAULT_MAX_POSITION_NEIGHBORS,
        )
        self.route_elimination_period = self._env_int(
            "Q1_ALNS_ROUTE_ELIMINATION_PERIOD",
            self.DEFAULT_ROUTE_ELIMINATION_PERIOD,
        )
        self.route_elimination_candidates = self._env_int(
            "Q1_ALNS_ROUTE_ELIMINATION_CANDIDATES",
            self.DEFAULT_ROUTE_ELIMINATION_CANDIDATES,
        )
        self.post_route_elimination_passes = self._env_int(
            "Q1_POST_ROUTE_ELIMINATION_PASSES",
            self.DEFAULT_POST_ROUTE_ELIMINATION_PASSES,
        )
        self.post_2opt_max_route_size = self._env_int(
            "Q1_POST_2OPT_MAX_ROUTE_SIZE",
            self.DEFAULT_POST_2OPT_MAX_ROUTE_SIZE,
        )
        self.post_2opt_passes = self._env_int("Q1_POST_2OPT_PASSES", self.DEFAULT_POST_2OPT_PASSES)
        self.enable_related_route_removal = self._env_int("Q1_ALNS_ENABLE_RELATED_ROUTE_REMOVAL", 0) > 0
        self.random_seed = self._env_int("Q1_ALNS_RANDOM_SEED", self.RANDOM_SEED)
        self.random = random.Random(self.random_seed)

    def improve(self, solution: Solution) -> Solution:
        """运行一版轻量 ALNS：destroy + repair + 模拟退火接受 + 自适应权重。"""

        current = self._clone_solution(solution)
        self._refresh_solution(current)
        best = self._clone_solution(current)

        current_cost = self._fitness(current)
        best_cost = self._fitness(best)
        temperature = max(1.0, 0.05 * max(current_cost, 1.0))
        cooling_rate = 0.995

        destroy_ops: dict[str, Callable[[Solution, int], list[ServiceUnit]]] = {
            "random_removal": self._destroy_random_removal,
            "route_removal": self._destroy_route_removal,
            "worst_removal": self._destroy_worst_removal,
        }
        if self.enable_related_route_removal:
            destroy_ops["related_route_removal"] = self._destroy_related_route_removal
        repair_ops: dict[str, Callable[[Solution, list[ServiceUnit]], None]] = {
            "greedy_insertion": self._repair_greedy_insertion,
            "regret2_insertion": self._repair_regret2_insertion,
        }

        destroy_weights = {name: 1.0 for name in destroy_ops}
        repair_weights = {name: 1.0 for name in repair_ops}
        destroy_scores = {name: 0.0 for name in destroy_ops}
        repair_scores = {name: 0.0 for name in repair_ops}
        destroy_counts = {name: 0 for name in destroy_ops}
        repair_counts = {name: 0 for name in repair_ops}

        log(
            f"ALNS 启动: 初始成本 {current.metrics.total_cost:.2f}, "
            f"路线 {len(current.routes)} 条, 未分配 {len(current.unassigned_units)} 个, "
            f"迭代 {self.iterations} 轮",
            indent=1,
        )
        log(
            f"ALNS 参数: destroy_ratio=[{self.destroy_min_ratio:.3f}, {self.destroy_max_ratio:.3f}], "
            f"max_repair_routes={self.max_repair_routes}, "
            f"max_position_neighbors={self.max_position_neighbors}, "
            f"route_elimination_period={self.route_elimination_period}, "
            f"route_elimination_candidates={self.route_elimination_candidates}, "
            f"post_route_elimination_passes={self.post_route_elimination_passes}, "
            f"related_route_removal={self.enable_related_route_removal}, seed={self.random_seed}",
            indent=2,
        )

        for iteration in range(1, self.iterations + 1):
            destroy_name = self._weighted_choice(destroy_weights)
            repair_name = self._weighted_choice(repair_weights)
            remove_count = self._draw_remove_count(current)

            candidate = self._clone_solution(current)
            removed_units = destroy_ops[destroy_name](candidate, remove_count)
            repair_ops[repair_name](candidate, removed_units)
            self._refresh_solution(candidate)

            if self._should_try_route_elimination(iteration):
                self._route_elimination_pass(candidate, max_attempts=self.route_elimination_candidates)

            candidate_cost = self._fitness(candidate)
            delta = candidate_cost - current_cost
            accepted = delta <= 0 or self.random.random() < math.exp(-delta / max(temperature, 1e-9))

            reward = 0.0
            if accepted:
                current = candidate
                current_cost = candidate_cost
                reward = self.ACCEPTED_WORSE_SCORE

                if delta < 0:
                    reward = self.IMPROVED_CURRENT_SCORE

                if candidate_cost < best_cost:
                    best = self._clone_solution(candidate)
                    best_cost = candidate_cost
                    reward = self.NEW_BEST_SCORE
                    log(
                        f"ALNS 第 {iteration} 轮发现新最优: 成本 {best.metrics.total_cost:.2f}, "
                        f"路线 {len(best.routes)} 条, 未分配 {len(best.unassigned_units)} 个, "
                        f"destroy={destroy_name}, repair={repair_name}",
                        indent=2,
                    )

            destroy_scores[destroy_name] += reward
            repair_scores[repair_name] += reward
            destroy_counts[destroy_name] += 1
            repair_counts[repair_name] += 1

            if iteration % self.WEIGHT_UPDATE_PERIOD == 0:
                self._update_weights(destroy_weights, destroy_scores, destroy_counts)
                self._update_weights(repair_weights, repair_scores, repair_counts)
                destroy_scores = {name: 0.0 for name in destroy_ops}
                repair_scores = {name: 0.0 for name in repair_ops}
                destroy_counts = {name: 0 for name in destroy_ops}
                repair_counts = {name: 0 for name in repair_ops}

            if iteration == 1 or iteration % 20 == 0 or iteration == self.iterations:
                log(
                    f"ALNS 进度 {iteration}/{self.iterations}: "
                    f"current={current.metrics.total_cost:.2f}, best={best.metrics.total_cost:.2f}, "
                    f"temperature={temperature:.2f}, accepted={accepted}",
                    indent=2,
                )

            temperature *= cooling_rate

        log("ALNS 后处理: 路线消除、路线内 2-opt、车型重分配", indent=1)
        for _ in range(max(0, self.post_route_elimination_passes)):
            changed = self._route_elimination_pass(best, max_attempts=max(self.route_elimination_candidates * 2, 1))
            if not changed:
                break
        self._two_opt_pass(best)
        self._optimize_vehicle_assignment(best)
        self._refresh_solution(best)

        log(
            f"ALNS 结束: 最优成本 {best.metrics.total_cost:.2f}, 路线 {len(best.routes)} 条, "
            f"未分配 {len(best.unassigned_units)} 个",
            indent=1,
        )
        return best

    def try_relocate(self, solution: Solution) -> bool:
        """最终精修阶段再实现。"""

        raise NotImplementedError("ALNS 版本暂不实现单独 relocate 精修。")

    def try_swap(self, solution: Solution) -> bool:
        """最终精修阶段再实现。"""

        raise NotImplementedError("ALNS 版本暂不实现单独 swap 精修。")

    def try_two_opt(self, solution: Solution) -> bool:
        """最终精修阶段再实现。"""

        raise NotImplementedError("ALNS 版本暂不实现单独 2-opt 精修。")

    def try_vehicle_reassignment(self, solution: Solution) -> bool:
        """最终精修阶段再实现。"""

        raise NotImplementedError("ALNS 版本暂不实现单独车型重分配精修。")

    def _destroy_random_removal(self, solution: Solution, remove_count: int) -> list[ServiceUnit]:
        served_unit_ids = self._served_unit_ids(solution)
        if not served_unit_ids:
            return []

        chosen_ids = self.random.sample(served_unit_ids, k=min(remove_count, len(served_unit_ids)))
        return self._remove_unit_ids(solution, chosen_ids)

    def _destroy_route_removal(self, solution: Solution, remove_count: int) -> list[ServiceUnit]:
        if not solution.routes:
            return []

        route_scores: list[tuple[float, int]] = []
        for index, route in enumerate(solution.routes):
            evaluation = solution.route_evaluations.get(route.vehicle_id) or self.route_evaluator.evaluate(route)
            unit_count = max(1, sum(len(stop.service_unit_ids) for stop in route.stops))
            route_scores.append((evaluation.cost.total_cost / unit_count, index))

        route_scores.sort(reverse=True)
        chosen_ids: list[str] = []
        for _, route_index in route_scores:
            route = solution.routes[route_index]
            for stop in route.stops:
                chosen_ids.extend(stop.service_unit_ids)
            if len(chosen_ids) >= remove_count:
                break

        return self._remove_unit_ids(solution, chosen_ids[: max(remove_count, len(chosen_ids))])

    def _destroy_related_route_removal(self, solution: Solution, remove_count: int) -> list[ServiceUnit]:
        """移除空间上相近的几条路线，让修复阶段重组局部片区。"""

        if not solution.routes:
            return []

        seed_index = self.random.randrange(len(solution.routes))
        seed_route = solution.routes[seed_index]
        scored_routes: list[tuple[float, int]] = []

        for route_index, route in enumerate(solution.routes):
            if route_index == seed_index:
                scored_routes.append((-1.0, route_index))
                continue
            scored_routes.append((self._route_distance(seed_route, route), route_index))

        scored_routes.sort(key=lambda item: (item[0], item[1]))
        chosen_ids: list[str] = []
        for _, route_index in scored_routes:
            for stop in solution.routes[route_index].stops:
                chosen_ids.extend(stop.service_unit_ids)
            if len(chosen_ids) >= remove_count:
                break

        return self._remove_unit_ids(solution, chosen_ids)

    def _destroy_worst_removal(self, solution: Solution, remove_count: int) -> list[ServiceUnit]:
        served_unit_ids = self._served_unit_ids(solution)
        if not served_unit_ids:
            return []

        sample_size = min(len(served_unit_ids), max(remove_count * 4, 25))
        sampled_ids = self.random.sample(served_unit_ids, k=sample_size)
        scored: list[tuple[float, str]] = []

        for unit_id in sampled_ids:
            contribution = self._unit_removal_contribution(solution, unit_id)
            scored.append((contribution, unit_id))

        scored.sort(reverse=True)
        chosen_ids = [unit_id for _, unit_id in scored[:remove_count]]
        return self._remove_unit_ids(solution, chosen_ids)

    def _repair_greedy_insertion(self, solution: Solution, removed_units: list[ServiceUnit]) -> None:
        pending = list(removed_units)
        while pending:
            best_move: InsertionMove | None = None
            best_unit_index = -1

            for index, unit in enumerate(pending):
                move = self._best_insertion_move(solution, unit)
                if move is None:
                    continue
                if best_move is None or move.delta_cost < best_move.delta_cost:
                    best_move = move
                    best_unit_index = index

            if best_move is None:
                solution.unassigned_units.extend(pending)
                return

            self._apply_insertion_move(solution, best_move)
            pending.pop(best_unit_index)

    def _repair_regret2_insertion(self, solution: Solution, removed_units: list[ServiceUnit]) -> None:
        pending = list(removed_units)
        while pending:
            selected_move: InsertionMove | None = None
            selected_index = -1
            best_regret = -float("inf")

            for index, unit in enumerate(pending):
                moves = self._top_insertion_moves(solution, unit, limit=2)
                if not moves:
                    continue
                first = moves[0]
                second_cost = moves[1].delta_cost if len(moves) > 1 else first.delta_cost + 10_000.0
                regret = second_cost - first.delta_cost
                if regret > best_regret:
                    best_regret = regret
                    selected_move = first
                    selected_index = index

            if selected_move is None:
                solution.unassigned_units.extend(pending)
                return

            self._apply_insertion_move(solution, selected_move)
            pending.pop(selected_index)

    def _best_insertion_move(self, solution: Solution, unit: ServiceUnit) -> InsertionMove | None:
        moves = self._top_insertion_moves(solution, unit, limit=1, allow_new_route=True)
        return moves[0] if moves else None

    def _top_insertion_moves(
        self,
        solution: Solution,
        unit: ServiceUnit,
        limit: int,
        allow_new_route: bool = True,
    ) -> list[InsertionMove]:
        moves: list[InsertionMove] = []

        for route_index, route in self._candidate_routes_for_unit(solution, unit):
            old_eval = solution.route_evaluations.get(route.vehicle_id) or self.route_evaluator.evaluate(route)
            positions = self._candidate_insert_positions(route, unit)

            for position in positions:
                new_route = self._insert_or_merge_unit(route, unit, position)
                new_route, new_eval = self._retime_route(new_route)
                if not new_eval.feasible:
                    continue
                moves.append(
                    InsertionMove(
                        unit=unit,
                        route_index=route_index,
                        insert_position=position,
                        route=new_route,
                        evaluation=new_eval,
                        delta_cost=new_eval.cost.total_cost - old_eval.cost.total_cost,
                    )
                )

        if allow_new_route:
            new_route_move = self._best_new_route_move(solution, unit)
            if new_route_move is not None:
                moves.append(new_route_move)

        moves.sort(key=lambda move: move.delta_cost)
        return moves[:limit]

    def _candidate_insert_positions(self, route: Route, unit: ServiceUnit) -> list[int]:
        for index, stop in enumerate(route.stops):
            if stop.customer_id == unit.customer_id:
                return [index]

        if len(route.stops) <= 2 * self.max_position_neighbors:
            return list(range(len(route.stops) + 1))

        ranked_stops = sorted(
            enumerate(route.stops),
            key=lambda item: self._customer_distance(unit.customer_id, item[1].customer_id),
        )
        positions: set[int] = {0, len(route.stops)}
        for stop_index, _ in ranked_stops[: self.max_position_neighbors]:
            positions.add(stop_index)
            positions.add(stop_index + 1)
        return sorted(positions)

    def _candidate_routes_for_unit(self, solution: Solution, unit: ServiceUnit) -> list[tuple[int, Route]]:
        if len(solution.routes) <= self.max_repair_routes:
            return list(enumerate(solution.routes))

        scored: list[tuple[float, int, Route]] = []
        for route_index, route in enumerate(solution.routes):
            vehicle = self.route_evaluator.vehicles[route.vehicle_id]
            route_weight = sum(stop.delivered_weight for stop in route.stops)
            route_volume = sum(stop.delivered_volume for stop in route.stops)
            if route_weight + unit.weight > vehicle.vehicle_type.max_weight + 1e-9:
                continue
            if route_volume + unit.volume > vehicle.vehicle_type.max_volume + 1e-9:
                continue

            if any(stop.customer_id == unit.customer_id for stop in route.stops):
                scored.append((-1.0, route_index, route))
                continue

            min_distance = min(
                self._customer_distance(unit.customer_id, stop.customer_id)
                for stop in route.stops
            )
            scored.append((min_distance, route_index, route))

        scored.sort(key=lambda item: (item[0], item[1]))
        return [(route_index, route) for _, route_index, route in scored[: self.max_repair_routes]]

    def _best_new_route_move(self, solution: Solution, unit: ServiceUnit) -> InsertionMove | None:
        used_vehicle_ids = {route.vehicle_id for route in solution.routes}
        unused_vehicles = [
            vehicle
            for vehicle in self.route_evaluator.vehicles.values()
            if vehicle.vehicle_id not in used_vehicle_ids
        ]
        unused_vehicles.sort(key=self._vehicle_opening_key)

        best_move: InsertionMove | None = None
        for vehicle in unused_vehicles:
            if unit.weight > vehicle.vehicle_type.max_weight + 1e-9:
                continue
            if unit.volume > vehicle.vehicle_type.max_volume + 1e-9:
                continue

            route = Route(
                vehicle_id=vehicle.vehicle_id,
                vehicle_type_id=vehicle.vehicle_type.type_id,
                departure_min=480,
                stops=[
                    RouteStop(
                        service_unit_ids=[unit.unit_id],
                        customer_id=unit.customer_id,
                        delivered_weight=unit.weight,
                        delivered_volume=unit.volume,
                    )
                ],
            )
            route, evaluation = self._retime_route(route)
            if not evaluation.feasible:
                continue

            move = InsertionMove(
                unit=unit,
                route_index=None,
                insert_position=0,
                route=route,
                evaluation=evaluation,
                delta_cost=evaluation.cost.total_cost,
            )
            if best_move is None or move.delta_cost < best_move.delta_cost:
                best_move = move

        return best_move

    def _apply_insertion_move(self, solution: Solution, move: InsertionMove) -> None:
        if move.route_index is None:
            solution.routes.append(move.route)
        else:
            solution.routes[move.route_index] = move.route
        solution.route_evaluations[move.route.vehicle_id] = move.evaluation

    def _remove_unit_ids(self, solution: Solution, unit_ids: Sequence[str]) -> list[ServiceUnit]:
        removed_units: list[ServiceUnit] = []
        seen: set[str] = set()
        for unit_id in unit_ids:
            if unit_id in seen:
                continue
            unit = self.route_evaluator.service_units.get(unit_id)
            if unit is None:
                continue
            if self._remove_unit_from_routes(solution, unit):
                removed_units.append(unit)
                seen.add(unit_id)

        self._drop_empty_routes(solution)
        self._refresh_solution(solution)
        return removed_units

    def _remove_unit_from_routes(self, solution: Solution, unit: ServiceUnit) -> bool:
        for route in solution.routes:
            for stop in route.stops:
                if unit.unit_id not in stop.service_unit_ids:
                    continue

                stop.service_unit_ids.remove(unit.unit_id)
                stop.delivered_weight -= unit.weight
                stop.delivered_volume -= unit.volume
                if not stop.service_unit_ids:
                    route.stops.remove(stop)
                return True
        return False

    def _unit_removal_contribution(self, solution: Solution, unit_id: str) -> float:
        unit = self.route_evaluator.service_units[unit_id]
        for route in solution.routes:
            if not any(unit_id in stop.service_unit_ids for stop in route.stops):
                continue

            old_eval = solution.route_evaluations.get(route.vehicle_id) or self.route_evaluator.evaluate(route)
            new_route = self._clone_route(route)
            temp_solution = Solution(routes=[new_route])
            if not self._remove_unit_from_routes(temp_solution, unit):
                return 0.0
            if not temp_solution.routes or not temp_solution.routes[0].stops:
                return old_eval.cost.total_cost

            new_route, new_eval = self._retime_route(temp_solution.routes[0])
            if not new_eval.feasible:
                return old_eval.cost.total_cost
            return old_eval.cost.total_cost - new_eval.cost.total_cost

        return 0.0

    def _insert_or_merge_unit(self, route: Route, unit: ServiceUnit, insert_position: int) -> Route:
        new_stops = [
            RouteStop(
                service_unit_ids=list(stop.service_unit_ids),
                customer_id=stop.customer_id,
                delivered_weight=stop.delivered_weight,
                delivered_volume=stop.delivered_volume,
            )
            for stop in route.stops
        ]

        for stop in new_stops:
            if stop.customer_id == unit.customer_id:
                stop.service_unit_ids.append(unit.unit_id)
                stop.delivered_weight += unit.weight
                stop.delivered_volume += unit.volume
                return Route(route.vehicle_id, route.vehicle_type_id, route.departure_min, new_stops)

        insert_position = max(0, min(insert_position, len(new_stops)))
        new_stops.insert(
            insert_position,
            RouteStop(
                service_unit_ids=[unit.unit_id],
                customer_id=unit.customer_id,
                delivered_weight=unit.weight,
                delivered_volume=unit.volume,
            ),
        )
        return Route(route.vehicle_id, route.vehicle_type_id, route.departure_min, new_stops)

    def _retime_route(self, route: Route) -> tuple[Route, RouteEvaluation]:
        candidates = self._departure_candidates(route)
        best_route = route
        best_eval = self.route_evaluator.evaluate(route)

        for departure_min in candidates:
            candidate_route = Route(route.vehicle_id, route.vehicle_type_id, departure_min, route.stops)
            evaluation = self.route_evaluator.evaluate(candidate_route)
            if not evaluation.feasible:
                continue
            if (not best_eval.feasible) or evaluation.cost.total_cost < best_eval.cost.total_cost:
                best_route = candidate_route
                best_eval = evaluation

        fine_candidates = range(max(480, best_route.departure_min - 10), best_route.departure_min + 11)
        for departure_min in fine_candidates:
            candidate_route = Route(route.vehicle_id, route.vehicle_type_id, departure_min, route.stops)
            evaluation = self.route_evaluator.evaluate(candidate_route)
            if not evaluation.feasible:
                continue
            if (not best_eval.feasible) or evaluation.cost.total_cost < best_eval.cost.total_cost:
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

    def _should_try_route_elimination(self, iteration: int) -> bool:
        if self.route_elimination_period <= 0:
            return False
        return iteration % self.route_elimination_period == 0

    def _route_elimination_pass(self, solution: Solution, max_attempts: int) -> bool:
        """尝试清空若干条较容易被吸收的路线，并只插回已有路线。"""

        if max_attempts <= 0 or len(solution.routes) <= 1:
            return False

        self._refresh_solution(solution)
        base_fitness = self._fitness(solution)
        candidate_route_indexes = sorted(
            range(len(solution.routes)),
            key=lambda index: self._route_elimination_key(solution, index),
        )

        improved = False
        for route_index in candidate_route_indexes[:max_attempts]:
            if route_index >= len(solution.routes):
                continue

            trial = self._clone_solution(solution)
            removed_route = trial.routes.pop(route_index)
            removed_units = [
                self.route_evaluator.service_units[unit_id]
                for stop in removed_route.stops
                for unit_id in stop.service_unit_ids
                if unit_id in self.route_evaluator.service_units
            ]
            trial.route_evaluations.pop(removed_route.vehicle_id, None)
            self._refresh_solution(trial)

            if not self._repair_regret2_existing_routes(trial, removed_units):
                continue

            self._refresh_solution(trial)
            trial_fitness = self._fitness(trial)
            if len(trial.unassigned_units) == 0 and trial_fitness + 1e-6 < base_fitness:
                old_routes = len(solution.routes)
                old_cost = solution.metrics.total_cost
                self._replace_solution(solution, trial)
                base_fitness = trial_fitness
                improved = True
                log(
                    f"路线消除成功: 路线 {old_routes} -> {len(solution.routes)}, "
                    f"成本 {old_cost:.2f} -> {solution.metrics.total_cost:.2f}",
                    indent=2,
                )

        return improved

    def _repair_regret2_existing_routes(self, solution: Solution, removed_units: list[ServiceUnit]) -> bool:
        pending = list(removed_units)
        while pending:
            selected_move: InsertionMove | None = None
            selected_index = -1
            best_regret = -float("inf")

            for index, unit in enumerate(pending):
                moves = self._top_insertion_moves(solution, unit, limit=2, allow_new_route=False)
                if not moves:
                    continue

                first = moves[0]
                second_cost = moves[1].delta_cost if len(moves) > 1 else first.delta_cost + 10_000.0
                regret = second_cost - first.delta_cost
                if regret > best_regret:
                    best_regret = regret
                    selected_move = first
                    selected_index = index

            if selected_move is None:
                return False

            self._apply_insertion_move(solution, selected_move)
            pending.pop(selected_index)

        return True

    def _route_elimination_key(self, solution: Solution, route_index: int) -> tuple[float, int, float, int]:
        route = solution.routes[route_index]
        vehicle = self.route_evaluator.vehicles[route.vehicle_id]
        total_weight = sum(stop.delivered_weight for stop in route.stops)
        total_volume = sum(stop.delivered_volume for stop in route.stops)
        load_ratio = max(
            total_weight / max(vehicle.vehicle_type.max_weight, 1e-9),
            total_volume / max(vehicle.vehicle_type.max_volume, 1e-9),
        )
        unit_count = sum(len(stop.service_unit_ids) for stop in route.stops)
        evaluation = solution.route_evaluations.get(route.vehicle_id) or self.route_evaluator.evaluate(route)
        return (load_ratio, unit_count, -evaluation.cost.total_cost, route_index)

    def _two_opt_pass(self, solution: Solution) -> bool:
        """对短路线做受限 2-opt，改善访问顺序和迟到/等待。"""

        if self.post_2opt_passes <= 0 or self.post_2opt_max_route_size <= 2:
            return False

        improved = False
        for pass_index in range(1, self.post_2opt_passes + 1):
            pass_improved = False
            for route_index, route in enumerate(list(solution.routes)):
                if len(route.stops) < 4 or len(route.stops) > self.post_2opt_max_route_size:
                    continue

                old_eval = solution.route_evaluations.get(route.vehicle_id) or self.route_evaluator.evaluate(route)
                best_route = route
                best_eval = old_eval

                for left in range(0, len(route.stops) - 2):
                    for right in range(left + 2, len(route.stops)):
                        candidate_stops = (
                            route.stops[:left]
                            + list(reversed(route.stops[left : right + 1]))
                            + route.stops[right + 1 :]
                        )
                        candidate_route = Route(
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
                                for stop in candidate_stops
                            ],
                        )
                        candidate_route, candidate_eval = self._retime_route(candidate_route)
                        if not candidate_eval.feasible:
                            continue
                        if candidate_eval.cost.total_cost + 1e-6 < best_eval.cost.total_cost:
                            best_route = candidate_route
                            best_eval = candidate_eval

                if best_route is not route:
                    solution.routes[route_index] = best_route
                    solution.route_evaluations[best_route.vehicle_id] = best_eval
                    pass_improved = True
                    improved = True

            if pass_improved:
                self._refresh_solution(solution)
                log(
                    f"2-opt 第 {pass_index} 轮有改进: 成本 {solution.metrics.total_cost:.2f}",
                    indent=2,
                )
            else:
                break

        return improved

    def _optimize_vehicle_assignment(self, solution: Solution) -> bool:
        """固定路线顺序，重新给路线分配更合适的车辆类型和实例。"""

        if not solution.routes:
            return False

        vehicles_by_type: dict[int, list[VehicleInstance]] = defaultdict(list)
        for vehicle in self.route_evaluator.vehicles.values():
            vehicles_by_type[vehicle.vehicle_type.type_id].append(vehicle)
        for vehicles in vehicles_by_type.values():
            vehicles.sort(key=lambda vehicle: vehicle.vehicle_id)

        route_choices: list[tuple[int, list[tuple[float, int, Route, RouteEvaluation]]]] = []
        for route_index, route in enumerate(solution.routes):
            total_weight = sum(stop.delivered_weight for stop in route.stops)
            total_volume = sum(stop.delivered_volume for stop in route.stops)
            choices: list[tuple[float, int, Route, RouteEvaluation]] = []

            for vehicle_type_id, vehicles in sorted(vehicles_by_type.items()):
                representative = vehicles[0]
                if total_weight > representative.vehicle_type.max_weight + 1e-9:
                    continue
                if total_volume > representative.vehicle_type.max_volume + 1e-9:
                    continue

                candidate_route = Route(
                    vehicle_id=representative.vehicle_id,
                    vehicle_type_id=vehicle_type_id,
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
                )
                candidate_route, candidate_eval = self._retime_route(candidate_route)
                if candidate_eval.feasible:
                    choices.append((candidate_eval.cost.total_cost, vehicle_type_id, candidate_route, candidate_eval))

            if not choices:
                return False

            choices.sort(key=lambda item: (item[0], item[1]))
            route_choices.append((route_index, choices))

        remaining_by_type = {type_id: list(vehicles) for type_id, vehicles in vehicles_by_type.items()}
        assigned_routes: list[Route | None] = [None] * len(solution.routes)
        assigned_evaluations: dict[str, RouteEvaluation] = {}
        route_order = sorted(
            route_choices,
            key=lambda item: (
                len(item[1]),
                min(choice[0] for choice in item[1]),
                item[0],
            ),
        )

        for route_index, choices in route_order:
            chosen: tuple[float, int, Route, RouteEvaluation] | None = None
            for choice in choices:
                _, vehicle_type_id, _, _ = choice
                if remaining_by_type.get(vehicle_type_id):
                    chosen = choice
                    break
            if chosen is None:
                return False

            _, vehicle_type_id, prototype_route, _ = chosen
            vehicle = remaining_by_type[vehicle_type_id].pop(0)
            route = Route(
                vehicle_id=vehicle.vehicle_id,
                vehicle_type_id=vehicle.vehicle_type.type_id,
                departure_min=prototype_route.departure_min,
                stops=[
                    RouteStop(
                        service_unit_ids=list(stop.service_unit_ids),
                        customer_id=stop.customer_id,
                        delivered_weight=stop.delivered_weight,
                        delivered_volume=stop.delivered_volume,
                    )
                    for stop in prototype_route.stops
                ],
            )
            route, evaluation = self._retime_route(route)
            if not evaluation.feasible:
                return False

            assigned_routes[route_index] = route
            assigned_evaluations[route.vehicle_id] = evaluation

        trial = Solution(
            routes=[route for route in assigned_routes if route is not None],
            unassigned_units=list(solution.unassigned_units),
            route_evaluations=assigned_evaluations,
            metrics=SolutionMetrics(),
        )
        self._refresh_solution(trial)

        if self._fitness(trial) + 1e-6 < self._fitness(solution):
            old_cost = solution.metrics.total_cost
            self._replace_solution(solution, trial)
            log(
                f"车型重分配成功: 成本 {old_cost:.2f} -> {solution.metrics.total_cost:.2f}",
                indent=2,
            )
            return True

        return False

    def _replace_solution(self, target: Solution, source: Solution) -> None:
        target.routes = [self._clone_route(route) for route in source.routes]
        target.unassigned_units = list(source.unassigned_units)
        target.route_evaluations = dict(source.route_evaluations)
        target.metrics = SolutionMetrics(
            total_cost=source.metrics.total_cost,
            total_distance_km=source.metrics.total_distance_km,
            total_energy_cost=source.metrics.total_energy_cost,
            total_carbon_cost=source.metrics.total_carbon_cost,
            total_waiting_cost=source.metrics.total_waiting_cost,
            total_late_cost=source.metrics.total_late_cost,
            used_vehicle_count=source.metrics.used_vehicle_count,
            unassigned_unit_count=source.metrics.unassigned_unit_count,
        )

    def _customer_distance(self, left_customer_id: int, right_customer_id: int) -> float:
        return self.route_evaluator.distance_matrix[left_customer_id][right_customer_id]

    def _route_distance(self, left: Route, right: Route) -> float:
        if not left.stops or not right.stops:
            return float("inf")
        return min(
            self._customer_distance(left_stop.customer_id, right_stop.customer_id)
            for left_stop in left.stops
            for right_stop in right.stops
        )

    def _refresh_solution(self, solution: Solution) -> None:
        self._drop_empty_routes(solution)
        evaluations: dict[str, RouteEvaluation] = {}
        for route in solution.routes:
            evaluations[route.vehicle_id] = self.route_evaluator.evaluate(route)
        solution.route_evaluations = evaluations
        solution.metrics = self._build_metrics(solution.routes, evaluations, solution.unassigned_units)

    def _build_metrics(
        self,
        routes: Sequence[Route],
        route_evaluations: dict[str, RouteEvaluation],
        unassigned_units: Sequence[ServiceUnit],
    ) -> SolutionMetrics:
        metrics = SolutionMetrics()
        metrics.used_vehicle_count = len(routes)
        metrics.unassigned_unit_count = len(unassigned_units)
        for route in routes:
            evaluation = route_evaluations.get(route.vehicle_id)
            if evaluation is None:
                continue
            metrics.total_cost += evaluation.cost.total_cost
            metrics.total_energy_cost += evaluation.cost.energy_cost
            metrics.total_carbon_cost += evaluation.cost.carbon_cost
            metrics.total_waiting_cost += evaluation.cost.waiting_cost
            metrics.total_late_cost += evaluation.cost.late_cost
            metrics.total_distance_km += sum(leg.distance_km for leg in evaluation.leg_records)
        return metrics

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
        )

    def _drop_empty_routes(self, solution: Solution) -> None:
        solution.routes = [route for route in solution.routes if route.stops]

    def _served_unit_ids(self, solution: Solution) -> list[str]:
        return [
            service_unit_id
            for route in solution.routes
            for stop in route.stops
            for service_unit_id in stop.service_unit_ids
        ]

    def _fitness(self, solution: Solution) -> float:
        return solution.metrics.total_cost + self.UNASSIGNED_PENALTY * len(solution.unassigned_units)

    def _draw_remove_count(self, solution: Solution) -> int:
        served_count = len(self._served_unit_ids(solution))
        if served_count <= 0:
            return 0
        ratio = self.random.uniform(self.destroy_min_ratio, self.destroy_max_ratio)
        return max(1, min(served_count, int(round(served_count * ratio))))

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

    def _weighted_choice(self, weights: dict[str, float]) -> str:
        total = sum(weights.values())
        pick = self.random.random() * total
        cumulative = 0.0
        for name, weight in weights.items():
            cumulative += weight
            if cumulative >= pick:
                return name
        return next(iter(weights))

    def _update_weights(
        self,
        weights: dict[str, float],
        scores: dict[str, float],
        counts: dict[str, int],
    ) -> None:
        for name in weights:
            average_score = scores[name] / counts[name] if counts[name] else 0.0
            weights[name] = max(0.1, self.WEIGHT_DECAY * weights[name] + (1.0 - self.WEIGHT_DECAY) * average_score)

    def _vehicle_opening_key(self, vehicle: VehicleInstance) -> tuple[float, int, str]:
        capacity_score = vehicle.vehicle_type.max_weight + 100.0 * vehicle.vehicle_type.max_volume
        return (capacity_score, vehicle.vehicle_type.type_id, vehicle.vehicle_id)
