from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class SpeedSegment:
    """一个固定交通时段。"""

    start_min: int
    end_min: int
    speed_kmh: float
    label: str


@dataclass(slots=True)
class Q1Constants:
    """
    Q1/Q2 共用固定常量。

    注意：
    这里放的是建模阶段已经固定的参数。
    正需求客户数、Big-M、规划时域上界这类量由数据读取后运行时计算，
    不在常量表中硬编码。
    类名保留 Q1Constants，是为了让 Q2 复用 Q1 的算法接口。
    """

    time_origin: str = "08:00"
    service_start_min: int = 480
    service_time_min: int = 20
    hour_to_min: int = 60
    fallback_speed_kmh: float = 35.4

    fuel_fpk_a: float = 0.0025
    fuel_fpk_b: float = -0.2554
    fuel_fpk_c: float = 31.75

    electric_epk_a: float = 0.0014
    electric_epk_b: float = -0.12
    electric_epk_c: float = 36.19

    fuel_load_factor_alpha: float = 0.4
    electric_load_factor_alpha: float = 0.35
    load_ratio_lower_bound: float = 0.0
    load_ratio_upper_bound: float = 1.0

    fuel_price: float = 7.61
    electricity_price: float = 1.64
    fuel_carbon_factor: float = 2.547
    electric_carbon_factor: float = 0.501
    carbon_price: float = 0.65

    startup_cost: float = 400.0
    wait_cost_per_hour: float = 20.0
    late_cost_per_hour: float = 50.0

    speed_segments: list[SpeedSegment] = field(
        default_factory=lambda: [
            SpeedSegment(480, 540, 9.8, "C"),
            SpeedSegment(540, 600, 55.3, "S"),
            SpeedSegment(600, 690, 35.4, "N"),
            SpeedSegment(690, 780, 9.8, "C"),
            SpeedSegment(780, 900, 55.3, "S"),
            SpeedSegment(900, 1020, 35.4, "N"),
        ]
    )

    def relative_hours_from_minute(self, minute_of_day: int) -> float:
        """把绝对分钟转成相对 08:00 的小时数。"""

        return (minute_of_day - self.service_start_min) / self.hour_to_min

    def minute_of_day_from_relative_hours(self, t_hour: float) -> float:
        """把相对 08:00 的小时数转回绝对分钟。"""

        return self.service_start_min + self.hour_to_min * t_hour


@dataclass(slots=True)
class RuntimeBounds:
    """
    运行时派生边界。

    planning_horizon_min:
        规划时间上界，至少要覆盖最晚服务时间、服务时长、返仓时间和允许迟到的缓冲。
    big_m_time_min:
        时间传播约束里使用的 Big-M。
    big_m_order:
        MTZ 子回路消除里使用的顺序上界，通常等于有效客户数。
    """

    planning_horizon_min: int
    big_m_time_min: int
    big_m_order: int
