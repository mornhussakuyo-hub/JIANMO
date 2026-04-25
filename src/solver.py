from __future__ import annotations

from pathlib import Path

from .constants import Q1Constants
from .costs import ArcCostCalculator
from .data_loader import Q1DataLoader
from .initial_solution import InitialSolutionBuilder
from .log_utils import log
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

        log("========== Q1 静态绿色物流调度求解开始 ==========")
        log(f"数据目录: {self.data_dir}", indent=1)

        log("步骤 1/5: 读取 cleaned_data 输入数据")
        input_data = self.load_input()
        log(
            f"读取完成: 正需求客户 {len(input_data.customers)} 个, "
            f"车型 {len(input_data.vehicle_types)} 类, 车辆实例 {len(input_data.vehicles)} 辆",
            indent=1,
        )

        log("步骤 2/5: 构造 ServiceUnit 任务块")
        service_units = self.build_service_units(input_data)
        log(f"ServiceUnit 构造完成: {len(service_units)} 个任务块", indent=1)

        log("步骤 3/5: 初始化交通模型、弧成本模型和路线评价器")
        evaluator = self.build_route_evaluator(input_data, service_units)
        log("路线评价器准备完成", indent=1)

        log("步骤 4/5: 构造初始解候选池并择优")
        initial_builder = InitialSolutionBuilder(route_evaluator=evaluator)
        solution = initial_builder.build(
            service_units=service_units,
            vehicles=input_data.vehicles,
        )
        log(
            f"初始解完成: 路线 {len(solution.routes)} 条, 未分配 {len(solution.unassigned_units)} 个, "
            f"成本 {solution.metrics.total_cost:.2f}",
            indent=1,
        )

        log("步骤 5/5: 执行局部搜索/改进器")
        local_search = LocalSearchEngine(route_evaluator=evaluator)
        solution = local_search.improve(solution)
        log(
            f"求解结束: 路线 {len(solution.routes)} 条, 未分配 {len(solution.unassigned_units)} 个, "
            f"总成本 {solution.metrics.total_cost:.2f}, 总距离 {solution.metrics.total_distance_km:.2f} km",
            indent=1,
        )
        log("========== Q1 求解结束 ==========")

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

        log("创建 TrafficProfile: 分段时变速度模型", indent=1)
        traffic_profile = TrafficProfile(constants=self.constants)
        log("创建 ArcCostCalculator: 能耗、碳排、等待、迟到成本模型", indent=1)
        arc_cost_calculator = ArcCostCalculator(constants=self.constants)
        vehicles_by_id = {vehicle.vehicle_id: vehicle for vehicle in input_data.vehicles}
        units_by_id = {unit.unit_id: unit for unit in service_units}
        log(
            f"评价器索引: vehicles_by_id={len(vehicles_by_id)}, service_units_by_id={len(units_by_id)}",
            indent=1,
        )

        return RouteEvaluator(
            customers=input_data.customers,
            vehicles=vehicles_by_id,
            service_units=units_by_id,
            distance_matrix=input_data.distance_matrix,
            traffic_profile=traffic_profile,
            arc_cost_calculator=arc_cost_calculator,
            constants=self.constants,
        )
