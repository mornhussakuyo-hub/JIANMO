from __future__ import annotations

import csv
import json
import math
import os
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from .constants import Q1Constants
from .costs import ArcCostCalculator
from .data_loader import Q1DataLoader
from .log_utils import log
from .model import Customer, Q1InputData, Route, RouteStop, ServiceUnit, Solution, TimeWindow
from .route_evaluator import RouteEvaluator
from .solution_utils import build_solution_metrics, evaluation_for
from .task_builder import ServiceUnitBuilder
from .traffic import TrafficProfile
from .validator import SolutionValidator


@dataclass(slots=True)
class Q3CaseResult:
    event_id: str
    event_type: str
    event_time_min: float
    status: str
    validation_ok: bool
    route_count: int
    used_vehicle_count: int
    total_cost: float
    total_distance_km: float
    energy_cost: float
    carbon_cost: float
    waiting_cost: float
    late_cost: float
    frozen_unit_count: int
    residual_unit_count: int
    added_route_count: int
    removed_route_count: int
    changed_assignment_count: int
    arc_disruption_count: int
    disruption_proxy: float
    notes: list[str]
    validation_errors: list[str]
    validation_warnings: list[str]
    routes: list[dict[str, Any]]
    stops: list[dict[str, Any]]


class Q3DynamicSolver:
    """Q3 动态重优化入口：按事件切片 Q1 计划，再做保守残余修复。"""

    def __init__(
        self,
        data_dir: Path,
        q1_run_dir: Path,
        events_path: Path,
        output_dir: Path,
        constants: Q1Constants | None = None,
    ) -> None:
        self.data_dir = data_dir
        self.q1_run_dir = q1_run_dir
        self.events_path = events_path
        self.output_dir = output_dir
        self.constants = constants or Q1Constants()

    def solve_all(self) -> list[Q3CaseResult]:
        log("========== Q3 动态重优化求解开始 ==========")
        log(f"数据目录: {self.data_dir}", indent=1)
        log(f"Q1 基准输出目录: {self.q1_run_dir}", indent=1)
        log(f"事件文件: {self.events_path}", indent=1)

        events = self._load_events()
        workers = int(os.environ.get("Q3_PARALLEL_WORKERS", "1") or "1")
        if workers > 1:
            log(f"事件级并行开启: workers={workers}", indent=1)
            payloads = [
                (
                    str(self.data_dir),
                    str(self.q1_run_dir),
                    str(self.events_path),
                    event,
                )
                for event in events
            ]
            with ProcessPoolExecutor(max_workers=workers) as executor:
                results = list(executor.map(_solve_event_case_worker, payloads))
        else:
            results = [
                solve_event_case(
                    data_dir=self.data_dir,
                    q1_run_dir=self.q1_run_dir,
                    event=event,
                    constants=self.constants,
                )
                for event in events
            ]

        results.sort(key=lambda item: (item.event_time_min, item.event_id))
        self._write_outputs(results)
        ok_count = sum(1 for item in results if item.validation_ok)
        log(f"Q3 求解完成: {ok_count}/{len(results)} 个事件场景通过校验", indent=1)
        log(f"输出目录: {self.output_dir}", indent=1)
        log("========== Q3 动态重优化求解结束 ==========")
        return results

    def _load_events(self) -> list[dict[str, Any]]:
        payload = json.loads(self.events_path.read_text(encoding="utf-8"))
        events = list(payload.get("events", []))
        if not events:
            raise ValueError("Q3 事件文件中没有 events。")
        log(f"读取事件完成: {len(events)} 条", indent=1)
        return sorted(events, key=lambda item: (float(item["event_time_min"]), str(item["event_id"])))

    def _write_outputs(self, results: list[Q3CaseResult]) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)

        cases_json = self.output_dir / "q3_cases.json"
        cases_json.write_text(
            json.dumps(
                {
                    "generated_at": datetime.now().isoformat(timespec="seconds"),
                    "q1_run_dir": str(self.q1_run_dir),
                    "events_path": str(self.events_path),
                    "case_count": len(results),
                    "cases": [_compact_case_dict(result) for result in results],
                    "detail_files": {
                        "routes": "q3_routes.csv",
                        "stops": "q3_route_stops.csv",
                        "summary": "q3_case_summary.csv",
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        summary_path = self.output_dir / "q3_case_summary.csv"
        summary_fields = [
            "event_id",
            "event_type",
            "event_time_min",
            "status",
            "validation_ok",
            "route_count",
            "used_vehicle_count",
            "total_cost",
            "total_distance_km",
            "energy_cost",
            "carbon_cost",
            "waiting_cost",
            "late_cost",
            "frozen_unit_count",
            "residual_unit_count",
            "added_route_count",
            "removed_route_count",
            "changed_assignment_count",
            "arc_disruption_count",
            "disruption_proxy",
        ]
        with summary_path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=summary_fields)
            writer.writeheader()
            for result in results:
                row = {field: getattr(result, field) for field in summary_fields}
                writer.writerow(row)

        routes_path = self.output_dir / "q3_routes.csv"
        route_fields = [
            "event_id",
            "route_id",
            "vehicle_id",
            "vehicle_type_id",
            "departure_min",
            "return_to_depot_min",
            "stop_count",
            "service_unit_count",
            "customer_sequence",
            "service_unit_ids",
            "total_weight",
            "total_volume",
            "distance_km",
            "route_total_cost_with_startup",
            "energy_cost",
            "carbon_cost",
            "waiting_cost",
            "late_cost",
            "feasible",
            "violations",
        ]
        with routes_path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=route_fields)
            writer.writeheader()
            for result in results:
                writer.writerows(result.routes)

        stops_path = self.output_dir / "q3_route_stops.csv"
        stop_fields = [
            "event_id",
            "route_id",
            "vehicle_id",
            "vehicle_type_id",
            "stop_seq",
            "customer_id",
            "original_customer_id",
            "service_unit_ids",
            "delivered_weight",
            "delivered_volume",
            "arrival_min",
            "service_start_min",
            "leave_min",
            "waiting_minutes",
            "late_minutes",
        ]
        with stops_path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=stop_fields)
            writer.writeheader()
            for result in results:
                writer.writerows(result.stops)

        report_path = self.output_dir / "q3_report.md"
        lines = [
            "# Q3 动态重优化运行报告",
            "",
            f"- Q1 基准方案：`{self.q1_run_dir}`",
            f"- 事件文件：`{self.events_path}`",
            f"- 事件场景数：{len(results)}",
            f"- 校验通过：{sum(1 for item in results if item.validation_ok)}/{len(results)}",
            "- 说明：当前版本不是把 16 条事件串成一天连续滚动状态，而是将 16 条事件分别作为独立动态场景，逐条基于同一个 Q1 基准方案单独重优化。",
            "",
            "## 方法口径",
            "",
            "本版采用保守稳定解法：先按事件时刻冻结 Q1 已执行事实，再把受事件影响的未来服务单元从原路线中摘出，必要时映射成 Q3 虚拟客户节点；新增、地址变更、时间窗变更任务使用事件后从仓库出发的安全单任务路线兜底。车辆允许执行层复用，但同一物理车辆必须通过无时间重叠校验。本版结果口径是独立事件场景，不是多事件连续滚动仿真。",
            "",
            "## 场景汇总",
            "",
            "| 事件 | 类型 | 时刻 | 校验 | 路线数 | 车辆数 | 成本 | 扰动代理 | 备注 |",
            "|---|---|---:|---|---:|---:|---:|---:|---|",
        ]
        for result in results:
            note = "; ".join(result.notes[:3])
            lines.append(
                f"| {result.event_id} | {result.event_type} | {result.event_time_min:.0f} | "
                f"{'通过' if result.validation_ok else '失败'} | {result.route_count} | "
                f"{result.used_vehicle_count} | {result.total_cost:.2f} | "
                f"{result.disruption_proxy:.2f} | {note} |"
            )
        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _compact_case_dict(result: Q3CaseResult) -> dict[str, Any]:
    payload = asdict(result)
    payload.pop("routes", None)
    payload.pop("stops", None)
    return payload


def _solve_event_case_worker(payload: tuple[str, str, str, dict[str, Any]]) -> Q3CaseResult:
    data_dir_text, q1_run_dir_text, _events_path_text, event = payload
    return solve_event_case(
        data_dir=Path(data_dir_text),
        q1_run_dir=Path(q1_run_dir_text),
        event=event,
        constants=Q1Constants(),
    )


def solve_event_case(
    data_dir: Path,
    q1_run_dir: Path,
    event: dict[str, Any],
    constants: Q1Constants | None = None,
) -> Q3CaseResult:
    constants = constants or Q1Constants()
    event_id = str(event["event_id"])
    event_type = str(event["event_type"])
    event_time_min = float(event["event_time_min"])
    log(f"处理 Q3 事件 {event_id}: {event_type}, t={event_time_min:.0f}", indent=1)

    input_data = Q1DataLoader(data_dir=data_dir, constants=constants).load()
    base_units = ServiceUnitBuilder().build_units(
        customers=input_data.customers.values(),
        vehicle_types=list(input_data.vehicle_types.values()),
    )
    base_routes = _load_q1_routes(q1_run_dir=q1_run_dir, base_units={unit.unit_id: unit for unit in base_units})
    base_assignment = _unit_assignment(base_routes)
    frozen_unit_ids = _frozen_service_units(q1_run_dir=q1_run_dir, event_time_min=event_time_min)

    customers = _copy_customers(input_data.customers)
    service_units = _copy_service_units(base_units)
    routes = _copy_routes(base_routes)
    synthetic_original_customer: dict[int, int] = {}
    notes: list[str] = []
    added_route_count = 0
    removed_route_count = 0

    affected_unit: ServiceUnit | None = None
    if event_type == "cancel_order":
        unit_id = str(event["service_unit_id"])
        affected_unit = service_units.get(unit_id)
        if affected_unit is None:
            notes.append(f"取消事件目标不存在: {unit_id}")
        elif unit_id in frozen_unit_ids:
            notes.append(f"取消事件目标已冻结，保留原计划: {unit_id}")
        else:
            _remove_unit_from_routes(routes=routes, unit=affected_unit)
            _subtract_customer_demand(customers, affected_unit.customer_id, affected_unit.weight, affected_unit.volume)
            service_units.pop(unit_id, None)
            notes.append(f"取消未来服务单元: {unit_id}")

    elif event_type == "new_order":
        new_unit, new_customer, original_customer_id = _build_event_unit_and_customer(event, customers)
        service_units[new_unit.unit_id] = new_unit
        customers[new_customer.customer_id] = new_customer
        synthetic_original_customer[new_customer.customer_id] = original_customer_id
        affected_unit = new_unit
        notes.append(f"新增服务单元映射为虚拟客户: {new_unit.unit_id}->{new_customer.customer_id}")

    elif event_type in {"address_change", "time_window_change"}:
        unit_id = str(event["service_unit_id"])
        old_unit = service_units.get(unit_id)
        if old_unit is None:
            notes.append(f"变更事件目标不存在: {unit_id}")
        elif unit_id in frozen_unit_ids:
            notes.append(f"变更事件目标已冻结，保留原计划: {unit_id}")
        else:
            _remove_unit_from_routes(routes=routes, unit=old_unit)
            _subtract_customer_demand(customers, old_unit.customer_id, old_unit.weight, old_unit.volume)
            new_unit, new_customer, original_customer_id = _build_changed_unit_and_customer(event, old_unit, customers)
            service_units[new_unit.unit_id] = new_unit
            customers[new_customer.customer_id] = new_customer
            synthetic_original_customer[new_customer.customer_id] = original_customer_id
            affected_unit = new_unit
            notes.append(f"{event_type} 服务单元摘出并映射为虚拟客户: {unit_id}->{new_customer.customer_id}")

    else:
        notes.append(f"未知事件类型，保留原计划: {event_type}")

    before_count = len(routes)
    routes = [route for route in routes if route.stops]
    removed_route_count = before_count - len(routes)

    distance_matrix = _extend_distance_matrix(
        input_data=input_data,
        customers=customers,
        synthetic_original_customer=synthetic_original_customer,
    )
    evaluator = _build_evaluator(
        input_data=input_data,
        customers=customers,
        service_units=service_units,
        distance_matrix=distance_matrix,
        constants=constants,
    )

    if affected_unit is not None and event_type in {"new_order", "address_change", "time_window_change"}:
        new_route = _build_safe_single_unit_route(
            event_id=event_id,
            event_time_min=event_time_min,
            unit=affected_unit,
            routes=routes,
            evaluator=evaluator,
        )
        routes.append(new_route)
        added_route_count += 1

    _repair_vehicle_schedule_conflicts(routes=routes, evaluator=evaluator)

    route_evaluations = {
        route.route_id: evaluator.evaluate(route)
        for route in routes
    }
    solution = Solution(
        routes=routes,
        unassigned_units=[],
        route_evaluations=route_evaluations,
    )
    solution.metrics = build_solution_metrics(
        routes=solution.routes,
        route_evaluations=solution.route_evaluations,
        unassigned_units=solution.unassigned_units,
        vehicles_by_id=evaluator.vehicles,
    )

    validation = SolutionValidator(
        route_evaluator=evaluator,
        allow_vehicle_reuse=True,
        vehicle_turnaround_min=float(os.environ.get("Q3_VEHICLE_TURNAROUND_MIN", "0") or 0),
    ).validate(solution)
    q3_physical_errors = _validate_q3_physical_rules(
        solution=solution,
        event=event,
        event_time_min=event_time_min,
        synthetic_original_customer=synthetic_original_customer,
    )
    validation_errors = list(validation["errors"]) + q3_physical_errors
    validation_ok = len(validation_errors) == 0

    new_assignment = _unit_assignment(routes)
    changed_assignment_count = sum(
        1
        for unit_id, old_route_id in base_assignment.items()
        if unit_id in service_units and new_assignment.get(unit_id) != old_route_id
    )
    arc_disruption_count = _arc_disruption_count(base_routes=base_routes, new_routes=routes)
    disruption_proxy = float(changed_assignment_count + arc_disruption_count)
    residual_unit_count = len(service_units) - len(frozen_unit_ids & set(service_units))

    return Q3CaseResult(
        event_id=event_id,
        event_type=event_type,
        event_time_min=event_time_min,
        status="ok" if validation_ok else "validation_failed",
        validation_ok=validation_ok,
        route_count=len(solution.routes),
        used_vehicle_count=solution.metrics.used_vehicle_count,
        total_cost=solution.metrics.total_cost,
        total_distance_km=solution.metrics.total_distance_km,
        energy_cost=solution.metrics.total_energy_cost,
        carbon_cost=solution.metrics.total_carbon_cost,
        waiting_cost=solution.metrics.total_waiting_cost,
        late_cost=solution.metrics.total_late_cost,
        frozen_unit_count=len(frozen_unit_ids & set(service_units)),
        residual_unit_count=residual_unit_count,
        added_route_count=added_route_count,
        removed_route_count=removed_route_count,
        changed_assignment_count=changed_assignment_count,
        arc_disruption_count=arc_disruption_count,
        disruption_proxy=disruption_proxy,
        notes=notes,
        validation_errors=validation_errors,
        validation_warnings=list(validation["warnings"]),
        routes=_solution_route_rows(event_id, solution),
        stops=_solution_stop_rows(event_id, solution, synthetic_original_customer),
    )


def _load_q1_routes(q1_run_dir: Path, base_units: dict[str, ServiceUnit]) -> list[Route]:
    routes_path = q1_run_dir / "q1_routes.csv"
    stops_path = q1_run_dir / "q1_route_stops.csv"
    route_meta: dict[str, dict[str, Any]] = {}
    route_order: list[str] = []
    with routes_path.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            route_id = str(row["route_id"])
            route_meta[route_id] = row
            route_order.append(route_id)

    grouped_stops: dict[str, list[RouteStop]] = defaultdict(list)
    with stops_path.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            unit_ids = json.loads(row["service_unit_ids"])
            customer_id = int(row["customer_id"])
            weight = sum(base_units[unit_id].weight for unit_id in unit_ids)
            volume = sum(base_units[unit_id].volume for unit_id in unit_ids)
            grouped_stops[str(row["route_id"])].append(
                RouteStop(
                    service_unit_ids=list(unit_ids),
                    customer_id=customer_id,
                    delivered_weight=weight,
                    delivered_volume=volume,
                )
            )

    routes: list[Route] = []
    for route_id in route_order:
        meta = route_meta[route_id]
        routes.append(
            Route(
                vehicle_id=str(meta["vehicle_id"]),
                vehicle_type_id=int(meta["vehicle_type_id"]),
                departure_min=int(float(meta["departure_min"])),
                stops=grouped_stops.get(route_id, []),
                route_id=route_id,
            )
        )
    return routes


def _frozen_service_units(q1_run_dir: Path, event_time_min: float) -> set[str]:
    frozen: set[str] = set()
    stops_path = q1_run_dir / "q1_route_stops.csv"
    with stops_path.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            route_departure = _route_departure_for_stop(q1_run_dir, str(row["route_id"]))
            leave_min = float(row["leave_min"])
            arrival_min = float(row["arrival_min"])
            if leave_min <= event_time_min or route_departure <= event_time_min < leave_min or arrival_min <= event_time_min < leave_min:
                frozen.update(json.loads(row["service_unit_ids"]))
    return frozen


_ROUTE_DEPARTURE_CACHE: dict[Path, dict[str, float]] = {}


def _route_departure_for_stop(q1_run_dir: Path, route_id: str) -> float:
    if q1_run_dir not in _ROUTE_DEPARTURE_CACHE:
        departures: dict[str, float] = {}
        with (q1_run_dir / "q1_routes.csv").open("r", encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                departures[str(row["route_id"])] = float(row["departure_min"])
        _ROUTE_DEPARTURE_CACHE[q1_run_dir] = departures
    return _ROUTE_DEPARTURE_CACHE[q1_run_dir][route_id]


def _copy_customers(customers: dict[int, Customer]) -> dict[int, Customer]:
    return {
        customer_id: replace(customer, time_window=replace(customer.time_window), raw_orders=list(customer.raw_orders))
        for customer_id, customer in customers.items()
    }


def _copy_service_units(units: list[ServiceUnit]) -> dict[str, ServiceUnit]:
    return {
        unit.unit_id: replace(unit, time_window=replace(unit.time_window), source_order_ids=list(unit.source_order_ids))
        for unit in units
    }


def _copy_routes(routes: list[Route]) -> list[Route]:
    return [
        Route(
            vehicle_id=route.vehicle_id,
            vehicle_type_id=route.vehicle_type_id,
            departure_min=route.departure_min,
            route_id=route.route_id,
            stops=[
                RouteStop(
                    service_unit_ids=list(stop.service_unit_ids),
                    customer_id=stop.customer_id,
                    delivered_weight=stop.delivered_weight,
                    delivered_volume=stop.delivered_volume,
                )
                for stop in route.stops
            ],
        )
        for route in routes
    ]


def _remove_unit_from_routes(routes: list[Route], unit: ServiceUnit) -> None:
    for route in routes:
        new_stops: list[RouteStop] = []
        for stop in route.stops:
            if unit.unit_id not in stop.service_unit_ids:
                new_stops.append(stop)
                continue
            unit_ids = [unit_id for unit_id in stop.service_unit_ids if unit_id != unit.unit_id]
            if unit_ids:
                new_stops.append(
                    RouteStop(
                        service_unit_ids=unit_ids,
                        customer_id=stop.customer_id,
                        delivered_weight=stop.delivered_weight - unit.weight,
                        delivered_volume=stop.delivered_volume - unit.volume,
                    )
                )
        route.stops = new_stops


def _subtract_customer_demand(
    customers: dict[int, Customer],
    customer_id: int,
    weight: float,
    volume: float,
) -> None:
    customer = customers[customer_id]
    customers[customer_id] = replace(
        customer,
        demand_weight=max(0.0, customer.demand_weight - weight),
        demand_volume=max(0.0, customer.demand_volume - volume),
    )


def _build_event_unit_and_customer(
    event: dict[str, Any],
    customers: dict[int, Customer],
) -> tuple[ServiceUnit, Customer, int]:
    original_customer_id = int(event["customer_id"])
    base_customer = customers[original_customer_id]
    synthetic_customer_id = _synthetic_customer_id(event)
    weight = float(event["weight"])
    volume = float(event["volume"])
    window = TimeWindow(
        start_min=int(float(event["window_start_min"])),
        end_min=int(float(event["window_end_min"])),
    )
    customer = Customer(
        customer_id=synthetic_customer_id,
        x=float(event.get("x_km") if event.get("x_km") is not None else base_customer.x),
        y=float(event.get("y_km") if event.get("y_km") is not None else base_customer.y),
        demand_weight=weight,
        demand_volume=volume,
        time_window=window,
        is_green=base_customer.is_green,
        raw_orders=[],
    )
    unit = ServiceUnit(
        unit_id=str(event["service_unit_id"]),
        customer_id=synthetic_customer_id,
        weight=weight,
        volume=volume,
        time_window=window,
        is_green=base_customer.is_green,
        source_order_ids=[str(event["event_id"])],
    )
    return unit, customer, original_customer_id


def _build_changed_unit_and_customer(
    event: dict[str, Any],
    old_unit: ServiceUnit,
    customers: dict[int, Customer],
) -> tuple[ServiceUnit, Customer, int]:
    original_customer_id = old_unit.customer_id
    base_customer = customers[original_customer_id]
    synthetic_customer_id = _synthetic_customer_id(event)
    window = old_unit.time_window
    if event.get("window_start_min") is not None and event.get("window_end_min") is not None:
        window = TimeWindow(
            start_min=int(float(event["window_start_min"])),
            end_min=int(float(event["window_end_min"])),
        )
    customer = Customer(
        customer_id=synthetic_customer_id,
        x=float(event.get("x_km") if event.get("x_km") is not None else base_customer.x),
        y=float(event.get("y_km") if event.get("y_km") is not None else base_customer.y),
        demand_weight=old_unit.weight,
        demand_volume=old_unit.volume,
        time_window=window,
        is_green=base_customer.is_green,
        raw_orders=[],
    )
    unit = ServiceUnit(
        unit_id=old_unit.unit_id,
        customer_id=synthetic_customer_id,
        weight=old_unit.weight,
        volume=old_unit.volume,
        time_window=window,
        is_green=old_unit.is_green,
        source_order_ids=list(old_unit.source_order_ids),
    )
    return unit, customer, original_customer_id


def _synthetic_customer_id(event: dict[str, Any]) -> int:
    type_code = {
        "new_order": 1,
        "cancel_order": 2,
        "address_change": 3,
        "time_window_change": 4,
    }.get(str(event["event_type"]), 9)
    digits = "".join(ch for ch in str(event["event_id"]) if ch.isdigit())
    sample = int(digits[-3:] or "0")
    return 900000 + type_code * 1000 + sample


def _extend_distance_matrix(
    input_data: Q1InputData,
    customers: dict[int, Customer],
    synthetic_original_customer: dict[int, int],
) -> dict[int, dict[int, float]]:
    matrix = {from_node: dict(row) for from_node, row in input_data.distance_matrix.items()}
    coords: dict[int, tuple[float, float]] = {0: (0.0, 0.0)}
    coords.update({customer_id: (customer.x, customer.y) for customer_id, customer in customers.items()})

    for synthetic_id, original_id in synthetic_original_customer.items():
        matrix.setdefault(synthetic_id, {})
        original_coord = coords.get(original_id, (0.0, 0.0))
        original_depot_distance = input_data.distance_matrix.get(0, {}).get(original_id, 0.0)
        original_radius = max(1e-6, math.hypot(original_coord[0], original_coord[1]))
        scale = max(1.0, original_depot_distance / original_radius)
        for node_id, coord in coords.items():
            distance = math.hypot(coords[synthetic_id][0] - coord[0], coords[synthetic_id][1] - coord[1]) * scale
            if node_id == original_id and distance < 1e-9:
                distance = input_data.distance_matrix.get(original_id, {}).get(original_id, 0.0)
            matrix[synthetic_id][node_id] = distance
            matrix.setdefault(node_id, {})[synthetic_id] = distance
        matrix[synthetic_id][synthetic_id] = 0.0
    return matrix


def _build_evaluator(
    input_data: Q1InputData,
    customers: dict[int, Customer],
    service_units: dict[str, ServiceUnit],
    distance_matrix: dict[int, dict[int, float]],
    constants: Q1Constants,
) -> RouteEvaluator:
    vehicles_by_id = {vehicle.vehicle_id: vehicle for vehicle in input_data.vehicles}
    return RouteEvaluator(
        customers=customers,
        vehicles=vehicles_by_id,
        service_units=service_units,
        distance_matrix=distance_matrix,
        traffic_profile=TrafficProfile(constants=constants),
        arc_cost_calculator=ArcCostCalculator(constants=constants),
        constants=constants,
    )


def _build_safe_single_unit_route(
    event_id: str,
    event_time_min: float,
    unit: ServiceUnit,
    routes: list[Route],
    evaluator: RouteEvaluator,
) -> Route:
    schedules = _vehicle_schedules(routes, evaluator)
    compatible_vehicle_ids = [
        vehicle_id
        for vehicle_id, vehicle in evaluator.vehicles.items()
        if unit.weight <= vehicle.vehicle_type.max_weight + 1e-9
        and unit.volume <= vehicle.vehicle_type.max_volume + 1e-9
    ]
    if not compatible_vehicle_ids:
        raise ValueError(f"没有车型能承运 Q3 服务单元: {unit.unit_id}")

    best: tuple[float, float, str, int, Route] | None = None
    candidate_departures = _single_unit_departure_candidates(
        event_time_min=event_time_min,
        unit=unit,
        evaluator=evaluator,
    )
    for vehicle_id in sorted(compatible_vehicle_ids):
        vehicle = evaluator.vehicles[vehicle_id]
        startup_delta = 0.0 if schedules.get(vehicle_id) else vehicle.vehicle_type.startup_cost
        for departure_min in candidate_departures:
            route = Route(
                vehicle_id=vehicle_id,
                vehicle_type_id=vehicle.vehicle_type.type_id,
                departure_min=departure_min,
                route_id=f"Q3_{event_id}",
                stops=[
                    RouteStop(
                        service_unit_ids=[unit.unit_id],
                        customer_id=unit.customer_id,
                        delivered_weight=unit.weight,
                        delivered_volume=unit.volume,
                    )
                ],
            )
            evaluation = evaluator.evaluate(route)
            if not evaluation.feasible or evaluation.return_to_depot_min is None:
                continue
            if _has_overlap(schedules.get(vehicle_id, []), departure_min, evaluation.return_to_depot_min):
                continue
            variable_cost = (
                evaluation.cost.energy_cost
                + evaluation.cost.carbon_cost
                + evaluation.cost.waiting_cost
                + evaluation.cost.late_cost
            )
            score = (
                variable_cost + startup_delta,
                evaluation.return_to_depot_min,
                vehicle_id,
                departure_min,
                route,
            )
            if best is None or score[:4] < best[:4]:
                best = score

    if best is None:
        raise ValueError(f"无法为 Q3 服务单元安排无冲突路线: {unit.unit_id}")
    return best[4]


def _single_unit_departure_candidates(
    event_time_min: float,
    unit: ServiceUnit,
    evaluator: RouteEvaluator,
) -> list[int]:
    distance = evaluator.distance_matrix[0][unit.customer_id]
    rough_fast_travel = distance / 55.3 * 60.0
    values: set[int] = {
        int(math.ceil(event_time_min)),
        int(max(event_time_min, unit.time_window.start_min - rough_fast_travel)),
        int(max(event_time_min, unit.time_window.start_min - 60)),
        int(max(event_time_min, unit.time_window.start_min - 30)),
        int(max(event_time_min, unit.time_window.start_min)),
        int(max(event_time_min, unit.time_window.end_min - 60)),
        int(max(event_time_min, unit.time_window.end_min - 30)),
        int(max(event_time_min, unit.time_window.end_min)),
    }
    upper = int(min(24 * 60 - 1, max(unit.time_window.end_min + 180, event_time_min + 240)))
    step = int(os.environ.get("Q3_SINGLE_ROUTE_DEPARTURE_STEP", "15") or "15")
    for minute in range(int(math.ceil(event_time_min)), upper + 1, max(5, step)):
        values.add(minute)
    return sorted(value for value in values if value >= event_time_min and value >= 480)


def _vehicle_schedules(routes: list[Route], evaluator: RouteEvaluator) -> dict[str, list[tuple[float, float]]]:
    schedules: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for route in routes:
        evaluation = evaluator.evaluate(route)
        if evaluation.feasible and evaluation.return_to_depot_min is not None:
            schedules[route.vehicle_id].append((float(route.departure_min), evaluation.return_to_depot_min))
    for vehicle_schedules in schedules.values():
        vehicle_schedules.sort()
    return schedules


def _repair_vehicle_schedule_conflicts(routes: list[Route], evaluator: RouteEvaluator) -> None:
    """
    在 Q3 删除/摘出服务单元后，原路线时长可能变化。

    这里只做保守排班修复：保持路线顺序和发车时间不变，
    若同一物理车辆出现时间重叠，就把后处理中的冲突路线换到另一辆可承运、
    且当前时间表无冲突的车辆上。
    """

    schedules: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for route in sorted(routes, key=lambda item: (float(item.departure_min), item.route_id)):
        evaluation = evaluator.evaluate(route)
        if not evaluation.feasible or evaluation.return_to_depot_min is None:
            continue
        start = float(route.departure_min)
        end = evaluation.return_to_depot_min
        if not _has_overlap(schedules.get(route.vehicle_id, []), start, end):
            schedules[route.vehicle_id].append((start, end))
            schedules[route.vehicle_id].sort()
            continue

        route_weight = sum(stop.delivered_weight for stop in route.stops)
        route_volume = sum(stop.delivered_volume for stop in route.stops)
        candidates = sorted(
            evaluator.vehicles.values(),
            key=lambda vehicle: (
                vehicle.vehicle_type.type_id != route.vehicle_type_id,
                bool(schedules.get(vehicle.vehicle_id)),
                vehicle.vehicle_type.type_id,
                vehicle.vehicle_id,
            ),
        )
        assigned = False
        for vehicle in candidates:
            if route_weight > vehicle.vehicle_type.max_weight + 1e-9:
                continue
            if route_volume > vehicle.vehicle_type.max_volume + 1e-9:
                continue
            candidate_route = Route(
                vehicle_id=vehicle.vehicle_id,
                vehicle_type_id=vehicle.vehicle_type.type_id,
                departure_min=route.departure_min,
                stops=route.stops,
                route_id=route.route_id,
            )
            candidate_eval = evaluator.evaluate(candidate_route)
            if not candidate_eval.feasible or candidate_eval.return_to_depot_min is None:
                continue
            if _has_overlap(schedules.get(vehicle.vehicle_id, []), start, candidate_eval.return_to_depot_min):
                continue
            route.vehicle_id = vehicle.vehicle_id
            route.vehicle_type_id = vehicle.vehicle_type.type_id
            schedules[route.vehicle_id].append((start, candidate_eval.return_to_depot_min))
            schedules[route.vehicle_id].sort()
            assigned = True
            break
        if not assigned:
            schedules[route.vehicle_id].append((start, end))
            schedules[route.vehicle_id].sort()


def _has_overlap(schedules: list[tuple[float, float]], start: float, end: float) -> bool:
    turnaround = float(os.environ.get("Q3_VEHICLE_TURNAROUND_MIN", "0") or 0)
    return any(start < old_end + turnaround and end + turnaround > old_start for old_start, old_end in schedules)


def _unit_assignment(routes: list[Route]) -> dict[str, str]:
    assignment: dict[str, str] = {}
    for route in routes:
        for stop in route.stops:
            for unit_id in stop.service_unit_ids:
                assignment[unit_id] = route.route_id
    return assignment


def _arc_disruption_count(base_routes: list[Route], new_routes: list[Route]) -> int:
    base_arcs = _route_arc_set(base_routes)
    new_arcs = _route_arc_set(new_routes)
    return len(base_arcs.symmetric_difference(new_arcs))


def _route_arc_set(routes: list[Route]) -> set[tuple[str, int, int]]:
    arcs: set[tuple[str, int, int]] = set()
    for route in routes:
        nodes = [0] + [stop.customer_id for stop in route.stops] + [0]
        for left, right in zip(nodes, nodes[1:]):
            arcs.add((route.route_id, left, right))
    return arcs


def _validate_q3_physical_rules(
    solution: Solution,
    event: dict[str, Any],
    event_time_min: float,
    synthetic_original_customer: dict[int, int],
) -> list[str]:
    errors: list[str] = []
    event_unit_id = str(event.get("service_unit_id", ""))
    if event["event_type"] in {"new_order", "address_change", "time_window_change"}:
        for route in solution.routes:
            if any(event_unit_id in stop.service_unit_ids for stop in route.stops):
                if route.departure_min < event_time_min - 1e-9:
                    errors.append(
                        f"事件服务单元 {event_unit_id} 被安排在事件前发车路线 {route.route_id}"
                    )
                if not any(stop.customer_id in synthetic_original_customer for stop in route.stops):
                    errors.append(
                        f"事件服务单元 {event_unit_id} 未映射为 Q3 虚拟客户"
                    )
    return errors


def _solution_route_rows(event_id: str, solution: Solution) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for route_index, route in enumerate(solution.routes, start=1):
        evaluation = evaluation_for(solution.route_evaluations, route, route_index)
        distance_km = sum(leg.distance_km for leg in evaluation.leg_records) if evaluation else 0.0
        unit_ids = [unit_id for stop in route.stops for unit_id in stop.service_unit_ids]
        rows.append(
            {
                "event_id": event_id,
                "route_id": route.route_id,
                "vehicle_id": route.vehicle_id,
                "vehicle_type_id": route.vehicle_type_id,
                "departure_min": route.departure_min,
                "return_to_depot_min": evaluation.return_to_depot_min if evaluation else "",
                "stop_count": len(route.stops),
                "service_unit_count": len(unit_ids),
                "customer_sequence": "->".join(str(stop.customer_id) for stop in route.stops),
                "service_unit_ids": json.dumps(unit_ids, ensure_ascii=False),
                "total_weight": sum(stop.delivered_weight for stop in route.stops),
                "total_volume": sum(stop.delivered_volume for stop in route.stops),
                "distance_km": distance_km,
                "route_total_cost_with_startup": evaluation.cost.total_cost if evaluation else "",
                "energy_cost": evaluation.cost.energy_cost if evaluation else "",
                "carbon_cost": evaluation.cost.carbon_cost if evaluation else "",
                "waiting_cost": evaluation.cost.waiting_cost if evaluation else "",
                "late_cost": evaluation.cost.late_cost if evaluation else "",
                "feasible": evaluation.feasible if evaluation else False,
                "violations": json.dumps(evaluation.violations if evaluation else [], ensure_ascii=False),
            }
        )
    return rows


def _solution_stop_rows(
    event_id: str,
    solution: Solution,
    synthetic_original_customer: dict[int, int],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for route_index, route in enumerate(solution.routes, start=1):
        evaluation = evaluation_for(solution.route_evaluations, route, route_index)
        leg_records = [leg for leg in evaluation.leg_records if leg.to_node != 0] if evaluation else []
        for stop_seq, stop in enumerate(route.stops, start=1):
            leg = leg_records[stop_seq - 1] if stop_seq - 1 < len(leg_records) else None
            rows.append(
                {
                    "event_id": event_id,
                    "route_id": route.route_id,
                    "vehicle_id": route.vehicle_id,
                    "vehicle_type_id": route.vehicle_type_id,
                    "stop_seq": stop_seq,
                    "customer_id": stop.customer_id,
                    "original_customer_id": synthetic_original_customer.get(stop.customer_id, stop.customer_id),
                    "service_unit_ids": json.dumps(stop.service_unit_ids, ensure_ascii=False),
                    "delivered_weight": stop.delivered_weight,
                    "delivered_volume": stop.delivered_volume,
                    "arrival_min": leg.arrival_min if leg else "",
                    "service_start_min": leg.service_start_min if leg else "",
                    "leave_min": leg.leave_min if leg else "",
                    "waiting_minutes": leg.waiting_minutes if leg else "",
                    "late_minutes": leg.late_minutes if leg else "",
                }
            )
    return rows
