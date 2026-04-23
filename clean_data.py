from __future__ import annotations

import csv
import json
import math
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zipfile import ZipFile
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parent
ATTACHMENT_DIR = ROOT / "附件"
OUTPUT_DIR = ROOT / "cleaned_data"
GREEN_AREA_RADIUS_KM = 10.0
PROBLEM_STATEMENT_GREEN_CUSTOMERS = 30

NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
CELL_RE = re.compile(r"([A-Z]+)([0-9]+)")


def column_to_index(column_name: str) -> int:
    index = 0
    for char in column_name:
        index = index * 26 + ord(char) - ord("A") + 1
    return index - 1


def to_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def to_int_string(value: Any) -> str | None:
    number = to_number(value)
    if number is None:
        text = None if value in (None, "") else str(value).strip()
        return text or None
    if not math.isfinite(number):
        return None
    if abs(number - round(number)) < 1e-9:
        return str(int(round(number)))
    return str(number)


def excel_time_to_hhmm(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        for fmt in ("%H:%M", "%H:%M:%S"):
            try:
                return datetime.strptime(text, fmt).strftime("%H:%M")
            except ValueError:
                pass
        return text

    number = to_number(value)
    if number is None:
        return None
    if 0 <= number < 1:
        total_minutes = int(round(number * 24 * 60))
        hour, minute = divmod(total_minutes, 60)
        return f"{hour % 24:02d}:{minute:02d}"
    if 1 <= number < 2:
        # Be permissive if a time was stored as 1.x by mistake.
        return excel_time_to_hhmm(number - int(number))
    return str(value)


def read_shared_strings(zf: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    strings: list[str] = []
    for item in root.findall("a:si", NS):
        texts = [
            node.text or ""
            for node in item.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")
        ]
        strings.append("".join(texts))
    return strings


def workbook_sheet_paths(zf: ZipFile) -> dict[str, str]:
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rel_targets = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}

    paths: dict[str, str] = {}
    for sheet in workbook.findall("a:sheets/a:sheet", NS):
        name = sheet.attrib["name"]
        rel_id = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
        target = rel_targets[rel_id].lstrip("/")
        if not target.startswith("xl/"):
            target = f"xl/{target}"
        paths[name] = target
    return paths


def cell_value(cell: ET.Element, shared_strings: list[str]) -> Any:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(
            node.text or ""
            for node in cell.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")
        )

    value_node = cell.find("a:v", NS)
    if value_node is None or value_node.text is None:
        return None

    raw = value_node.text
    if cell_type == "s":
        return shared_strings[int(raw)]
    if cell_type == "b":
        return raw == "1"

    try:
        number = float(raw)
    except ValueError:
        return raw
    if math.isfinite(number) and abs(number - round(number)) < 1e-9:
        return int(round(number))
    return number


def read_xlsx_first_sheet(path: Path) -> list[list[Any]]:
    with ZipFile(path) as zf:
        shared_strings = read_shared_strings(zf)
        sheet_paths = workbook_sheet_paths(zf)
        first_sheet_path = next(iter(sheet_paths.values()))
        root = ET.fromstring(zf.read(first_sheet_path))

        rows: list[list[Any]] = []
        for row in root.findall("a:sheetData/a:row", NS):
            values: list[Any] = []
            for cell in row.findall("a:c", NS):
                ref = cell.attrib.get("r", "")
                match = CELL_RE.match(ref)
                if match:
                    column_index = column_to_index(match.group(1))
                    while len(values) < column_index:
                        values.append(None)
                values.append(cell_value(cell, shared_strings))
            rows.append(values)
        return rows


def row_value(row: list[Any], index: int) -> Any:
    return row[index] if index < len(row) else None


def normalize_header(value: Any) -> str:
    return "" if value is None else str(value).strip()


def write_distance_csv(rows: list[list[Any]], report: dict[str, Any]) -> None:
    output_path = OUTPUT_DIR / "distance_matrix.csv"
    cleaned_rows: list[list[Any]] = []

    for row_index, row in enumerate(rows):
        if row_index == 0:
            cleaned_rows.append([normalize_header(value) for value in row])
            continue

        row_id = to_int_string(row_value(row, 0))
        if row_id is None:
            report["skipped_distance_rows"].append(
                {"row_number": row_index + 1, "reason": "missing row id"}
            )
            continue

        cleaned_row: list[Any] = [row_id]
        for col_index, value in enumerate(row[1:], start=1):
            number = to_number(value)
            if number is None:
                cleaned_row.append("")
            elif number < 0:
                report["skipped_distance_cells"].append(
                    {
                        "row_number": row_index + 1,
                        "column_number": col_index + 1,
                        "value": value,
                        "reason": "negative distance",
                    }
                )
                cleaned_row.append("")
            else:
                cleaned_row.append(number)
        cleaned_rows.append(cleaned_row)

    with output_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerows(cleaned_rows)


def build_time_windows(rows: list[list[Any]]) -> dict[str, dict[str, str | None]]:
    windows: dict[str, dict[str, str | None]] = {}
    for row in rows[1:]:
        guest_id = to_int_string(row_value(row, 0))
        if guest_id is None:
            continue
        windows[guest_id] = {
            "early": excel_time_to_hhmm(row_value(row, 1)),
            "late": excel_time_to_hhmm(row_value(row, 2)),
        }
    return windows


def build_coordinates(rows: list[list[Any]], report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    coordinates: dict[str, dict[str, Any]] = {}
    for row_index, row in enumerate(rows[1:], start=2):
        point_type = str(row_value(row, 0) or "").strip()
        guest_id = to_int_string(row_value(row, 1))
        if guest_id is None:
            report["skipped_coordinate_rows"].append(
                {"row_number": row_index, "reason": "missing id"}
            )
            continue
        if guest_id == "0" or point_type == "配送中心":
            continue

        x = to_number(row_value(row, 2))
        y = to_number(row_value(row, 3))
        coordinates[guest_id] = {"x": x, "y": y}
    return coordinates


def make_order(row: list[Any], row_index: int, windows: dict[str, dict[str, str | None]], report: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    order_id = to_int_string(row_value(row, 0))
    weight = to_number(row_value(row, 1))
    volume = to_number(row_value(row, 2))
    guest_id = to_int_string(row_value(row, 3))

    if guest_id is None:
        report["skipped_order_rows"].append(
            {"row_number": row_index, "order_id": order_id, "reason": "missing customer id"}
        )
        return None
    if weight is not None and weight < 0:
        report["skipped_order_rows"].append(
            {"row_number": row_index, "order_id": order_id, "reason": "negative weight"}
        )
        return None
    if volume is not None and volume < 0:
        report["skipped_order_rows"].append(
            {"row_number": row_index, "order_id": order_id, "reason": "negative volume"}
        )
        return None

    window = windows.get(guest_id, {"early": None, "late": None})
    return guest_id, {
        "order_id": order_id,
        "weight": weight,
        "volume": volume,
        "early": window["early"],
        "late": window["late"],
    }


def build_customers(
    coordinate_rows: list[list[Any]],
    time_rows: list[list[Any]],
    order_rows: list[list[Any]],
    report: dict[str, Any],
) -> list[dict[str, Any]]:
    coordinates = build_coordinates(coordinate_rows, report)
    windows = build_time_windows(time_rows)

    customer_ids = set(coordinates) | set(windows)
    orders_by_customer: dict[str, list[dict[str, Any]]] = {}
    for row_index, row in enumerate(order_rows[1:], start=2):
        order = make_order(row, row_index, windows, report)
        if order is None:
            continue
        guest_id, order_data = order
        customer_ids.add(guest_id)
        orders_by_customer.setdefault(guest_id, []).append(order_data)

    customers: list[dict[str, Any]] = []
    for guest_id in sorted(customer_ids, key=lambda item: int(item) if item.isdigit() else item):
        coord = coordinates.get(guest_id, {"x": None, "y": None})
        x = coord.get("x")
        y = coord.get("y")
        if_in_green_area = (
            bool(math.hypot(x, y) <= GREEN_AREA_RADIUS_KM)
            if isinstance(x, (int, float)) and isinstance(y, (int, float))
            else None
        )
        location = {"x": x, "y": y}
        customers.append(
            {
                "guest_id": guest_id,
                "loaction": location,
                "location": location,
                "orders": orders_by_customer.get(guest_id, []),
                "if_in_green_area": if_in_green_area,
            }
        )

    return customers


def build_vehicles() -> list[dict[str, Any]]:
    vehicle_specs = [
        (1, "燃油", 3000, 13.5, 60),
        (2, "燃油", 1500, 10.8, 50),
        (3, "燃油", 1250, 6.5, 50),
        (4, "新能源", 3000, 15.0, 10),
        (5, "新能源", 1250, 8.5, 15),
    ]
    return [
        {
            "k": k,
            "vehicle_type_id": str(k),
            "energy_type": energy_type,
            "max_weight": float(max_weight),
            "max_volume": float(max_volume),
            "available_count": int(available_count),
            "startup_cost": 400.0,
        }
        for k, energy_type, max_weight, max_volume, available_count in vehicle_specs
    ]


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    report: dict[str, Any] = {
        "source_files": {
            "distance_matrix": str(ATTACHMENT_DIR / "距离矩阵.xlsx"),
            "coordinates": str(ATTACHMENT_DIR / "客户坐标信息.xlsx"),
            "orders": str(ATTACHMENT_DIR / "订单信息.xlsx"),
            "time_windows": str(ATTACHMENT_DIR / "时间窗.xlsx"),
        },
        "skipped_distance_rows": [],
        "skipped_distance_cells": [],
        "skipped_coordinate_rows": [],
        "skipped_order_rows": [],
        "notes": [
            "Missing scalar values are written as null in JSON and empty cells in CSV.",
            "Clearly unreasonable records, such as negative distances/weights/volumes or records without customer ids, are skipped.",
            "The requested key name 'loaction' is preserved; a correctly spelled duplicate key 'location' is also included.",
        ],
    }

    distance_rows = read_xlsx_first_sheet(ATTACHMENT_DIR / "距离矩阵.xlsx")
    coordinate_rows = read_xlsx_first_sheet(ATTACHMENT_DIR / "客户坐标信息.xlsx")
    order_rows = read_xlsx_first_sheet(ATTACHMENT_DIR / "订单信息.xlsx")
    time_rows = read_xlsx_first_sheet(ATTACHMENT_DIR / "时间窗.xlsx")

    write_distance_csv(distance_rows, report)
    customers = build_customers(coordinate_rows, time_rows, order_rows, report)
    vehicles = build_vehicles()

    (OUTPUT_DIR / "customers.json").write_text(
        json.dumps(customers, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (OUTPUT_DIR / "vehicles.json").write_text(
        json.dumps(vehicles, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    customers_in_green_area = sum(1 for customer in customers if customer["if_in_green_area"] is True)
    report["summary"] = {
        "distance_matrix_rows_written_including_header": max(len(distance_rows) - len(report["skipped_distance_rows"]), 0),
        "distance_matrix_columns_written": len(distance_rows[0]) if distance_rows else 0,
        "customers_written": len(customers),
        "orders_written": sum(len(customer["orders"]) for customer in customers),
        "vehicle_types_written": len(vehicles),
        "customers_in_green_area_by_coordinates": customers_in_green_area,
        "green_area_radius_km": GREEN_AREA_RADIUS_KM,
        "problem_statement_green_customers": PROBLEM_STATEMENT_GREEN_CUSTOMERS,
    }
    if customers_in_green_area != PROBLEM_STATEMENT_GREEN_CUSTOMERS:
        report["notes"].append(
            "The problem statement says 30 customers are in the green area, but applying the stated radius-10-km rule to the coordinate file gives "
            f"{customers_in_green_area} customers. The JSON field if_in_green_area follows the coordinate rule."
        )
    (OUTPUT_DIR / "cleaning_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
