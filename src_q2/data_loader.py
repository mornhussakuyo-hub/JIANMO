from __future__ import annotations

import csv
import json
from pathlib import Path

from .constants import Q1Constants, RuntimeBounds
from .log_utils import log
from .model import Customer, DistanceMatrix, Q1InputData, TimeWindow, VehicleInstance, VehicleType


class Q1DataLoader:
    """读取 Q1/Q2 共用的 cleaned_data 输入文件，并转成程序内部对象。"""

    def __init__(self, data_dir: Path, constants: Q1Constants | None = None) -> None:
        self.data_dir = data_dir
        self.constants = constants or Q1Constants()

    def load(self) -> Q1InputData:
        """
        一次性加载调度求解需要的基础输入。

        读取内容包括：
        1. customers.json
        2. vehicles.json
        3. distance_matrix.csv

        返回统一的 Q1InputData 对象；类名沿用 Q1，Q2 继续复用该数据结构。
        """

        customers = self.load_customers()
        vehicle_types = self.load_vehicle_types()
        vehicles = self.build_vehicle_instances(vehicle_types)
        distance_matrix = self.load_distance_matrix()

        self.validate_distance_matrix(customers,distance_matrix)
        log("距离矩阵覆盖性校验通过", indent=2)

        return Q1InputData(
            customers=customers,
            vehicle_types=vehicle_types,
            vehicles=vehicles,
            distance_matrix=distance_matrix,
            data_dir=self.data_dir,
        )

    def load_customers(self) -> dict[int, Customer]:
        """
        读取 customers.json，并聚合成客户层对象。

        处理逻辑：
        1. 读取每个客户的订单列表
        2. 聚合总重量、总体积
        3. 只保留正需求客户
        4. 解析共享时间窗
        5. 保留 raw_orders，供后续拆 service unit 使用
        """

        file_path = self.data_dir / "customers.json"
        log(f"读取客户文件: {file_path}", indent=2)
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        customers: dict[int, Customer] = {}

        for row in payload:
            customer_id = int(row["guest_id"])

            orders = row.get("orders",[])

            total_weight = sum(float(order["weight"]) for order in orders)
            total_volume = sum(float(order["volume"]) for order in orders)
            if total_weight <= 0 and total_volume <= 0:
                continue

            time_window = self._parse_customer_time_window(row)
            
            # 兼容数据清洗阶段的字段误拼写：location / loaction。
            location = row.get("location") or row.get("loaction") or {}
            customers[customer_id] = Customer(
                customer_id=customer_id,
                x=float(location.get("x", 0.0)),
                y=float(location.get("y", 0.0)),
                demand_weight=total_weight,
                demand_volume=total_volume,
                time_window=time_window,
                is_green=bool(row.get("if_in_green_area")),
                raw_orders=orders,
            )

        raw_order_count = sum(len(customer.raw_orders) for customer in customers.values())
        log(
            f"客户读取完成: 原始客户 {len(payload)} 行, 正需求客户 {len(customers)} 个, "
            f"订单 {raw_order_count} 条",
            indent=2,
        )
        return customers

    def load_vehicle_types(self) -> dict[int, VehicleType]:
        """
        读取 vehicles.json，构造车型对象字典。

        返回：
        `vehicle_types[type_id] = VehicleType(...)`
        """

        file_path = self.data_dir / "vehicles.json"
        log(f"读取车型文件: {file_path}", indent=2)
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        vehicle_types: dict[int, VehicleType] = {}

        for row in payload:
            type_id = int(row["k"])
            vehicle_types[type_id] = VehicleType(
                type_id=type_id,
                energy_type=str(row["energy_type"]),
                max_weight=float(row["max_weight"]),
                max_volume=float(row["max_volume"]),
                available_count=int(row["available_count"]),
                startup_cost=float(row["startup_cost"]),
            )

        log(f"车型读取完成: {len(vehicle_types)} 类", indent=2)
        for vehicle_type in vehicle_types.values():
            log(
                f"车型 {vehicle_type.type_id}: {vehicle_type.energy_type}, "
                f"{vehicle_type.max_weight}kg/{vehicle_type.max_volume}m3, "
                f"数量 {vehicle_type.available_count}, 启动成本 {vehicle_type.startup_cost}",
                indent=3,
            )
        return vehicle_types

    def build_vehicle_instances(self, vehicle_types: dict[int, VehicleType]) -> list[VehicleInstance]:
        """
        把车型按可用数量展开成具体车辆实例。

        例如：
        车型 1 有 60 辆，就展开成：
        T1_001, T1_002, ..., T1_060
        """

        log("展开车型为具体车辆实例", indent=2)
        vehicles: list[VehicleInstance] = []
        for vehicle_type in vehicle_types.values():
            for index in range(1, vehicle_type.available_count + 1):
                vehicles.append(
                    VehicleInstance(
                        vehicle_id=f"T{vehicle_type.type_id}_{index:03d}",
                        vehicle_type=vehicle_type,
                    )
                )
        log(f"车辆实例展开完成: {len(vehicles)} 辆", indent=2)
        return vehicles

    def load_distance_matrix(self) -> DistanceMatrix:
        """
        读取距离矩阵 CSV。

        存储结构：
        distance_matrix[from_node][to_node] = 距离
        """

        file_path = self.data_dir / "distance_matrix.csv"
        log(f"读取距离矩阵: {file_path}", indent=2)

        distance_matrix: DistanceMatrix = {}

        with file_path.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.reader(file)
            rows = list(reader)

        if not rows:
            raise ValueError("distance_matrix.csv 为空。")



        header = rows[0]

        if len(header)<2:
            raise ValueError("distance_matrix.csv 表头格式不正确。")
        
        node_ids = [int(value) for value in header[1:] if value != ""]

        for row in rows[1:]:
            if not row:
                continue

            from_node = int(row[0])
            distance_matrix[from_node] = {}
            for to_node, value in zip(node_ids, row[1:]):
                if value == "":
                    continue
                distance_matrix[from_node][to_node] = float(value)
        arc_count = sum(len(row) for row in distance_matrix.values())
        log(f"距离矩阵读取完成: {len(distance_matrix)} 个起点行, {arc_count} 条弧距离", indent=2)
        return distance_matrix

    def derive_runtime_bounds(self, input_data: Q1InputData) -> RuntimeBounds:
        """
        根据当前数据计算规划时域上界和 Big-M。

        这里采用保守的运行时边界估计：

        1. 找到所有客户中最晚的时间窗结束时刻
        2. 加上固定服务时间 20 分钟
        3. 再加一个固定返仓缓冲，例如 120 分钟
        4. 最终不允许超过当天 24:00
        5. Big-M 时间边界在此基础上再放大一些
        """
        if not input_data.customers:
            raise ValueError("没有正需求客户，无法计算运行时边界。")

        latest_window_end = max(
            customer.time_window.end_min for customer in input_data.customers.values()
        )

        service_time = self.constants.service_time_min

        # 给一个固定返仓缓冲，不按最慢速度逐弧精算。
        return_buffer_min = 120

        planning_horizon_min = latest_window_end + service_time + return_buffer_min

        # 最晚只允许到当天 24:00。
        end_of_day_min = 24 * 60
        planning_horizon_min = min(planning_horizon_min, end_of_day_min)

        # Big-M 只要明显大于规划时域即可，避免过度放大。
        big_m_time_min = planning_horizon_min + 180

        # 顺序 Big-M 直接取正需求客户数。
        big_m_order = len(input_data.customers)

        return RuntimeBounds(
            planning_horizon_min=planning_horizon_min,
            big_m_time_min=big_m_time_min,
            big_m_order=big_m_order,
        )

        

    def _parse_customer_time_window(self, row: dict[str, object]) -> TimeWindow:
        """
        解析客户共享时间窗。

        当前 cleaned_data 里同一客户的所有订单共用同一个时间窗，
        所以这里直接取第一条订单里的 early / late 即可。
        """

        orders = row.get("orders", [])
        if not orders:
            raise ValueError("正需求客户缺少订单时间窗数据。")

        early = str(orders[0]["early"])
        late = str(orders[0]["late"]) 
    
        return TimeWindow(
            start_min=self._hhmm_to_minute_of_day(early),
            end_min=self._hhmm_to_minute_of_day(late),
        )

    @staticmethod
    def _hhmm_to_minute_of_day(hhmm: str) -> int:
        """把 `HH:MM` 转成当天绝对分钟。"""

        hour_text, minute_text = hhmm.split(":")
        return int(hour_text) * 60 + int(minute_text)


    def validate_distance_matrix(
        self,
        customers: dict[int, Customer],
        distance_matrix: DistanceMatrix,
    ) -> None:
        """
        校验距离矩阵是否覆盖调度求解需要的所有节点。

        至少需要：
        1. 仓库节点 0
        2. 所有正需求客户节点
        """
        required_nodes = {0, *customers.keys()}

        missing_rows = [node for node in required_nodes if node not in distance_matrix]
        if missing_rows:
            raise ValueError(f"距离矩阵缺少这些起点行: {missing_rows}")

        for from_node in required_nodes:
            missing_cols = [to_node for to_node in required_nodes if to_node not in distance_matrix[from_node]]
            if missing_cols:
                raise ValueError(
                    f"距离矩阵在起点 {from_node} 这一行中缺少这些终点: {missing_cols}"
                )
