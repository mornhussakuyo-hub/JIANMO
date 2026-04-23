from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parent
CUSTOMERS_JSON = ROOT / "cleaned_data" / "customers.json"
MODEL_JSON = ROOT / "cleaned_data" / "order_weight_volume_linear_model.json"


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)


def load_training_data() -> tuple[np.ndarray, np.ndarray, list[dict[str, Any]]]:
    customers = json.loads(CUSTOMERS_JSON.read_text(encoding="utf-8"))
    valid_rows: list[dict[str, Any]] = []

    for customer in customers:
        for order in customer.get("orders", []):
            weight = order.get("weight")
            volume = order.get("volume")
            if is_number(weight) and is_number(volume) and weight > 0 and volume > 0:
                valid_rows.append(
                    {
                        "guest_id": customer.get("guest_id"),
                        "order_id": order.get("order_id"),
                        "weight": float(weight),
                        "volume": float(volume),
                    }
                )

    weights = np.array([row["weight"] for row in valid_rows], dtype=float)
    volumes = np.array([row["volume"] for row in valid_rows], dtype=float)
    return weights, volumes, valid_rows


def fit_simple_linear(x: np.ndarray, y: np.ndarray) -> dict[str, float]:
    slope, intercept = np.polyfit(x, y, deg=1)
    y_pred = slope * x + intercept
    residuals = y - y_pred
    ss_res = float(np.sum(residuals**2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    mae = float(np.mean(np.abs(residuals)))
    rmse = float(np.sqrt(np.mean(residuals**2)))

    return {
        "slope": float(slope),
        "intercept": float(intercept),
        "r2": r2,
        "mae": mae,
        "rmse": rmse,
    }


def train() -> dict[str, Any]:
    weights, volumes, rows = load_training_data()
    if len(rows) < 2:
        raise RuntimeError("Not enough complete orders to train a linear model.")

    volume_from_weight = fit_simple_linear(weights, volumes)
    weight_from_volume = fit_simple_linear(volumes, weights)

    model = {
        "model_type": "ordinary_least_squares_linear_regression",
        "source_file": str(CUSTOMERS_JSON),
        "target_file": str(MODEL_JSON),
        "training_samples": len(rows),
        "volume_from_weight": {
            "formula": "volume = slope * weight + intercept",
            **volume_from_weight,
        },
        "weight_from_volume": {
            "formula": "weight = slope * volume + intercept",
            **weight_from_volume,
        },
        "data_summary": {
            "weight_min": float(np.min(weights)),
            "weight_max": float(np.max(weights)),
            "weight_mean": float(np.mean(weights)),
            "volume_min": float(np.min(volumes)),
            "volume_max": float(np.max(volumes)),
            "volume_mean": float(np.mean(volumes)),
        },
        "notes": [
            "This is a simple OLS linear model trained on complete positive order records.",
            "Predictions are clipped at 0 because negative weight or volume is physically invalid.",
            "For imputing missing values, prefer this model only when the scatter plot supports an approximately linear relation.",
        ],
    }
    MODEL_JSON.write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")
    return model


def load_model() -> dict[str, Any]:
    if not MODEL_JSON.exists():
        return train()
    return json.loads(MODEL_JSON.read_text(encoding="utf-8"))


def predict_volume(weight: float, model: dict[str, Any]) -> float:
    params = model["volume_from_weight"]
    return max(0.0, params["slope"] * weight + params["intercept"])


def predict_weight(volume: float, model: dict[str, Any]) -> float:
    params = model["weight_from_volume"]
    return max(0.0, params["slope"] * volume + params["intercept"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Train or use a bidirectional linear model between order weight and volume."
    )
    parser.add_argument(
        "--train",
        action="store_true",
        help="Retrain the model and write cleaned_data/order_weight_volume_linear_model.json.",
    )
    parser.add_argument("--weight", type=float, help="Known order weight in kg; predicts volume.")
    parser.add_argument("--volume", type=float, help="Known order volume in m^3; predicts weight.")
    return parser


def main() -> None:
    args = build_parser().parse_args()

    if args.train or not MODEL_JSON.exists():
        model = train()
        print("Model trained and saved:")
        print(json.dumps(model, ensure_ascii=False, indent=2))
    else:
        model = load_model()

    if args.weight is not None:
        prediction = predict_volume(args.weight, model)
        print(
            json.dumps(
                {
                    "input": {"weight": args.weight},
                    "prediction": {"volume": prediction},
                    "model": "volume_from_weight",
                },
                ensure_ascii=False,
                indent=2,
            )
        )

    if args.volume is not None:
        prediction = predict_weight(args.volume, model)
        print(
            json.dumps(
                {
                    "input": {"volume": args.volume},
                    "prediction": {"weight": prediction},
                    "model": "weight_from_volume",
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
