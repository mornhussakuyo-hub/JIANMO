from __future__ import annotations

from .constants import Q1Constants
from .costs import ArcCostCalculator
from .model import CostBreakdown, Customer, DistanceMatrix, Route, RouteStop, RouteEvaluation, ServiceUnit, VehicleInstance, RouteLegRecord
from .traffic import TrafficProfile


class RouteEvaluator:
    """
    Q2 路线评价器。

    它的职责是：
    1. 对一条完整路线做精确成本计算
    2. 做容量、时间、返仓和绿色准入等一致性检查
    3. 给初始解构造和局部搜索提供统一的“打分器”
    """

    def __init__(
        self,
        customers: dict[int, Customer],
        vehicles: dict[str, VehicleInstance],
        service_units: dict[str, ServiceUnit],
        distance_matrix: DistanceMatrix,
        traffic_profile: TrafficProfile,
        arc_cost_calculator: ArcCostCalculator,
        constants: Q1Constants | None = None,
        green_policy_enabled: bool = False,
        green_policy_start_min: int = 480,
        green_policy_end_min: int = 960,
    ) -> None:
        self.customers = customers
        self.vehicles = vehicles
        self.service_units = service_units
        self.distance_matrix = distance_matrix
        self.traffic_profile = traffic_profile
        self.arc_cost_calculator = arc_cost_calculator
        self.constants = constants or Q1Constants()
        self.green_policy_enabled = green_policy_enabled
        self.green_policy_start_min = green_policy_start_min
        self.green_policy_end_min = green_policy_end_min

    def evaluate(self, route: Route) -> RouteEvaluation:
        """
        精确评价一条完整路线。

        计算流程：
        1. 找到具体车辆
        2. 统计路线初始总载重、总体积
        3. 检查初始是否超载
        4. 从仓库出发，逐个 stop 传播：
           - 距离
           - 分段交通
           - 行驶时间
           - 能耗和碳成本
           - 到达时刻
           - 等待时间
           - 迟到时间
           - 服务结束时刻
           - 更新剩余载重和剩余体积
        5. 最后计算返仓弧
        6. 汇总成本和可行性
        """
        vehicle = self.vehicles[route.vehicle_id]

        cost = self._empty_cost()

        cost.startup_cost=vehicle.vehicle_type.startup_cost

        violations:list[str]=[]
        leg_records:list[RouteLegRecord]=[]

        total_weight = sum(stop.delivered_weight for stop in route.stops)
        total_volume = sum(stop.delivered_volume for stop in route.stops)

        if total_weight > vehicle.vehicle_type.max_weight + 1e-9:
            violations.append(
                f"初始总重量超载: {total_weight:.6f} > {vehicle.vehicle_type.max_weight:.6f}"
            )
        
        if total_volume > vehicle.vehicle_type.max_volume + 1e-9:
            violations.append(
                f"初始总体积超载: {total_volume:.6f} > {vehicle.vehicle_type.max_volume:.6f}"
            )

        remaining_weight = total_weight
        remaining_volume = total_volume

        current_node =0 
        current_min = float(route.departure_min)

        for stop in route.stops:
            stop_units: list[ServiceUnit] = []
            if not stop.service_unit_ids:
                violations.append(f"stop 缺少 service_unit_ids: customer_id={stop.customer_id}")
            for service_unit_id in stop.service_unit_ids:
                service_unit = self.service_units.get(service_unit_id)
                if service_unit is None:
                    violations.append(f"未知 service_unit_id: {service_unit_id}")
                    continue
                stop_units.append(service_unit)

            customer = self.customers[stop.customer_id]

            for service_unit in stop_units:
                if stop.customer_id != service_unit.customer_id:
                    violations.append(
                        f"stop.customer_id 与 service_unit.customer_id 不一致: "
                        f"{stop.customer_id} != {service_unit.customer_id}"
                    )
            
            if stop.customer_id != customer.customer_id:
                violations.append(
                    f"stop.customer_id 与 customer.customer_id 不一致: "
                    f"{stop.customer_id} != {customer.customer_id}"
                )
            
            if stop.delivered_weight < -1e-9:
                violations.append(f"出现负配送重量: {stop.delivered_weight:.6f}")

            if stop.delivered_volume < -1e-9:
                violations.append(f"出现负配送体积: {stop.delivered_volume:.6f}")

            expected_weight = sum(unit.weight for unit in stop_units)
            expected_volume = sum(unit.volume for unit in stop_units)
            if abs(stop.delivered_weight - expected_weight) > 1e-6:
                violations.append(
                    f"stop 配送重量与 service units 汇总不一致: "
                    f"{stop.delivered_weight:.6f} != {expected_weight:.6f}"
                )

            if abs(stop.delivered_volume - expected_volume) > 1e-6:
                violations.append(
                    f"stop 配送体积与 service units 汇总不一致: "
                    f"{stop.delivered_volume:.6f} != {expected_volume:.6f}"
                )
            


            try:
                distance_km = self._distance(current_node,stop.customer_id)
            except KeyError:
                violations.append(f"距离矩阵缺失: {current_node} -> {stop.customer_id}")
                return RouteEvaluation(
                    feasible=False,
                    cost=cost,
                    leg_records=leg_records,
                    return_to_depot_min=None,
                    violations=violations,
                )
            
            segments = self.traffic_profile.travel_segments(
                distance_km=distance_km,
                depart_min=current_min,
            )

            arc_result = self.arc_cost_calculator.evaluate_arc(
                vehicle=vehicle,
                segments=segments,
                remaining_weight=remaining_weight,
            )  

            arrival_min = current_min + arc_result.travel_minutes

            if self._violates_green_access_policy(vehicle, customer, arrival_min):
                violations.append(
                    "绿色准入违约: "
                    f"燃油车 {route.vehicle_id} 于 {arrival_min:.2f}min "
                    f"到达绿色区客户 {customer.customer_id}，落入禁入区间 "
                    f"[{self.green_policy_start_min}, {self.green_policy_end_min})"
                )

            # 早到产生等待成本。
            service_start_min = max(arrival_min,float(customer.time_window.start_min))
            waiting_minutes = max(0.0,float(customer.time_window.start_min)-arrival_min)

            # 晚到产生迟到惩罚成本。
            late_minutes = max(0.0, arrival_min - float(customer.time_window.end_min))

            # 服务结束时刻 = 开始服务时刻 + 固定服务时间。
            leave_min = service_start_min +self.constants.service_time_min

            cost.energy_cost += arc_result.energy_cost
            cost.carbon_cost += arc_result.carbon_cost
            cost.waiting_cost += self.arc_cost_calculator.waiting_cost(waiting_minutes)
            cost.late_cost += self.arc_cost_calculator.late_cost(late_minutes)
            
            remaining_weight -= stop.delivered_weight
            remaining_volume -= stop.delivered_volume

            if remaining_weight < -1e-9:
                violations.append(
                    f"出现负剩余重量，说明卸货量超过当前载货量: {remaining_weight:.6f}"
                )

            if remaining_volume < -1e-9:
                violations.append(
                    f"出现负剩余体积，说明卸货体积超过当前载货体积: {remaining_volume:.6f}"
                )
            
            leg_records.append(
                RouteLegRecord(
                    from_node=current_node,
                    to_node=stop.customer_id,
                    depart_min=current_min,
                    arrival_min=arrival_min,
                    service_start_min=service_start_min,
                    leave_min=leave_min,
                    travel_minutes=arc_result.travel_minutes,
                    distance_km=distance_km,
                    waiting_minutes=waiting_minutes,
                    late_minutes=late_minutes,
                    remaining_weight_after_service=remaining_weight,
                    remaining_volume_after_service=remaining_volume,
                    energy_cost=arc_result.energy_cost,
                    carbon_cost=arc_result.carbon_cost,
                    segments=arc_result.segments,
                )
            )
            current_node = stop.customer_id
            current_min = leave_min

        return_to_depot_min:float|None = None
        if route.stops:
            if abs(remaining_weight) > 1e-6:
                violations.append(f"返仓前剩余重量不为 0: {remaining_weight:.6f}")

            if abs(remaining_volume) > 1e-6:
                violations.append(f"返仓前剩余体积不为 0: {remaining_volume:.6f}")
            
            try:
                back_distance_km = self._distance(current_node, 0)
            except KeyError:
                violations.append(f"距离矩阵缺失: {current_node} -> 0")
                return RouteEvaluation(
                    feasible=False,
                    cost=cost,
                    leg_records=leg_records,
                    return_to_depot_min=None,
                    violations=violations,
                )

            back_segments = self.traffic_profile.travel_segments(
                distance_km=back_distance_km,
                depart_min=current_min,
            )

            back_arc_result = self.arc_cost_calculator.evaluate_arc(
                vehicle=vehicle,
                segments=back_segments,
                remaining_weight=remaining_weight,
            )

            cost.energy_cost += back_arc_result.energy_cost
            cost.carbon_cost += back_arc_result.carbon_cost
            return_to_depot_min = current_min + back_arc_result.travel_minutes


            leg_records.append(
                RouteLegRecord(
                    from_node=current_node,
                    to_node=0,
                    depart_min=current_min,
                    arrival_min=return_to_depot_min,
                    service_start_min=return_to_depot_min,
                    leave_min=return_to_depot_min,
                    travel_minutes=back_arc_result.travel_minutes,
                    distance_km=back_distance_km,
                    waiting_minutes=0.0,
                    late_minutes=0.0,
                    remaining_weight_after_service=remaining_weight,
                    remaining_volume_after_service=remaining_volume,
                    energy_cost=back_arc_result.energy_cost,
                    carbon_cost=back_arc_result.carbon_cost,
                    segments=back_arc_result.segments,
                )
            )
        else:
            # 如果是一条空路线，那么它没有真正行驶，返仓时刻就等于出发时刻
            return_to_depot_min = float(route.departure_min)

        feasible = len(violations) == 0

        return RouteEvaluation(
            feasible=feasible,
            cost=cost,
            leg_records=leg_records,
            return_to_depot_min=return_to_depot_min,
            violations=violations,
        )

    def evaluate_insertion_delta(
        self,
        route: Route,
        service_unit: ServiceUnit,
        insert_position: int,
    ) -> float:
        """
        精确计算插入一个任务块后的成本增量。

        实现方法：
        1. 先评价原路线
        2. 构造插入后的新路线
        3. 再评价新路线
        4. 如果新路线不可行，则返回正无穷
        5. 否则返回新旧总成本之差
        """
        old_eval = self.evaluate(route)
        
        if not old_eval.feasible:
            return float("inf")

        new_stops = self._add_unit_to_stops(
            stops=route.stops,
            service_unit=service_unit,
            insert_position=insert_position,
        )

        new_route = Route(
            vehicle_id=route.vehicle_id,
            vehicle_type_id=route.vehicle_type_id,
            departure_min=route.departure_min,
            stops=new_stops,
        )

        new_eval=self.evaluate(new_route)

        if not new_eval.feasible:
            return float("inf")
        

        return new_eval.cost.total_cost - old_eval.cost.total_cost
    

    def _distance(self, from_node: int, to_node: int) -> float:
        """读取两点之间的距离。"""

        return self.distance_matrix[from_node][to_node]

    def _add_unit_to_stops(
        self,
        stops: list[RouteStop],
        service_unit: ServiceUnit,
        insert_position: int,
    ) -> list[RouteStop]:
        """把 service unit 插入路线；若同客户已存在，则合并到已有停靠点。"""

        new_stops = [
            RouteStop(
                service_unit_ids=list(stop.service_unit_ids),
                customer_id=stop.customer_id,
                delivered_weight=stop.delivered_weight,
                delivered_volume=stop.delivered_volume,
            )
            for stop in stops
        ]

        for stop in new_stops:
            if stop.customer_id == service_unit.customer_id:
                stop.service_unit_ids.append(service_unit.unit_id)
                stop.delivered_weight += service_unit.weight
                stop.delivered_volume += service_unit.volume
                return new_stops

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
        return new_stops

    def _empty_cost(self) -> CostBreakdown:
        """创建一个空成本对象，方便后续累加。"""

        return CostBreakdown()

    def _violates_green_access_policy(
        self,
        vehicle: VehicleInstance,
        customer: Customer,
        arrival_min: float,
    ) -> bool:
        if not self.green_policy_enabled:
            return False
        if vehicle.vehicle_type.energy_type != "燃油":
            return False
        if not customer.is_green:
            return False
        return self.green_policy_start_min <= arrival_min < self.green_policy_end_min
