from __future__ import annotations

import json
import math
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "cleaned_data"
CUSTOMERS_JSON = DATA_DIR / "customers.json"
MODEL_JSON = DATA_DIR / "order_weight_volume_linear_model.json"
BACKUP_JSON = DATA_DIR / "customers_before_imputation.json"
REPORT_JSON = DATA_DIR / "imputation_report.json"


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)


def clip_nonnegative(value: float) -> float:
    return max(0.0, float(value))


def round_value(value: float) -> float:
    # Keep enough precision for modeling while avoiding noisy floating tails.
    return round(float(value), 6)


def main() -> None:
    customers = json.loads(CUSTOMERS_JSON.read_text(encoding="utf-8"))
    model = json.loads(MODEL_JSON.read_text(encoding="utf-8"))

    volume_model = model["volume_from_weight"]
    weight_model = model["weight_from_volume"]

    if not BACKUP_JSON.exists():
        shutil.copy2(CUSTOMERS_JSON, BACKUP_JSON)

    imputations: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for customer in customers:
        guest_id = customer.get("guest_id")
        for order in customer.get("orders", []):
            order_id = order.get("order_id")
            weight = order.get("weight")
            volume = order.get("volume")
            has_weight = is_number(weight)
            has_volume = is_number(volume)

            if has_weight and not has_volume:
                predicted_volume = clip_nonnegative(
                    volume_model["slope"] * float(weight) + volume_model["intercept"]
                )
                order["volume"] = round_value(predicted_volume)
                order["imputed_fields"] = sorted(set(order.get("imputed_fields", []) + ["volume"]))
                imputations.append(
                    {
                        "guest_id": guest_id,
                        "order_id": order_id,
                        "field": "volume",
                        "known_weight": weight,
                        "old_value": volume,
                        "imputed_value": order["volume"],
                        "model": volume_model["formula"],
                    }
                )
            elif has_volume and not has_weight:
                predicted_weight = clip_nonnegative(
                    weight_model["slope"] * float(volume) + weight_model["intercept"]
                )
                order["weight"] = round_value(predicted_weight)
                order["imputed_fields"] = sorted(set(order.get("imputed_fields", []) + ["weight"]))
                imputations.append(
                    {
                        "guest_id": guest_id,
                        "order_id": order_id,
                        "field": "weight",
                        "known_volume": volume,
                        "old_value": weight,
                        "imputed_value": order["weight"],
                        "model": weight_model["formula"],
                    }
                )
            elif not has_weight and not has_volume:
                skipped.append(
                    {
                        "guest_id": guest_id,
                        "order_id": order_id,
                        "reason": "both weight and volume are missing",
                    }
                )

    CUSTOMERS_JSON.write_text(
        json.dumps(customers, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    remaining_missing = []
    for customer in customers:
        for order in customer.get("orders", []):
            if not is_number(order.get("weight")) or not is_number(order.get("volume")):
                remaining_missing.append(
                    {
                        "guest_id": customer.get("guest_id"),
                        "order_id": order.get("order_id"),
                        "weight": order.get("weight"),
                        "volume": order.get("volume"),
                    }
                )

    report = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "customers_file_updated": str(CUSTOMERS_JSON),
        "backup_file": str(BACKUP_JSON),
        "model_file": str(MODEL_JSON),
        "model_metrics": {
            "volume_from_weight_r2": volume_model.get("r2"),
            "weight_from_volume_r2": weight_model.get("r2"),
        },
        "imputed_count": len(imputations),
        "skipped_count": len(skipped),
        "remaining_missing_count": len(remaining_missing),
        "imputations": imputations,
        "skipped": skipped,
        "remaining_missing": remaining_missing,
    }
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({k: report[k] for k in ("imputed_count", "skipped_count", "remaining_missing_count")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
