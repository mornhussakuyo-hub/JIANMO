from __future__ import annotations

from pathlib import Path

from .constants import Q1Constants
from .costs import ArcCostCalculator
from .data_loader import Q1DataLoader
from .initial_solution import InitialSolutionBuilder
from .local_search import LocalSearchEngine
from .model import Q1InputData, ServiceUnit, Solution
from .route_evaluator import RouteEvaluator
from .task_builder import ServiceUnitBuilder
from .traffic import TrafficProfile


class Q1Solver:
    """Q1 总调度器，把各模块串起来。"""

    def __init__(self, data_dir: Path, constants: Q1Constants | None = None) -> None:
        self.data_dir = data_dir
        self.constants = constants or Q1Constants()

    def solve(self) -> Solution:
        """
        Q1 总流程入口。

        推荐你最终按这个流程实现：
        1. 读取输入数据
        2. 计算运行时边界
        3. 构造 service units
        4. 初始化交通模型和成本计算器
        5. 创建路线评价器
        6. 先构造初始解
        7. 再做局部搜索或 ALNS
        8. 最后汇总指标并输出解
        """

        input_data = self.load_input()
        service_units = self.build_service_units(input_data)
        evaluator = self.build_route_evaluator(input_data, service_units)

        initial_builder = InitialSolutionBuilder(route_evaluator=evaluator)
        solution = initial_builder.build(
            service_units=service_units,
            vehicles=input_data.vehicles,
        )

        local_search = LocalSearchEngine(route_evaluator=evaluator)
        solution = local_search.improve(solution)

        # 这里后面建议补一个“解层指标汇总”步骤：
        # 1. 把每条路线重新评价一遍
        # 2. 累加总成本、总距离、总等待、总迟到
        # 3. 统计用了多少辆车、还有多少未分配任务
        # 4. 写入 solution.metrics
        return solution

    def load_input(self) -> Q1InputData:
        """读取 cleaned_data 中的输入文件。"""

        loader = Q1DataLoader(data_dir=self.data_dir, constants=self.constants)
        return loader.load()

    def build_service_units(self, input_data: Q1InputData) -> list[ServiceUnit]:
        """把客户需求拆成求解器真正操作的 service unit。"""

        builder = ServiceUnitBuilder()
        return builder.build_units(
            customers=input_data.customers.values(),
            vehicle_types=list(input_data.vehicle_types.values()),
        )

    def build_route_evaluator(
        self,
        input_data: Q1InputData,
        service_units: list[ServiceUnit],
    ) -> RouteEvaluator:
        """创建所有构造和搜索阶段共用的路线评价器。"""

        traffic_profile = TrafficProfile(constants=self.constants)
        arc_cost_calculator = ArcCostCalculator(constants=self.constants)
        vehicles_by_id = {vehicle.vehicle_id: vehicle for vehicle in input_data.vehicles}
        units_by_id = {unit.unit_id: unit for unit in service_units}

        return RouteEvaluator(
            customers=input_data.customers,
            vehicles=vehicles_by_id,
            service_units=units_by_id,
            distance_matrix=input_data.distance_matrix,
            traffic_profile=traffic_profile,
            arc_cost_calculator=arc_cost_calculator,
            constants=self.constants,
        )

