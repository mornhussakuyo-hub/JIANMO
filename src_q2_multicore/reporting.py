from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .model import Route, RouteEvaluation, Solution
from .route_evaluator import RouteEvaluator
from .solution_utils import evaluation_for
from .validator import SolutionValidator


class Q2ReportBuilder:
    """把 Q2 求解结果整理成可交付文件。

    输出重点：
    1. 总体 KPI
    2. 车辆使用汇总
    3. 路线总览
    4. 路线弧段明细
    5. 路线客户停靠明细
    6. 客户层服务完成情况
    7. 绿色准入政策校验
    8. 最终可行性校验
    """

    def __init__(self, route_evaluator: RouteEvaluator) -> None:
        self.route_evaluator = route_evaluator

    def build_summary_dict(self, solution: Solution) -> dict[str, Any]:
        validator = SolutionValidator(route_evaluator=self.route_evaluator)
        validation = validator.validate(solution)

        route_rows = self._build_route_rows(solution)
        arc_rows = self._build_arc_rows(solution)
        stop_rows = self._build_stop_rows(solution)
        customer_rows = self._build_customer_service_rows(solution)
        vehicle_rows = self._build_vehicle_usage_rows(solution)
        policy_rows = self._build_green_policy_rows(solution)

        return {
            "metadata": {
                "problem": "Q2",
                "scenario": "q2_green_access_policy",
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "customer_count": len(self.route_evaluator.customers),
                "service_unit_count": len(self.route_evaluator.service_units),
                "vehicle_count": len(self.route_evaluator.vehicles),
                "green_policy_enabled": self.route_evaluator.green_policy_enabled,
                "green_policy_start_min": self.route_evaluator.green_policy_start_min,
                "green_policy_end_min": self.route_evaluator.green_policy_end_min,
            },
            "kpi": self._build_kpi(solution),
            "vehicle_usage": vehicle_rows,
            "routes": route_rows,
            "route_arcs": arc_rows,
            "route_stops": stop_rows,
            "customer_service": customer_rows,
            "green_policy_service": policy_rows,
            "unassigned_units": self._build_unassigned_rows(solution),
            "validation": validation,
        }

    def write_json(self, solution: Solution, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.build_summary_dict(solution)
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def write_all(self, solution: Solution, output_dir: Path) -> dict[str, Path]:
        """写出完整 Q2 结果文件，并返回文件路径。"""

        output_dir.mkdir(parents=True, exist_ok=True)
        payload = self.build_summary_dict(solution)

        paths = {
            "json": output_dir / "q2_solution.json",
            "kpi_csv": output_dir / "q2_kpi.csv",
            "routes_csv": output_dir / "q2_routes.csv",
            "route_arcs_csv": output_dir / "q2_route_arcs.csv",
            "route_stops_csv": output_dir / "q2_route_stops.csv",
            "customer_service_csv": output_dir / "q2_customer_service.csv",
            "green_policy_csv": output_dir / "q2_green_policy_service.csv",
            "vehicle_usage_csv": output_dir / "q2_vehicle_usage.csv",
            "report_md": output_dir / "q2_report.md",
        }

        paths["json"].write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._write_csv(paths["kpi_csv"], [payload["kpi"]])
        self._write_csv(paths["routes_csv"], payload["routes"])
        self._write_csv(paths["route_arcs_csv"], payload["route_arcs"])
        self._write_csv(paths["route_stops_csv"], payload["route_stops"])
        self._write_csv(paths["customer_service_csv"], payload["customer_service"])
        self._write_csv(paths["green_policy_csv"], payload["green_policy_service"])
        self._write_csv(paths["vehicle_usage_csv"], payload["vehicle_usage"])
        paths["report_md"].write_text(self._build_markdown(payload), encoding="utf-8")
        return paths

    def _build_kpi(self, solution: Solution) -> dict[str, Any]:
        unique_vehicle_type_by_id = {
            route.vehicle_id: route.vehicle_type_id
            for route in solution.routes
        }
        used_vehicle_ids = sorted(unique_vehicle_type_by_id)
        startup_cost = 0.0
        for vehicle_id in used_vehicle_ids:
            vehicle = self.route_evaluator.vehicles.get(vehicle_id)
            if vehicle is not None:
                startup_cost += vehicle.vehicle_type.startup_cost

        return {
            "policy_enabled": self.route_evaluator.green_policy_enabled,
            "green_policy_start_min": self.route_evaluator.green_policy_start_min,
            "green_policy_end_min": self.route_evaluator.green_policy_end_min,
            "total_cost": round(solution.metrics.total_cost, 6),
            "total_distance_km": round(solution.metrics.total_distance_km, 6),
            "startup_cost_unique_vehicle": round(startup_cost, 6),
            "total_energy_cost": round(solution.metrics.total_energy_cost, 6),
            "total_carbon_cost": round(solution.metrics.total_carbon_cost, 6),
            "total_waiting_cost": round(solution.metrics.total_waiting_cost, 6),
            "total_late_cost": round(solution.metrics.total_late_cost, 6),
            "route_count": len(solution.routes),
            "used_vehicle_count": solution.metrics.used_vehicle_count,
            "served_service_units": sum(
                len(stop.service_unit_ids)
                for route in solution.routes
                for stop in route.stops
            ),
            "unassigned_unit_count": solution.metrics.unassigned_unit_count,
            "late_stop_count": self._late_stop_count(solution),
            "wait_stop_count": self._wait_stop_count(solution),
            "green_violation_count": self._green_violation_count(solution),
            "green_fuel_service_count": self._green_service_count(solution, energy_type="燃油"),
            "green_new_energy_service_count": self._green_service_count(solution, energy_type="新能源"),
            "vehicle_type_route_count": dict(Counter(route.vehicle_type_id for route in solution.routes)),
            "vehicle_type_used_count": dict(Counter(unique_vehicle_type_by_id.values())),
        }

    def _build_route_rows(self, solution: Solution) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for index, route in enumerate(solution.routes, start=1):
            evaluation = self._evaluation(solution, route, index)
            vehicle = self.route_evaluator.vehicles.get(route.vehicle_id)
            unit_ids = [unit_id for stop in route.stops for unit_id in stop.service_unit_ids]
            rows.append(
                {
                    "route_id": route.route_id,
                    "route_seq": index,
                    "vehicle_id": route.vehicle_id,
                    "vehicle_instance_id": route.vehicle_id,
                    "vehicle_type_id": route.vehicle_type_id,
                    "energy_type": vehicle.vehicle_type.energy_type if vehicle else "",
                    "departure_min": route.departure_min,
                    "departure_time": self._format_min(route.departure_min),
                    "return_to_depot_min": self._round_or_none(evaluation.return_to_depot_min),
                    "return_to_depot_time": self._format_min(evaluation.return_to_depot_min),
                    "stop_count": len(route.stops),
                    "service_unit_count": len(unit_ids),
                    "customer_sequence": "->".join(str(stop.customer_id) for stop in route.stops),
                    "service_unit_ids": unit_ids,
                    "total_weight": round(sum(stop.delivered_weight for stop in route.stops), 6),
                    "total_volume": round(sum(stop.delivered_volume for stop in route.stops), 6),
                    "distance_km": round(sum(leg.distance_km for leg in evaluation.leg_records), 6),
                    "route_total_cost_with_startup": round(evaluation.cost.total_cost, 6),
                    "energy_cost": round(evaluation.cost.energy_cost, 6),
                    "carbon_cost": round(evaluation.cost.carbon_cost, 6),
                    "waiting_cost": round(evaluation.cost.waiting_cost, 6),
                    "late_cost": round(evaluation.cost.late_cost, 6),
                    "feasible": evaluation.feasible,
                    "violations": evaluation.violations,
                }
            )
        return rows

    def _build_arc_rows(self, solution: Solution) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for route_index, route in enumerate(solution.routes, start=1):
            evaluation = self._evaluation(solution, route, route_index)
            for arc_seq, leg in enumerate(evaluation.leg_records, start=1):
                rows.append(
                    {
                        "route_id": route.route_id,
                        "vehicle_id": route.vehicle_id,
                        "vehicle_instance_id": route.vehicle_id,
                        "vehicle_type_id": route.vehicle_type_id,
                        "energy_type": self._route_energy_type(route),
                        "arc_seq": arc_seq,
                        "from_node": leg.from_node,
                        "to_node": leg.to_node,
                        "to_is_green": self._node_is_green(leg.to_node),
                        "green_access_violation": self._leg_violates_green_policy(route, leg.to_node, leg.arrival_min),
                        "depart_min": round(leg.depart_min, 6),
                        "depart_time": self._format_min(leg.depart_min),
                        "arrival_min": round(leg.arrival_min, 6),
                        "arrival_time": self._format_min(leg.arrival_min),
                        "service_start_min": round(leg.service_start_min, 6),
                        "service_start_time": self._format_min(leg.service_start_min),
                        "leave_min": round(leg.leave_min, 6),
                        "leave_time": self._format_min(leg.leave_min),
                        "travel_minutes": round(leg.travel_minutes, 6),
                        "distance_km": round(leg.distance_km, 6),
                        "waiting_minutes": round(leg.waiting_minutes, 6),
                        "late_minutes": round(leg.late_minutes, 6),
                        "remaining_weight_after_service": round(leg.remaining_weight_after_service, 6),
                        "remaining_volume_after_service": round(leg.remaining_volume_after_service, 6),
                        "energy_cost": round(leg.energy_cost, 6),
                        "carbon_cost": round(leg.carbon_cost, 6),
                        "traffic_segments": [
                            {
                                "start_min": round(segment.start_min, 6),
                                "end_min": round(segment.end_min, 6),
                                "speed_kmh": round(segment.speed_kmh, 6),
                                "distance_km": round(segment.distance_km, 6),
                                "period_label": segment.period_label,
                            }
                            for segment in leg.segments
                        ],
                    }
                )
        return rows

    def _build_stop_rows(self, solution: Solution) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for route_index, route in enumerate(solution.routes, start=1):
            evaluation = self._evaluation(solution, route, route_index)
            customer_legs = [leg for leg in evaluation.leg_records if leg.to_node != 0]
            for stop_seq, stop in enumerate(route.stops, start=1):
                customer = self.route_evaluator.customers[stop.customer_id]
                leg = customer_legs[stop_seq - 1] if stop_seq - 1 < len(customer_legs) else None
                rows.append(
                    {
                        "route_id": route.route_id,
                        "vehicle_id": route.vehicle_id,
                        "vehicle_instance_id": route.vehicle_id,
                        "vehicle_type_id": route.vehicle_type_id,
                        "energy_type": self._route_energy_type(route),
                        "stop_seq": stop_seq,
                        "customer_id": stop.customer_id,
                        "is_green": customer.is_green,
                        "service_unit_ids": list(stop.service_unit_ids),
                        "delivered_weight": round(stop.delivered_weight, 6),
                        "delivered_volume": round(stop.delivered_volume, 6),
                        "customer_tw_start": customer.time_window.start_min,
                        "customer_tw_start_time": self._format_min(customer.time_window.start_min),
                        "customer_tw_end": customer.time_window.end_min,
                        "customer_tw_end_time": self._format_min(customer.time_window.end_min),
                        "arrival_min": self._round_or_none(leg.arrival_min if leg else None),
                        "arrival_time": self._format_min(leg.arrival_min if leg else None),
                        "service_start_min": self._round_or_none(leg.service_start_min if leg else None),
                        "service_start_time": self._format_min(leg.service_start_min if leg else None),
                        "leave_min": self._round_or_none(leg.leave_min if leg else None),
                        "leave_time": self._format_min(leg.leave_min if leg else None),
                        "waiting_minutes": self._round_or_none(leg.waiting_minutes if leg else None),
                        "late_minutes": self._round_or_none(leg.late_minutes if leg else None),
                        "green_access_violation": (
                            self._leg_violates_green_policy(route, stop.customer_id, leg.arrival_min)
                            if leg else False
                        ),
                    }
                )
        return rows

    def _build_customer_service_rows(self, solution: Solution) -> list[dict[str, Any]]:
        delivered: dict[int, dict[str, Any]] = defaultdict(
            lambda: {
                "delivered_weight": 0.0,
                "delivered_volume": 0.0,
                "served_route_ids": set(),
                "served_vehicle_ids": set(),
                "served_unit_ids": [],
            }
        )

        for route in solution.routes:
            for stop in route.stops:
                bucket = delivered[stop.customer_id]
                bucket["delivered_weight"] += stop.delivered_weight
                bucket["delivered_volume"] += stop.delivered_volume
                bucket["served_route_ids"].add(route.route_id)
                bucket["served_vehicle_ids"].add(route.vehicle_id)
                bucket["served_unit_ids"].extend(stop.service_unit_ids)

        rows: list[dict[str, Any]] = []
        for customer_id, customer in sorted(self.route_evaluator.customers.items()):
            bucket = delivered[customer_id]
            weight_ratio = self._safe_ratio(bucket["delivered_weight"], customer.demand_weight)
            volume_ratio = self._safe_ratio(bucket["delivered_volume"], customer.demand_volume)
            rows.append(
                {
                    "customer_id": customer_id,
                    "is_green": customer.is_green,
                    "total_demand_weight": round(customer.demand_weight, 6),
                    "total_demand_volume": round(customer.demand_volume, 6),
                    "delivered_weight": round(bucket["delivered_weight"], 6),
                    "delivered_volume": round(bucket["delivered_volume"], 6),
                    "weight_ratio": round(weight_ratio, 8),
                    "volume_ratio": round(volume_ratio, 8),
                    "served_route_ids": sorted(bucket["served_route_ids"]),
                    "served_vehicle_ids": sorted(bucket["served_vehicle_ids"]),
                    "served_unit_ids": bucket["served_unit_ids"],
                    "is_fully_served": (
                        abs(bucket["delivered_weight"] - customer.demand_weight) <= 1e-5
                        and abs(bucket["delivered_volume"] - customer.demand_volume) <= 1e-5
                    ),
                }
            )
        return rows

    def _build_green_policy_rows(self, solution: Solution) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for route_index, route in enumerate(solution.routes, start=1):
            evaluation = self._evaluation(solution, route, route_index)
            vehicle = self.route_evaluator.vehicles.get(route.vehicle_id)
            if vehicle is None:
                continue
            customer_legs = [leg for leg in evaluation.leg_records if leg.to_node != 0]
            for stop_seq, stop in enumerate(route.stops, start=1):
                customer = self.route_evaluator.customers[stop.customer_id]
                if not customer.is_green:
                    continue
                leg = customer_legs[stop_seq - 1] if stop_seq - 1 < len(customer_legs) else None
                arrival_min = leg.arrival_min if leg else None
                rows.append(
                    {
                        "route_id": route.route_id,
                        "vehicle_instance_id": route.vehicle_id,
                        "vehicle_type_id": route.vehicle_type_id,
                        "energy_type": vehicle.vehicle_type.energy_type,
                        "stop_seq": stop_seq,
                        "customer_id": stop.customer_id,
                        "arrival_min": self._round_or_none(arrival_min),
                        "arrival_time": self._format_min(arrival_min),
                        "green_access_violation": (
                            self._leg_violates_green_policy(route, stop.customer_id, arrival_min)
                            if arrival_min is not None else False
                        ),
                        "delivered_weight": round(stop.delivered_weight, 6),
                        "delivered_volume": round(stop.delivered_volume, 6),
                        "service_unit_ids": list(stop.service_unit_ids),
                    }
                )
        return rows

    def _build_vehicle_usage_rows(self, solution: Solution) -> list[dict[str, Any]]:
        grouped: dict[str, list[tuple[Route, RouteEvaluation]]] = defaultdict(list)
        for index, route in enumerate(solution.routes, start=1):
            grouped[route.vehicle_id].append((route, self._evaluation(solution, route, index)))

        rows: list[dict[str, Any]] = []
        for vehicle_id, pairs in sorted(grouped.items()):
            vehicle = self.route_evaluator.vehicles[vehicle_id]
            first_depart = min(route.departure_min for route, _ in pairs)
            last_return = max(
                evaluation.return_to_depot_min or route.departure_min
                for route, evaluation in pairs
            )
            rows.append(
                {
                    "vehicle_id": vehicle_id,
                    "vehicle_type_id": vehicle.vehicle_type.type_id,
                    "energy_type": vehicle.vehicle_type.energy_type,
                    "max_weight": vehicle.vehicle_type.max_weight,
                    "max_volume": vehicle.vehicle_type.max_volume,
                    "route_count": len(pairs),
                    "first_depart_min": round(first_depart, 6),
                    "first_depart_time": self._format_min(first_depart),
                    "last_return_min": round(last_return, 6),
                    "last_return_time": self._format_min(last_return),
                    "total_distance_km": round(sum(sum(leg.distance_km for leg in ev.leg_records) for _, ev in pairs), 6),
                    "total_energy_cost": round(sum(ev.cost.energy_cost for _, ev in pairs), 6),
                    "total_carbon_cost": round(sum(ev.cost.carbon_cost for _, ev in pairs), 6),
                    "total_waiting_cost": round(sum(ev.cost.waiting_cost for _, ev in pairs), 6),
                    "total_late_cost": round(sum(ev.cost.late_cost for _, ev in pairs), 6),
                    "startup_cost": vehicle.vehicle_type.startup_cost,
                    "route_ids": [route.route_id for route, _ in sorted(pairs, key=lambda item: item[0].departure_min)],
                }
            )
        return rows

    def _build_unassigned_rows(self, solution: Solution) -> list[dict[str, Any]]:
        return [
            {
                "unit_id": unit.unit_id,
                "customer_id": unit.customer_id,
                "weight": round(unit.weight, 6),
                "volume": round(unit.volume, 6),
                "time_window_start": unit.time_window.start_min,
                "time_window_end": unit.time_window.end_min,
                "source_order_ids": unit.source_order_ids,
            }
            for unit in solution.unassigned_units
        ]

    def _evaluation(self, solution: Solution, route: Route, index: int) -> RouteEvaluation:
        evaluation = evaluation_for(solution.route_evaluations, route, index)
        if evaluation is not None:
            return evaluation
        return self.route_evaluator.evaluate(route)

    def _build_markdown(self, payload: dict[str, Any]) -> str:
        kpi = payload["kpi"]
        validation = payload["validation"]
        lines: list[str] = []
        lines.append("# Q2 绿色准入约束配送方案")
        lines.append("")
        lines.append("## 1. 总体 KPI")
        lines.append("")
        lines.append(f"- 绿色准入政策启用：{'是' if kpi['policy_enabled'] else '否'}")
        lines.append(
            f"- 燃油车绿色区禁入到达区间："
            f"{self._format_min(kpi['green_policy_start_min'])} - {self._format_min(kpi['green_policy_end_min'])}"
        )
        lines.append(f"- 总成本：{kpi['total_cost']:.2f} 元")
        lines.append(f"- 路线数：{kpi['route_count']} 条")
        lines.append(f"- 实际使用车辆数：{kpi['used_vehicle_count']} 辆")
        lines.append(f"- 总距离：{kpi['total_distance_km']:.2f} km")
        lines.append(f"- 能耗成本：{kpi['total_energy_cost']:.2f} 元")
        lines.append(f"- 碳成本：{kpi['total_carbon_cost']:.2f} 元")
        lines.append(f"- 等待成本：{kpi['total_waiting_cost']:.2f} 元")
        lines.append(f"- 迟到成本：{kpi['total_late_cost']:.2f} 元")
        lines.append(f"- 未分配任务数：{kpi['unassigned_unit_count']}")
        lines.append(f"- 绿色准入违约次数：{kpi['green_violation_count']}")
        lines.append(f"- 绿色区燃油车服务次数：{kpi['green_fuel_service_count']}")
        lines.append(f"- 绿色区新能源车服务次数：{kpi['green_new_energy_service_count']}")
        lines.append("")
        lines.append("## 2. 车辆使用情况")
        lines.append("")
        lines.append("| 车辆 | 车型 | 能源 | 趟数 | 首次出发 | 最晚返回 | 距离/km | 路线 |")
        lines.append("|---|---:|---|---:|---|---|---:|---|")
        for row in payload["vehicle_usage"]:
            lines.append(
                f"| {row['vehicle_id']} | {row['vehicle_type_id']} | {row['energy_type']} | "
                f"{row['route_count']} | {row['first_depart_time']} | {row['last_return_time']} | "
                f"{row['total_distance_km']:.2f} | {', '.join(row['route_ids'])} |"
            )
        lines.append("")
        lines.append("## 3. 路线总览")
        lines.append("")
        lines.append("| 路线 | 车辆 | 车型 | 出发 | 返回 | 客户序列 | 距离/km | 路线成本/元 |")
        lines.append("|---|---|---:|---|---|---|---:|---:|")
        for row in payload["routes"]:
            lines.append(
                f"| {row['route_id']} | {row['vehicle_id']} | {row['vehicle_type_id']} | "
                f"{row['departure_time']} | {row['return_to_depot_time']} | "
                f"{row['customer_sequence']} | {row['distance_km']:.2f} | {row['route_total_cost_with_startup']:.2f} |"
            )
        lines.append("")
        lines.append("## 4. 校验结果")
        lines.append("")
        lines.append(f"- 是否通过校验：{'是' if validation['ok'] else '否'}")
        lines.append(f"- 已服务任务数：{validation['served_unit_count']}")
        lines.append(f"- 缺失任务数：{len(validation['missing_unit_ids'])}")
        lines.append(f"- 重复任务数：{len(validation['duplicate_unit_ids'])}")
        if validation["errors"]:
            lines.append("")
            lines.append("### 错误")
            for error in validation["errors"][:100]:
                lines.append(f"- {error}")
        if validation["warnings"]:
            lines.append("")
            lines.append("### 警告")
            for warning in validation["warnings"][:100]:
                lines.append(f"- {warning}")
        lines.append("")
        lines.append("## 5. 文件说明")
        lines.append("")
        lines.append("- `q2_route_arcs.csv`：正式路线弧段表，含真实出发/到达/服务/离开时刻。")
        lines.append("- `q2_route_stops.csv`：每条路线的客户停靠与配送量。")
        lines.append("- `q2_green_policy_service.csv`：绿色区服务与准入校验明细。")
        lines.append("- `q2_customer_service.csv`：客户层服务完成情况。")
        lines.append("- `q2_vehicle_usage.csv`：车辆复用与车辆成本汇总。")
        return "\n".join(lines)

    def _green_violation_count(self, solution: Solution) -> int:
        return sum(
            1
            for route_index, route in enumerate(solution.routes, start=1)
            for leg in self._evaluation(solution, route, route_index).leg_records
            if self._leg_violates_green_policy(route, leg.to_node, leg.arrival_min)
        )

    def _green_service_count(self, solution: Solution, energy_type: str) -> int:
        count = 0
        for route in solution.routes:
            if self._route_energy_type(route) != energy_type:
                continue
            for stop in route.stops:
                customer = self.route_evaluator.customers[stop.customer_id]
                if customer.is_green:
                    count += 1
        return count

    def _late_stop_count(self, solution: Solution) -> int:
        return sum(
            1
            for route_index, route in enumerate(solution.routes, start=1)
            for leg in self._evaluation(solution, route, route_index).leg_records
            if leg.to_node != 0 and leg.late_minutes > 1e-9
        )

    def _wait_stop_count(self, solution: Solution) -> int:
        return sum(
            1
            for route_index, route in enumerate(solution.routes, start=1)
            for leg in self._evaluation(solution, route, route_index).leg_records
            if leg.to_node != 0 and leg.waiting_minutes > 1e-9
        )

    def _leg_violates_green_policy(self, route: Route, to_node: int, arrival_min: float) -> bool:
        if not self.route_evaluator.green_policy_enabled:
            return False
        if to_node == 0 or not self._node_is_green(to_node):
            return False
        if self._route_energy_type(route) != "燃油":
            return False
        return self.route_evaluator.green_policy_start_min <= arrival_min < self.route_evaluator.green_policy_end_min

    def _node_is_green(self, node_id: int) -> bool:
        customer = self.route_evaluator.customers.get(node_id)
        return bool(customer and customer.is_green)

    def _route_energy_type(self, route: Route) -> str:
        vehicle = self.route_evaluator.vehicles.get(route.vehicle_id)
        return vehicle.vehicle_type.energy_type if vehicle else ""

    @staticmethod
    def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not rows:
            path.write_text("", encoding="utf-8-sig")
            return
        fieldnames: list[str] = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
        with path.open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: Q2ReportBuilder._csv_value(row.get(key)) for key in fieldnames})

    @staticmethod
    def _csv_value(value: Any) -> Any:
        if isinstance(value, (list, dict, tuple, set)):
            return json.dumps(value, ensure_ascii=False)
        return value

    @staticmethod
    def _format_min(value: float | int | None) -> str:
        if value is None:
            return ""
        total_seconds = int(round(float(value) * 60))
        total_seconds %= 24 * 3600
        hour = total_seconds // 3600
        minute = (total_seconds % 3600) // 60
        second = total_seconds % 60
        return f"{hour:02d}:{minute:02d}:{second:02d}"

    @staticmethod
    def _round_or_none(value: float | int | None) -> float | None:
        if value is None:
            return None
        return round(float(value), 6)

    @staticmethod
    def _safe_ratio(numerator: float, denominator: float) -> float:
        if abs(denominator) <= 1e-12:
            return 1.0 if abs(numerator) <= 1e-12 else float("inf")
        return numerator / denominator


Q1ReportBuilder = Q2ReportBuilder
