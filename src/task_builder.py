from __future__ import annotations

from collections.abc import Iterable, Sequence
from math import ceil

from .log_utils import log
from .model import Customer, ServiceUnit, VehicleType


class ServiceUnitBuilder:
    """
    把客户层需求压缩成 service unit。

    当前采用的口径是：
    1. 使用车型 2 作为安全容量：1500kg / 10.8m^3；
    2. 小客户直接合并成 1 个 ServiceUnit；
    3. 大客户在客户内部做二维 BFD 装箱；
    4. 普通订单不拆；
    5. 只有当单条订单没有任何车型能同时装下时，才拆 piece；
    6. 超过安全容量但可由大车承运的订单，不拆，允许单独形成大件 ServiceUnit。
    """

    SAFE_VEHICLE_TYPE_ID = 2
    EPS = 1e-9

    def build_units(
        self,
        customers: Iterable[Customer],
        vehicle_types: Sequence[VehicleType],
    ) -> list[ServiceUnit]:
        """
        构造全部 service unit。

        总体流程：
        1. 读取车型 2 的安全容量；
        2. 对每个客户单独处理，不跨客户合并；
        3. 小客户直接合并；
        4. 大客户在客户内部做 BFD；
        5. 最后做统一合法性校验。
        """
        vehicle_types = list(vehicle_types)
        if not vehicle_types:
            raise ValueError("vehicle_types 不能为空。")

        safe_weight, safe_volume = self._get_safe_capacity(vehicle_types)
        customers = list(customers)
        log(
            f"ServiceUnitBuilder 启动: 客户 {len(customers)} 个, "
            f"安全容量 {safe_weight:.1f}kg/{safe_volume:.1f}m3",
            indent=2,
        )

        service_units: list[ServiceUnit] = []
        split_customer_count = 0
        for index, customer in enumerate(customers, start=1):
            customer_units = self.split_customer_into_units(
                customer=customer,
                vehicle_types=vehicle_types,
                safe_weight=safe_weight,
                safe_volume=safe_volume,
            )
            if len(customer_units) > 1:
                split_customer_count += 1
            service_units.extend(customer_units)
            if index == 1 or index % 20 == 0 or index == len(customers):
                log(
                    f"已处理客户 {index}/{len(customers)}，累计 ServiceUnit {len(service_units)} 个",
                    indent=3,
                )

        self.validate_units(service_units=service_units, vehicle_types=vehicle_types)
        total_weight = sum(unit.weight for unit in service_units)
        total_volume = sum(unit.volume for unit in service_units)
        log(
            f"ServiceUnit 校验通过: {len(service_units)} 个, 拆分客户 {split_customer_count} 个, "
            f"总重量 {total_weight:.3f}kg, 总体积 {total_volume:.3f}m3",
            indent=2,
        )
        return service_units

    def split_customer_into_units(
        self,
        customer: Customer,
        vehicle_types: Sequence[VehicleType],
        safe_weight: float,
        safe_volume: float,
    ) -> list[ServiceUnit]:
        """
        拆分单个客户。

        规则：
        1. 若客户总需求不超过安全容量，则该客户所有订单直接合并为 1 个 unit；
        2. 若客户总需求超过安全容量，则客户内部做 BFD；
        3. 订单默认不拆；
        4. 只有当某条订单没有任何车型能承运时，才把这条订单拆成 piece。
        """
        if customer.demand_weight <= 0 and customer.demand_volume <= 0:
            return []

        orders = customer.raw_orders or []

        # 缺少订单级明细时，只能退化到客户总需求层处理
        if not orders:
            return self._split_aggregate_customer(
                customer=customer,
                vehicle_types=vehicle_types,
                safe_weight=safe_weight,
                safe_volume=safe_volume,
            )

        total_weight = sum(float(order["weight"]) for order in orders)
        total_volume = sum(float(order["volume"]) for order in orders)

        if total_weight <= safe_weight + self.EPS and total_volume <= safe_volume + self.EPS:
            unit = ServiceUnit(
                unit_id=f"C{customer.customer_id:03d}_U001",
                customer_id=customer.customer_id,
                weight=total_weight,
                volume=total_volume,
                time_window=customer.time_window,
                is_green=customer.is_green,
                source_order_ids=[str(order["order_id"]) for order in orders],
            )
            self._check_customer_total_preserved(customer=customer, units=[unit])
            return [unit]

        items: list[dict[str, object]] = []
        for order in orders:
            items.extend(self._expand_order_to_items(order=order, vehicle_types=vehicle_types))

        units = self._pack_items_for_customer(
            customer=customer,
            items=items,
            safe_weight=safe_weight,
            safe_volume=safe_volume,
        )
        self._check_customer_total_preserved(customer=customer, units=units)
        return units

    def validate_units(
        self,
        service_units: Sequence[ServiceUnit],
        vehicle_types: Sequence[VehicleType],
    ) -> None:
        """
        校验拆分结果是否合理。

        至少检查：
        1. unit_id 唯一；
        2. 重量与体积非负；
        3. 时间窗合法；
        4. 每个 unit 至少能被一种车型承运。
        """
        seen_ids: set[str] = set()

        for unit in service_units:
            if unit.unit_id in seen_ids:
                raise ValueError(f"发现重复的 unit_id: {unit.unit_id}")
            seen_ids.add(unit.unit_id)

            if unit.weight < -self.EPS:
                raise ValueError(f"service unit 出现负重量: {unit.unit_id}")

            if unit.volume < -self.EPS:
                raise ValueError(f"service unit 出现负体积: {unit.unit_id}")

            if unit.time_window.start_min > unit.time_window.end_min:
                raise ValueError(
                    f"service unit 时间窗不合法: {unit.unit_id}, "
                    f"{unit.time_window.start_min} > {unit.time_window.end_min}"
                )

            if not self._can_any_vehicle_carry(
                weight=unit.weight,
                volume=unit.volume,
                vehicle_types=vehicle_types,
            ):
                raise ValueError(
                    f"service unit 无法被任何车型承运: {unit.unit_id}, "
                    f"weight={unit.weight}, volume={unit.volume}"
                )

    def _get_safe_capacity(self, vehicle_types: Sequence[VehicleType]) -> tuple[float, float]:
        """读取车型 2 的安全容量。"""
        for vehicle_type in vehicle_types:
            if vehicle_type.type_id == self.SAFE_VEHICLE_TYPE_ID:
                return vehicle_type.max_weight, vehicle_type.max_volume
        raise ValueError("未找到车型 2，无法确定安全容量。")

    def _expand_order_to_items(
        self,
        order: dict[str, object],
        vehicle_types: Sequence[VehicleType],
    ) -> list[dict[str, object]]:
        """
        把单条订单展开成一个或多个 item。

        规则：
        1. 若存在车型能承运该订单，则该订单整体保留；
        2. 若没有任何车型能承运，才按比例拆成多个 piece。
        """
        order_id = str(order["order_id"])
        weight = float(order["weight"])
        volume = float(order["volume"])

        if weight < -self.EPS or volume < -self.EPS:
            raise ValueError(f"订单出现负重量或负体积: order_id={order_id}")

        if self._can_any_vehicle_carry(weight=weight, volume=volume, vehicle_types=vehicle_types):
            return [
                {
                    "weight": weight,
                    "volume": volume,
                    "source_order_ids": [order_id],
                }
            ]

        piece_count = self._piece_count_to_fit_any_vehicle(
            weight=weight,
            volume=volume,
            vehicle_types=vehicle_types,
        )

        items: list[dict[str, object]] = []
        piece_weight = weight / piece_count
        piece_volume = volume / piece_count
        for piece_index in range(1, piece_count + 1):
            items.append(
                {
                    "weight": piece_weight,
                    "volume": piece_volume,
                    "source_order_ids": [f"{order_id}__P{piece_index:02d}_OF_{piece_count:02d}"],
                }
            )
        return items

    def _pack_items_for_customer(
        self,
        customer: Customer,
        items: Sequence[dict[str, object]],
        safe_weight: float,
        safe_volume: float,
    ) -> list[ServiceUnit]:
        """
        在单客户内部做二维 BFD。

        规则：
        1. 先按 size_score 从大到小排序；
        2. 若 item 超过安全容量，但可由大车承运，则直接单独成一个大件 unit；
        3. 其余 item 尝试放入已有 safe bin；
        4. 若多个 bin 都能放，选放入后剩余容量最小的 bin；
        5. 若没有可放的 bin，则新建一个 bin。
        """
        sorted_items = sorted(
            items,
            key=lambda item: max(
                float(item["weight"]) / safe_weight if safe_weight > 0 else 0.0,
                float(item["volume"]) / safe_volume if safe_volume > 0 else 0.0,
            ),
            reverse=True,
        )

        bins: list[dict[str, object]] = []

        for item in sorted_items:
            item_weight = float(item["weight"])
            item_volume = float(item["volume"])
            item_sources = list(item["source_order_ids"])

            # 超安全容量但可被某种大车承运：单独成一个大件 unit
            if item_weight > safe_weight + self.EPS or item_volume > safe_volume + self.EPS:
                bins.append(
                    {
                        "weight": item_weight,
                        "volume": item_volume,
                        "source_order_ids": item_sources,
                        "safe_bin": False,
                    }
                )
                continue

            best_bin_index: int | None = None
            best_score: float | None = None

            for index, bin_state in enumerate(bins):
                if not bool(bin_state["safe_bin"]):
                    continue

                new_weight = float(bin_state["weight"]) + item_weight
                new_volume = float(bin_state["volume"]) + item_volume

                if new_weight <= safe_weight + self.EPS and new_volume <= safe_volume + self.EPS:
                    score = ((safe_weight - new_weight) / safe_weight) + (
                        (safe_volume - new_volume) / safe_volume
                    )
                    if best_score is None or score < best_score:
                        best_score = score
                        best_bin_index = index

            if best_bin_index is None:
                bins.append(
                    {
                        "weight": item_weight,
                        "volume": item_volume,
                        "source_order_ids": item_sources,
                        "safe_bin": True,
                    }
                )
            else:
                bins[best_bin_index]["weight"] = float(bins[best_bin_index]["weight"]) + item_weight
                bins[best_bin_index]["volume"] = float(bins[best_bin_index]["volume"]) + item_volume
                bins[best_bin_index]["source_order_ids"].extend(item_sources)

        units: list[ServiceUnit] = []
        for index, bin_state in enumerate(bins, start=1):
            units.append(
                ServiceUnit(
                    unit_id=f"C{customer.customer_id:03d}_U{index:03d}",
                    customer_id=customer.customer_id,
                    weight=float(bin_state["weight"]),
                    volume=float(bin_state["volume"]),
                    time_window=customer.time_window,
                    is_green=customer.is_green,
                    source_order_ids=list(bin_state["source_order_ids"]),
                )
            )
        return units

    def _split_aggregate_customer(
        self,
        customer: Customer,
        vehicle_types: Sequence[VehicleType],
        safe_weight: float,
        safe_volume: float,
    ) -> list[ServiceUnit]:
        """
        当客户没有订单级明细时，退化为按客户总需求处理。

        规则：
        1. 若总需求不超过安全容量，直接 1 个 unit；
        2. 若总需求超过安全容量但可由某种大车承运，也直接 1 个大件 unit；
        3. 只有总需求没有任何车型能承运时，才按最小 piece_count 平均拆分。
        """
        total_weight = customer.demand_weight
        total_volume = customer.demand_volume

        if total_weight <= safe_weight + self.EPS and total_volume <= safe_volume + self.EPS:
            return [
                ServiceUnit(
                    unit_id=f"C{customer.customer_id:03d}_U001",
                    customer_id=customer.customer_id,
                    weight=total_weight,
                    volume=total_volume,
                    time_window=customer.time_window,
                    is_green=customer.is_green,
                    source_order_ids=[],
                )
            ]

        if self._can_any_vehicle_carry(
            weight=total_weight,
            volume=total_volume,
            vehicle_types=vehicle_types,
        ):
            return [
                ServiceUnit(
                    unit_id=f"C{customer.customer_id:03d}_U001",
                    customer_id=customer.customer_id,
                    weight=total_weight,
                    volume=total_volume,
                    time_window=customer.time_window,
                    is_green=customer.is_green,
                    source_order_ids=[],
                )
            ]

        part_count = self._piece_count_to_fit_any_vehicle(
            weight=total_weight,
            volume=total_volume,
            vehicle_types=vehicle_types,
        )

        unit_weight = total_weight / part_count
        unit_volume = total_volume / part_count

        service_units: list[ServiceUnit] = []
        for index in range(1, part_count + 1):
            service_units.append(
                ServiceUnit(
                    unit_id=f"C{customer.customer_id:03d}_U{index:03d}",
                    customer_id=customer.customer_id,
                    weight=unit_weight,
                    volume=unit_volume,
                    time_window=customer.time_window,
                    is_green=customer.is_green,
                    source_order_ids=[],
                )
            )

        self._check_customer_total_preserved(customer=customer, units=service_units)
        return service_units

    def _can_any_vehicle_carry(
        self,
        weight: float,
        volume: float,
        vehicle_types: Sequence[VehicleType],
    ) -> bool:
        """检查是否存在至少一种车型能同时装下给定重量和体积。"""
        return any(
            weight <= vehicle_type.max_weight + self.EPS
            and volume <= vehicle_type.max_volume + self.EPS
            for vehicle_type in vehicle_types
        )

    def _piece_count_to_fit_any_vehicle(
        self,
        weight: float,
        volume: float,
        vehicle_types: Sequence[VehicleType],
    ) -> int:
        """
        计算最少要拆成多少份，才能让每一份都被至少一种车型同时装下。

        公式：
        piece_count = min over vehicle_type:
            max(
                ceil(weight / max_weight),
                ceil(volume / max_volume)
            )
        """
        if self._can_any_vehicle_carry(weight=weight, volume=volume, vehicle_types=vehicle_types):
            return 1

        candidate_piece_counts = [
            max(
                ceil(weight / vehicle_type.max_weight) if weight > 0 else 1,
                ceil(volume / vehicle_type.max_volume) if volume > 0 else 1,
            )
            for vehicle_type in vehicle_types
        ]
        return min(candidate_piece_counts)

    def _check_customer_total_preserved(
        self,
        customer: Customer,
        units: Sequence[ServiceUnit],
    ) -> None:
        """检查拆分后的总重量和总体积是否守恒。"""
        total_weight = sum(unit.weight for unit in units)
        total_volume = sum(unit.volume for unit in units)

        if abs(total_weight - customer.demand_weight) > 1e-6:
            raise ValueError(
                f"客户 {customer.customer_id} 拆分后总重量不守恒: "
                f"{total_weight} != {customer.demand_weight}"
            )

        if abs(total_volume - customer.demand_volume) > 1e-6:
            raise ValueError(
                f"客户 {customer.customer_id} 拆分后总体积不守恒: "
                f"{total_volume} != {customer.demand_volume}"
            )
