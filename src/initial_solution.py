from __future__ import annotations

from collections.abc import Sequence

from .model import InsertionCandidate, Route, RouteStop, ServiceUnit, Solution, VehicleInstance
from .route_evaluator import RouteEvaluator


class InitialSolutionBuilder:
    """负责构造 Q1 的初始可行解。"""

    def __init__(self, route_evaluator: RouteEvaluator) -> None:
        self.route_evaluator = route_evaluator

    def build(self, service_units: Sequence[ServiceUnit], vehicles: Sequence[VehicleInstance]) -> Solution:
        """
        构造初始解的主入口。

        推荐实现流程：
        1. 先对 service unit 排序。
           常见规则：
           - 最晚到达时间早的优先
           - 需求大的优先
           - 离仓库近的优先
        2. 维护当前已经打开的路线列表。
        3. 对每个 unit，尝试插入现有路线的所有位置。
        4. 若都插不进去，就开一辆新车。
        5. 若新车也放不下，就暂时记为未分配任务。
        """

        raise NotImplementedError("请实现 Q1 初始解构造。")

    def sort_units_for_construction(self, service_units: Sequence[ServiceUnit]) -> list[ServiceUnit]:
        """
        定义初始解构造时的任务顺序。

        这里可以先写一个简单稳定的排序规则，
        后面如果你想换成 regret 插入，也不用改外层接口。
        """

        raise NotImplementedError("请实现初始构造时的任务排序规则。")

    def find_best_insertion(
        self,
        route: Route,
        service_unit: ServiceUnit,
    ) -> InsertionCandidate:
        """
        在一条给定路线里寻找最优插入位置。

        典型写法：
        1. 从位置 0 扫到 `len(route.stops)`。
        2. 每个位置都调用路线评价器做精确重算。
        3. 保存成本增量最小且可行的位置。
        """

        raise NotImplementedError("请实现单路线内的最优插入搜索。")

    def create_single_unit_route(self, service_unit: ServiceUnit, vehicle: VehicleInstance) -> Route:
        """
        用一辆车和一个服务单元创建一条新路线。

        这里先给你保留了最基础的单点路线结构，
        后面你只需要决定默认发车时刻是否固定为 08:00。

        额外提醒：
        如果 service_unit 采用订单级细粒度，
        后续真正实现初始解时要注意避免：
        - 同一辆车在同一条路线里对同一客户形成多个 stop
        - 否则会把一次客户服务错误地拆成多次停靠
        """

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
