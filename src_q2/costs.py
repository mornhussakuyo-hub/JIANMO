from __future__ import annotations

from .constants import Q1Constants
from .model import ArcCostResult, TravelSegmentRecord, VehicleInstance, VehicleType


class ArcCostCalculator:
    """负责计算单条弧上的能耗、碳排放和对应成本。"""

    def __init__(self, constants: Q1Constants | None = None) -> None:
        self.constants = constants or Q1Constants()

    def fuel_consumption_per_100km(self, speed_kmh: float) -> float:
        """计算燃油车在给定速度下的百公里油耗。"""

        return (
            self.constants.fuel_fpk_a * speed_kmh * speed_kmh
            + self.constants.fuel_fpk_b * speed_kmh
            + self.constants.fuel_fpk_c
        )

    def electric_consumption_per_100km(self, speed_kmh: float) -> float:
        """计算新能源车在给定速度下的百公里电耗。"""

        return (
            self.constants.electric_epk_a * speed_kmh * speed_kmh
            + self.constants.electric_epk_b * speed_kmh
            + self.constants.electric_epk_c
        )

    def load_factor(self, vehicle: VehicleInstance, remaining_weight: float) -> float:
        """
        根据剩余载重计算载重修正因子。

        计算规则：
        1. 用 `remaining_weight / 车辆最大载重` 得到装载率。
        2. 把装载率裁剪到 [0, 1]，避免由于浮点误差或中间状态出现异常值。
        3. 如果是燃油车，用 `1 + 0.4 * 装载率`。
        4. 如果是新能源车，用 `1 + 0.35 * 装载率`。
        """
        capacity_weight = vehicle.vehicle_type.max_weight
        if capacity_weight <=0:
            raise ValueError("车辆最大载重必须为正数")
        
        load_ratio = remaining_weight / capacity_weight
        load_ratio = max(self.constants.load_ratio_lower_bound,load_ratio)
        load_ratio = min(self.constants.load_ratio_upper_bound,load_ratio)

        if vehicle.vehicle_type.energy_type == "燃油":
            return 1.0+self.constants.fuel_load_factor_alpha * load_ratio
        
        if vehicle.vehicle_type.energy_type == "新能源":
            return 1.0+self.constants.electric_load_factor_alpha *load_ratio
        
        raise ValueError(f"未知能源类型: {vehicle.vehicle_type.energy_type}")

    def evaluate_arc(
        self,
        vehicle: VehicleInstance,
        segments: list[TravelSegmentRecord],
        remaining_weight: float,
    ) -> ArcCostResult:
        """
        计算一整条弧上的成本。

        累计过程：
        1. 先根据 `remaining_weight` 算出载重修正因子。
        2. 对弧上的每个交通时段片段分别计算：
           - 该片段速度下的百公里能耗
           - 该片段真实距离上的能耗量
           - 该片段能耗成本
           - 该片段碳排放量
           - 该片段碳成本
        3. 把所有片段累加成一个 `ArcCostResult`。
        4. travel_minutes 直接由所有片段时长求和得到。
        """
        factor = self.load_factor(vehicle=vehicle,remaining_weight=remaining_weight)

        total_energy_used = 0.0
        total_carbon_emission = 0.0
        total_energy_cost = 0.0
        total_carbon_cost = 0.0
        total_travel_minutes = 0.0

        for segment in segments:
            if segment.distance_km < 0:
                raise ValueError("弧段距离不能为负数。")

            if segment.end_min < segment.start_min:
                raise ValueError("弧段结束时间不能早于开始时间。")


            distance_factor = segment.distance_km / 100.0

            if vehicle.vehicle_type.energy_type == "燃油":
                per_100km = self.fuel_consumption_per_100km(segment.speed_kmh)
                energy_used = distance_factor*per_100km*factor
                carbon_emission = energy_used *self.constants.fuel_carbon_factor
                energy_cost = energy_used *self.constants.fuel_price
            elif vehicle.vehicle_type.energy_type == "新能源":
                per_100km = self.electric_consumption_per_100km(segment.speed_kmh)
                energy_used = distance_factor*per_100km*factor
                carbon_emission = energy_used *self.constants.electric_carbon_factor
                energy_cost = energy_used *self.constants.electricity_price
            else:
                raise ValueError(f"未知能源类型: {vehicle.vehicle_type.energy_type}")
            
            carbon_cost = carbon_emission *self.constants.carbon_price
            travel_minutes = segment.end_min - segment.start_min

            total_energy_used += energy_used
            total_carbon_emission += carbon_emission
            total_energy_cost += energy_cost
            total_carbon_cost += carbon_cost
            total_travel_minutes += travel_minutes

        return ArcCostResult(
            energy_used=total_energy_used,
            carbon_emission=total_carbon_emission,
            energy_cost=total_energy_cost,
            carbon_cost=total_carbon_cost,
            travel_minutes=total_travel_minutes,
            segments=segments,
        )



    def waiting_cost(self, waiting_minutes: float) -> float:
        """把等待分钟数换算成等待成本。"""

        return waiting_minutes / self.constants.hour_to_min * self.constants.wait_cost_per_hour

    def late_cost(self, late_minutes: float) -> float:
        """把迟到分钟数换算成迟到惩罚成本。"""

        return late_minutes / self.constants.hour_to_min * self.constants.late_cost_per_hour


