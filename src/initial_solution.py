from __future__ import annotations

import os
from collections.abc import Sequence
from math import atan2, cos, sin

from .model import (
    InsertionCandidate,
    Route,
    RouteEvaluation,
    RouteStop,
    ServiceUnit,
    Solution,
    SolutionMetrics,
    VehicleInstance,
)
from .log_utils import log
from .route_evaluator import RouteEvaluator
from .split_dp import SplitDPBuilder


class GiantTourBuilder:
    """生成不含仓库的 ServiceUnit 全局访问顺序。"""

    def __init__(self, route_evaluator: RouteEvaluator) -> None:
        self.route_evaluator = route_evaluator

    def build_tour_pool(self, service_units: Sequence[ServiceUnit]) -> list[tuple[str, list[ServiceUnit]]]:
        """生成一组确定性的 giant tours，供初始解构造阶段择优。"""

        units = list(service_units)
        if not units:
            return []

        log(f"Giant Tour 生成启动: ServiceUnit {len(units)} 个", indent=2)
        log("生成最近邻 Giant Tour", indent=3)
        nearest_neighbor = self.nearest_neighbor_tour(units)
        log("生成 MST + DFS Giant Tour", indent=3)
        mst_dfs = self.mst_dfs_tour(units)
        tours: list[tuple[str, list[ServiceUnit]]] = [
            ("nearest_neighbor", nearest_neighbor),
            ("mst_dfs", mst_dfs),
        ]

        for offset_degree in (0.0, 90.0):
            log(f"生成角度扫描 Giant Tour: offset={offset_degree:.0f}°", indent=3)
            tours.append((f"angle_scan_{int(offset_degree)}", self.angle_scan_tour(units, offset_degree)))

        for name, tour in tours:
            log(
                f"Tour {name}: 长度 {len(tour)}, 唯一任务 {len({unit.unit_id for unit in tour})}, "
                f"首任务 {tour[0].unit_id}, 尾任务 {tour[-1].unit_id}",
                indent=3,
            )
        return tours

    def nearest_neighbor_tour(self, service_units: Sequence[ServiceUnit]) -> list[ServiceUnit]:
        """最近邻 Giant Tour：从最难安排的任务出发，每次接最近的未访问任务。"""

        unvisited = list(service_units)
        current = min(unvisited, key=self._hardness_key)
        tour = [current]
        unvisited.remove(current)

        while unvisited:
            next_unit = min(
                unvisited,
                key=lambda unit: (
                    self.graph_cost(current, unit),
                    self._hardness_key(unit),
                    unit.unit_id,
                ),
            )
            tour.append(next_unit)
            unvisited.remove(next_unit)
            current = next_unit

        return tour

    def mst_dfs_tour(self, service_units: Sequence[ServiceUnit]) -> list[ServiceUnit]:
        """MST + DFS Giant Tour：先建 ServiceUnit 相似图最小生成树，再 DFS 得到顺序。"""

        units = list(service_units)
        if len(units) <= 1:
            return units

        start = min(units, key=self._hardness_key)
        in_tree = {start.unit_id}
        adjacency: dict[str, list[str]] = {unit.unit_id: [] for unit in units}
        units_by_id = {unit.unit_id: unit for unit in units}

        while len(in_tree) < len(units):
            best_edge: tuple[float, str, str] | None = None
            for from_id in sorted(in_tree):
                from_unit = units_by_id[from_id]
                for to_unit in units:
                    if to_unit.unit_id in in_tree:
                        continue
                    edge = (self.graph_cost(from_unit, to_unit), from_id, to_unit.unit_id)
                    if best_edge is None or edge < best_edge:
                        best_edge = edge

            if best_edge is None:
                break

            _, from_id, to_id = best_edge
            adjacency[from_id].append(to_id)
            adjacency[to_id].append(from_id)
            in_tree.add(to_id)

        visited: set[str] = set()
        ordered: list[ServiceUnit] = []

        def dfs(unit_id: str) -> None:
            visited.add(unit_id)
            ordered.append(units_by_id[unit_id])
            neighbors = sorted(
                adjacency[unit_id],
                key=lambda neighbor_id: (
                    self.graph_cost(units_by_id[unit_id], units_by_id[neighbor_id]),
                    self._hardness_key(units_by_id[neighbor_id]),
                    neighbor_id,
                ),
            )
            for neighbor_id in neighbors:
                if neighbor_id not in visited:
                    dfs(neighbor_id)

        dfs(start.unit_id)

        for unit in sorted(units, key=lambda item: (self._hardness_key(item), item.unit_id)):
            if unit.unit_id not in visited:
                dfs(unit.unit_id)

        return ordered

    def angle_scan_tour(
        self,
        service_units: Sequence[ServiceUnit],
        offset_degree: float = 0.0,
    ) -> list[ServiceUnit]:
        """角度扫描 Giant Tour：按仓库为中心的旋转极角排序。"""

        offset_radian = offset_degree / 180.0 * 3.141592653589793

        def key(unit: ServiceUnit) -> tuple[float, int, int, str]:
            customer = self.route_evaluator.customers[unit.customer_id]
            rotated_x = customer.x * cos(offset_radian) - customer.y * sin(offset_radian)
            rotated_y = customer.x * sin(offset_radian) + customer.y * cos(offset_radian)
            angle = atan2(rotated_y, rotated_x)
            return (
                angle,
                unit.time_window.end_min,
                unit.customer_id,
                unit.unit_id,
            )

        return sorted(service_units, key=key)

    def graph_cost(self, left: ServiceUnit, right: ServiceUnit) -> float:
        """ServiceUnit 相似图边权，综合空间、时间窗、需求和同客户奖励。"""

        if left.unit_id == right.unit_id:
            return 0.0

        distance = self._distance(left.customer_id, right.customer_id)
        time_gap = (
            abs(left.time_window.start_min - right.time_window.start_min)
            + abs(left.time_window.end_min - right.time_window.end_min)
        ) / 60.0
        demand_gap = abs(left.weight - right.weight) / 1500.0 + abs(left.volume - right.volume) / 10.8

        cost = distance + 0.3 * time_gap + 0.05 * demand_gap
        if left.customer_id == right.customer_id:
            return min(cost, 0.0001)
        return cost

    def _distance(self, from_customer_id: int, to_customer_id: int) -> float:
        return self.route_evaluator.distance_matrix[from_customer_id][to_customer_id]

    def _hardness_key(self, unit: ServiceUnit) -> tuple[int, float, float, float, int, int, str]:
        compatible_count = sum(
            1
            for vehicle in self.route_evaluator.vehicles.values()
            if unit.weight <= vehicle.vehicle_type.max_weight + 1e-9
            and unit.volume <= vehicle.vehicle_type.max_volume + 1e-9
        )
        window_width = unit.time_window.end_min - unit.time_window.start_min
        return (
            compatible_count,
            -unit.weight,
            -unit.volume,
            window_width,
            unit.time_window.end_min,
            unit.customer_id,
            unit.unit_id,
        )

    def _deduplicate_tours(self, tours: Sequence[tuple[str, list[ServiceUnit]]]) -> list[tuple[str, list[ServiceUnit]]]:
        unique_tours: list[tuple[str, list[ServiceUnit]]] = []
        seen: set[tuple[str, ...]] = set()
        for name, tour in tours:
            signature = tuple(unit.unit_id for unit in tour)
            if signature in seen:
                continue
            seen.add(signature)
            unique_tours.append((name, tour))
        return unique_tours


class InitialSolutionBuilder:
    """构造 Q1 的稳定初始解：排序 + 最佳插入 + 必要时开新车。"""

    def __init__(self, route_evaluator: RouteEvaluator) -> None:
        self.route_evaluator = route_evaluator
        self.giant_tour_builder = GiantTourBuilder(route_evaluator=route_evaluator)
        self.split_dp_builder = SplitDPBuilder(route_evaluator=route_evaluator)

    def build(self, service_units: Sequence[ServiceUnit], vehicles: Sequence[VehicleInstance]) -> Solution:
        candidate_orders: list[tuple[str, list[ServiceUnit]]] = [
            ("hardness_sorted", self.sort_units_for_construction(service_units)),
            *self.giant_tour_builder.build_tour_pool(service_units),
        ]
        log(f"初始解候选顺序数量: {len(candidate_orders)}", indent=2)
        skip_insertion_threshold = int(os.environ.get("Q1_SKIP_INSERTION_WHEN_UNITS_GT", "300"))
        skip_insertion = len(service_units) > skip_insertion_threshold
        if skip_insertion:
            log(
                f"ServiceUnit 数量 {len(service_units)} > {skip_insertion_threshold}，"
                "跳过顺序插入候选，仅运行 Giant Tour + Split DP",
                indent=2,
            )

        best_solution: Solution | None = None
        for name, ordered_units in candidate_orders:
            if not skip_insertion:
                log(f"候选 {name}: 开始顺序插入构造", indent=2)
                insertion_solution = self._build_from_order(ordered_units, vehicles)
                self._log_solution_summary(f"{name} / insertion", insertion_solution, indent=3)
                if best_solution is None or self._solution_rank(insertion_solution) < self._solution_rank(best_solution):
                    best_solution = insertion_solution
                    log(f"当前最优更新为: {name} / insertion", indent=3)

            if name != "hardness_sorted":
                log(f"候选 {name}: 开始 Split DP 切分构造", indent=2)
                split_solution = self.split_dp_builder.build_solution(ordered_units, vehicles)
                self._log_solution_summary(f"{name} / split_dp", split_solution, indent=3)
                if best_solution is None or self._solution_rank(split_solution) < self._solution_rank(best_solution):
                    best_solution = split_solution
                    log(f"当前最优更新为: {name} / split_dp", indent=3)

        if best_solution is not None:
            self._log_solution_summary("初始解最终选择", best_solution, indent=2)
        return best_solution or Solution()

    def _build_from_order(
        self,
        service_units: Sequence[ServiceUnit],
        vehicles: Sequence[VehicleInstance],
    ) -> Solution:
        routes: list[Route] = []
        route_evaluations: dict[str, RouteEvaluation] = {}
        unassigned_units: list[ServiceUnit] = []

        unused_vehicles = self._sort_vehicles_for_opening(vehicles)

        for index, unit in enumerate(service_units, start=1):
            best_route_index: int | None = None
            best_candidate: InsertionCandidate | None = None

            for route_index, route in enumerate(routes):
                candidate = self.find_best_insertion(route, unit)
                if not candidate.feasible:
                    continue

                if best_candidate is None or candidate.delta_cost < best_candidate.delta_cost:
                    best_candidate = InsertionCandidate(
                        service_unit_id=candidate.service_unit_id,
                        route_index=route_index,
                        insert_position=candidate.insert_position,
                        delta_cost=candidate.delta_cost,
                        feasible=True,
                    )
                    best_route_index = route_index

            if best_route_index is not None and best_candidate is not None:
                updated_route = self._insert_or_merge_unit(
                    route=routes[best_route_index],
                    service_unit=unit,
                    insert_position=best_candidate.insert_position,
                )
                updated_route, evaluation = self._retime_route(updated_route)

                routes[best_route_index] = updated_route
                route_evaluations[updated_route.vehicle_id] = evaluation
                if index == 1 or index % 25 == 0 or index == len(service_units):
                    log(
                        f"顺序插入进度 {index}/{len(service_units)}: "
                        f"路线 {len(routes)} 条, 未分配 {len(unassigned_units)} 个, 剩余车辆 {len(unused_vehicles)} 辆",
                        indent=4,
                    )
                continue

            new_route_result = self._create_best_new_route(unit, unused_vehicles)
            if new_route_result is None:
                unassigned_units.append(unit)
                if index == 1 or index % 25 == 0 or index == len(service_units):
                    log(
                        f"顺序插入进度 {index}/{len(service_units)}: "
                        f"路线 {len(routes)} 条, 未分配 {len(unassigned_units)} 个, 剩余车辆 {len(unused_vehicles)} 辆",
                        indent=4,
                    )
                continue

            new_route, evaluation, used_vehicle_id = new_route_result
            routes.append(new_route)
            route_evaluations[new_route.vehicle_id] = evaluation
            unused_vehicles = [vehicle for vehicle in unused_vehicles if vehicle.vehicle_id != used_vehicle_id]

            if index == 1 or index % 25 == 0 or index == len(service_units):
                log(
                    f"顺序插入进度 {index}/{len(service_units)}: "
                    f"路线 {len(routes)} 条, 未分配 {len(unassigned_units)} 个, 剩余车辆 {len(unused_vehicles)} 辆",
                    indent=4,
                )

        return Solution(
            routes=routes,
            unassigned_units=unassigned_units,
            route_evaluations=route_evaluations,
            metrics=self._build_metrics(routes, route_evaluations, unassigned_units),
        )

    def _solution_rank(self, solution: Solution) -> tuple[int, float, int, float]:
        """择优规则：先全覆盖，再低成本，再少车辆，再短距离。"""

        return (
            solution.metrics.unassigned_unit_count,
            solution.metrics.total_cost,
            solution.metrics.used_vehicle_count,
            solution.metrics.total_distance_km,
        )

    def _log_solution_summary(self, label: str, solution: Solution, indent: int = 0) -> None:
        log(
            f"{label}: 路线 {len(solution.routes)} 条, 未分配 {len(solution.unassigned_units)} 个, "
            f"成本 {solution.metrics.total_cost:.2f}, 距离 {solution.metrics.total_distance_km:.2f} km, "
            f"等待成本 {solution.metrics.total_waiting_cost:.2f}, 迟到成本 {solution.metrics.total_late_cost:.2f}",
            indent=indent,
        )

    def sort_units_for_construction(self, service_units: Sequence[ServiceUnit]) -> list[ServiceUnit]:
        """优先安排可用车型少、需求大的任务，避免最后只剩小车装不下。"""

        def key(unit: ServiceUnit) -> tuple[int, float, float, float, int, int, str]:
            compatible_count = sum(
                1
                for vehicle in self.route_evaluator.vehicles.values()
                if unit.weight <= vehicle.vehicle_type.max_weight + 1e-9
                and unit.volume <= vehicle.vehicle_type.max_volume + 1e-9
            )
            window_width = unit.time_window.end_min - unit.time_window.start_min
            return (
                compatible_count,
                -unit.weight,
                -unit.volume,
                window_width,
                unit.time_window.end_min,
                unit.customer_id,
                unit.unit_id,
            )

        return sorted(service_units, key=key)


    def find_best_insertion(
        self,
        route: Route,
        service_unit: ServiceUnit,
    ) -> InsertionCandidate:
        """在单条路线中寻找插入或合并该 service unit 的最低增量位置。"""

        old_eval = self.route_evaluator.evaluate(route)
        if not old_eval.feasible:
            return InsertionCandidate(
                service_unit_id=service_unit.unit_id,
                route_index=-1,
                insert_position=-1,
                delta_cost=float("inf"),
                feasible=False,
                reason="原路线不可行",
            )

        vehicle = self.route_evaluator.vehicles[route.vehicle_id]
        current_weight = sum(stop.delivered_weight for stop in route.stops)
        current_volume = sum(stop.delivered_volume for stop in route.stops)

        if current_weight + service_unit.weight > vehicle.vehicle_type.max_weight + 1e-9:
            return InsertionCandidate(
                service_unit_id=service_unit.unit_id,
                route_index=-1,
                insert_position=-1,
                delta_cost=float("inf"),
                feasible=False,
                reason="插入后重量超载",
            )

        if current_volume + service_unit.volume > vehicle.vehicle_type.max_volume + 1e-9:
            return InsertionCandidate(
                service_unit_id=service_unit.unit_id,
                route_index=-1,
                insert_position=-1,
                delta_cost=float("inf"),
                feasible=False,
                reason="插入后体积超载",
            )

        # 如果同客户 stop 已经存在，则只能合并，不需要枚举位置。
        for index, stop in enumerate(route.stops):
            if stop.customer_id == service_unit.customer_id:
                merged_route = self._insert_or_merge_unit(route, service_unit, index)
                merged_route, new_eval = self._retime_route(merged_route)
                if not new_eval.feasible:
                    return InsertionCandidate(
                        service_unit_id=service_unit.unit_id,
                        route_index=-1,
                        insert_position=index,
                        delta_cost=float("inf"),
                        feasible=False,
                        reason="合并后路线不可行",
                    )

                return InsertionCandidate(
                    service_unit_id=service_unit.unit_id,
                    route_index=-1,
                    insert_position=index,
                    delta_cost=new_eval.cost.total_cost - old_eval.cost.total_cost,
                    feasible=True,
                )

        best_position = -1
        best_delta = float("inf")

        for insert_position in range(len(route.stops) + 1):
            candidate_route = self._insert_or_merge_unit(route, service_unit, insert_position)
            candidate_route, new_eval = self._retime_route(candidate_route)

            if not new_eval.feasible:
                continue

            delta = new_eval.cost.total_cost - old_eval.cost.total_cost
            if delta < best_delta:
                best_delta = delta
                best_position = insert_position

        if best_position < 0:
            return InsertionCandidate(
                service_unit_id=service_unit.unit_id,
                route_index=-1,
                insert_position=-1,
                delta_cost=float("inf"),
                feasible=False,
                reason="没有可行插入位置",
            )

        return InsertionCandidate(
            service_unit_id=service_unit.unit_id,
            route_index=-1,
            insert_position=best_position,
            delta_cost=best_delta,
            feasible=True,
        )

    def create_single_unit_route(self, service_unit: ServiceUnit, vehicle: VehicleInstance) -> Route:
        """用一辆车和一个 service unit 创建单点路线。"""

        return Route(
            vehicle_id=vehicle.vehicle_id,
            vehicle_type_id=vehicle.vehicle_type.type_id,
            departure_min=480,
            stops=[
                RouteStop(
                    service_unit_ids=[service_unit.unit_id],
                    customer_id=service_unit.customer_id,
                    delivered_weight=service_unit.weight,
                    delivered_volume=service_unit.volume,
                )
            ],
        )

    def _create_best_new_route(
        self,
        service_unit: ServiceUnit,
        unused_vehicles: Sequence[VehicleInstance],
    ) -> tuple[Route, RouteEvaluation, str] | None:
        """为一个未能插入现有路线的 unit 开新车，选择稳定的小可行车辆。"""

        best: tuple[Route, RouteEvaluation, str] | None = None

        for vehicle in unused_vehicles:
            if service_unit.weight > vehicle.vehicle_type.max_weight + 1e-9:
                continue
            if service_unit.volume > vehicle.vehicle_type.max_volume + 1e-9:
                continue

            route = self.create_single_unit_route(service_unit, vehicle)
            route, evaluation = self._retime_route(route)

            if not evaluation.feasible:
                continue

            if best is None:
                best = (route, evaluation, vehicle.vehicle_id)
                continue

            _, best_eval, best_vehicle_id = best
            current_score = self._vehicle_opening_score(vehicle, evaluation.cost.total_cost)
            best_vehicle = self.route_evaluator.vehicles[best_vehicle_id]
            best_score = self._vehicle_opening_score(best_vehicle, best_eval.cost.total_cost)

            if current_score < best_score:
                best = (route, evaluation, vehicle.vehicle_id)

        return best

    def _vehicle_opening_score(self, vehicle: VehicleInstance, route_cost: float) -> tuple[float, float, int, str]:
        """
        开新车优先用更小的可行车，避免过早占用大车。
        route_cost 作为同级容量下的细分比较项。
        """

        capacity_score = vehicle.vehicle_type.max_weight + 100.0 * vehicle.vehicle_type.max_volume
        return (
            capacity_score,
            route_cost,
            vehicle.vehicle_type.type_id,
            vehicle.vehicle_id,
        )

    def _sort_vehicles_for_opening(self, vehicles: Sequence[VehicleInstance]) -> list[VehicleInstance]:
        """车辆开线顺序：小可行车优先，车辆编号稳定排序。"""

        return sorted(
            vehicles,
            key=lambda vehicle: (
                vehicle.vehicle_type.max_weight + 100.0 * vehicle.vehicle_type.max_volume,
                vehicle.vehicle_type.type_id,
                vehicle.vehicle_id,
            ),
        )

    def _insert_or_merge_unit(
        self,
        route: Route,
        service_unit: ServiceUnit,
        insert_position: int,
    ) -> Route:
        """插入 unit；若同客户已有 stop，则合并到已有 stop。"""

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
            if stop.customer_id == service_unit.customer_id:
                stop.service_unit_ids.append(service_unit.unit_id)
                stop.delivered_weight += service_unit.weight
                stop.delivered_volume += service_unit.volume
                return Route(
                    vehicle_id=route.vehicle_id,
                    vehicle_type_id=route.vehicle_type_id,
                    departure_min=route.departure_min,
                    stops=new_stops,
                )

        insert_position = max(0, min(insert_position, len(new_stops)))
        new_stops.insert(
            insert_position,
            RouteStop(
                service_unit_ids=[service_unit.unit_id],
                customer_id=service_unit.customer_id,
                delivered_weight=service_unit.weight,
                delivered_volume=service_unit.volume,
            ),
        )

        return Route(
            vehicle_id=route.vehicle_id,
            vehicle_type_id=route.vehicle_type_id,
            departure_min=route.departure_min,
            stops=new_stops,
        )

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
            )
            evaluation = self.route_evaluator.evaluate(candidate_route)
            if not evaluation.feasible:
                continue

            if (not best_eval.feasible) or evaluation.cost.total_cost < best_eval.cost.total_cost:
                best_route = candidate_route
                best_eval = evaluation

        fine_candidates = range(
            max(480, best_route.departure_min - 10),
            best_route.departure_min + 11,
        )

        for departure_min in fine_candidates:
            candidate_route = Route(
                vehicle_id=route.vehicle_id,
                vehicle_type_id=route.vehicle_type_id,
                departure_min=departure_min,
                stops=route.stops,
            )
            evaluation = self.route_evaluator.evaluate(candidate_route)
            if not evaluation.feasible:
                continue

            if (not best_eval.feasible) or evaluation.cost.total_cost < best_eval.cost.total_cost:
                best_route = candidate_route
                best_eval = evaluation

        return best_route, best_eval

    def _departure_candidates(self, route: Route) -> list[int]:
        """构造发车时间候选集。"""

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

    def _build_metrics(
        self,
        routes: Sequence[Route],
        route_evaluations: dict[str, RouteEvaluation],
        unassigned_units: Sequence[ServiceUnit],
    ) -> SolutionMetrics:
        """汇总初始解指标。"""

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
