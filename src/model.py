from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeAlias


DistanceMatrix: TypeAlias = dict[int, dict[int, float]]


@dataclass(slots=True)
class TimeWindow:
    """客户时间窗，统一用当天绝对分钟表示。"""

    start_min: int# 最早可开始服务的时刻，单位是当天绝对分钟
    end_min: int# 最晚允许到达或开始服务的时刻，单位是当天绝对分钟


@dataclass(slots=True)
class Customer:
    """客户层需求对象。Q1 主模型就是围绕它组织的。"""

    customer_id: int  # 客户编号，对应题目中的客户 ID
    x: float # 客户横坐标，单位 km
    y: float # 客户纵坐标，单位 km
    demand_weight: float  # 该客户聚合后的总重量需求，单位 kg
    demand_volume: float  # 该客户聚合后的总体积需求，单位 m^3
    time_window: TimeWindow # 该客户共享的时间窗
    is_green: bool  # 该客户是否位于绿色配送区
    raw_orders: list[dict[str, Any]] = field(default_factory=list)  # 该客户原始订单明细，供拆分 service unit 或调试使用


@dataclass(slots=True)
class VehicleType:
    """车型定义。一个车型后面会展开出多辆具体车辆。"""

    type_id: int  # 车型编号，例如 1~5
    energy_type: str  # 能源类型，通常是“燃油”或“新能源”
    max_weight: float  # 该车型最大载重，单位 kg
    max_volume: float  # 该车型最大容积，单位 m^3
    available_count: int  # 该车型可用车辆数量
    startup_cost: float  # 启动一辆该车型车辆的固定成本，单位元


@dataclass(slots=True)
class VehicleInstance:
    """具体车辆实例。后续路线会绑定到具体车。"""

    vehicle_id: str  # 具体车辆编号，例如 T1_001
    vehicle_type: VehicleType  # 这辆车所属的车型对象


@dataclass(slots=True)
class ServiceUnit:
    """
    启发式求解用的离散任务块。

    数学模型是客户层可拆分配送，
    实际程序里为了方便插入、交换、局部搜索，
    通常会先把客户需求拆成多个可执行 service unit。

    当前项目更推荐保留订单级细粒度：
    - 一个订单通常对应一个 service unit
    - 只有超单车容量订单才继续拆 piece
    """

    unit_id: str
    customer_id: int
    weight: float
    volume: float
    time_window: TimeWindow
    is_green: bool
    source_order_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RouteStop:
    """
    路线中的一个停靠点。

    一个 stop 可以合并同一客户的多个 service unit。
    这样同一辆车给同一客户配送多批任务时，路线层只访问一次客户，
    服务时间也只计算一次。
    """

    service_unit_ids: list[str]
    customer_id: int
    delivered_weight: float
    delivered_volume: float


@dataclass(slots=True)
class TravelSegmentRecord:
    """
    一条弧在某个交通时段内完成的那一小段记录。

    因为一条路可能横跨多个交通时段，
    所以路线评价时不能只算一次速度，
    而要切成多个片段分别累计。
    """

    start_min: float
    end_min: float
    speed_kmh: float
    distance_km: float
    period_label: str


@dataclass(slots=True)
class ArcCostResult:
    """单条弧的成本计算结果。"""

    energy_used: float
    carbon_emission: float
    energy_cost: float
    carbon_cost: float
    travel_minutes: float
    segments: list[TravelSegmentRecord] = field(default_factory=list)


@dataclass(slots=True)
class CostBreakdown:
    """路线或解的成本拆分。"""

    startup_cost: float = 0.0
    energy_cost: float = 0.0
    carbon_cost: float = 0.0
    waiting_cost: float = 0.0
    late_cost: float = 0.0

    @property
    def total_cost(self) -> float:
        return (
            self.startup_cost
            + self.energy_cost
            + self.carbon_cost
            + self.waiting_cost
            + self.late_cost
        )


@dataclass(slots=True)
class RouteLegRecord:
    """路线中一段完整行驶和服务过程的详细记录。"""

    from_node: int
    to_node: int
    depart_min: float
    arrival_min: float
    service_start_min: float
    leave_min: float
    travel_minutes: float
    distance_km: float
    waiting_minutes: float
    late_minutes: float
    remaining_weight_after_service: float
    remaining_volume_after_service: float
    energy_cost: float
    carbon_cost: float
    segments: list[TravelSegmentRecord] = field(default_factory=list)


@dataclass(slots=True)
class Route:
    """一辆车对应的一条路线。"""

    vehicle_id: str
    vehicle_type_id: int
    departure_min: int
    stops: list[RouteStop] = field(default_factory=list)


@dataclass(slots=True)
class RouteEvaluation:
    """路线评价器返回的完整结果。"""

    feasible: bool
    cost: CostBreakdown
    leg_records: list[RouteLegRecord] = field(default_factory=list)
    return_to_depot_min: float | None = None
    violations: list[str] = field(default_factory=list)


@dataclass(slots=True)
class InsertionCandidate:
    """一个候选插入动作。"""

    service_unit_id: str
    route_index: int
    insert_position: int
    delta_cost: float
    feasible: bool
    reason: str = ""


@dataclass(slots=True)
class SolutionMetrics:
    """解层面的汇总指标。"""

    total_cost: float = 0.0
    total_distance_km: float = 0.0
    total_energy_cost: float = 0.0
    total_carbon_cost: float = 0.0
    total_waiting_cost: float = 0.0
    total_late_cost: float = 0.0
    used_vehicle_count: int = 0
    unassigned_unit_count: int = 0


@dataclass(slots=True)
class Solution:
    """Q1 最终解对象。"""

    routes: list[Route] = field(default_factory=list)
    unassigned_units: list[ServiceUnit] = field(default_factory=list)
    route_evaluations: dict[str, RouteEvaluation] = field(default_factory=dict)
    metrics: SolutionMetrics = field(default_factory=SolutionMetrics)


@dataclass(slots=True)
class Q1InputData:
    """Q1 输入数据的统一内存表示。"""

    customers: dict[int, Customer]
    vehicle_types: dict[int, VehicleType]
    vehicles: list[VehicleInstance]
    distance_matrix: DistanceMatrix
    data_dir: Path
