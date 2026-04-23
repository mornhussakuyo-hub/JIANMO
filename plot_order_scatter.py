from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parent
CUSTOMERS_JSON = ROOT / "cleaned_data" / "customers.json"
OUTPUT_DIR = ROOT / "cleaned_data"
MPL_CONFIG_PARENT = OUTPUT_DIR / ".matplotlib_cache"
SCATTER_PATH = OUTPUT_DIR / "order_weight_volume_scatter.png"
REPORT_PATH = OUTPUT_DIR / "order_weight_volume_fit_report.json"

MPL_CONFIG_PARENT.mkdir(parents=True, exist_ok=True)
os.environ["MPLCONFIGDIR"] = tempfile.mkdtemp(prefix="mpl-", dir=MPL_CONFIG_PARENT)

import matplotlib.pyplot as plt


def r2_score(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    ss_res = float(np.sum((y_true - y_pred) ** 2))
    ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
    return 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")


def load_orders() -> tuple[np.ndarray, np.ndarray, list[dict]]:
    customers = json.loads(CUSTOMERS_JSON.read_text(encoding="utf-8"))
    rows: list[dict] = []

    for customer in customers:
        guest_id = customer["guest_id"]
        for order in customer["orders"]:
            weight = order.get("weight")
            volume = order.get("volume")
            rows.append(
                {
                    "guest_id": guest_id,
                    "order_id": order.get("order_id"),
                    "weight": weight,
                    "volume": volume,
                }
            )

    valid = [
        row
        for row in rows
        if isinstance(row["weight"], (int, float))
        and isinstance(row["volume"], (int, float))
        and math.isfinite(row["weight"])
        and math.isfinite(row["volume"])
    ]
    weights = np.array([row["weight"] for row in valid], dtype=float)
    volumes = np.array([row["volume"] for row in valid], dtype=float)
    return weights, volumes, rows


def fit_models(weights: np.ndarray, volumes: np.ndarray) -> dict:
    positive_mask = (weights > 0) & (volumes > 0)
    w_pos = weights[positive_mask]
    v_pos = volumes[positive_mask]

    linear_coef = np.polyfit(weights, volumes, deg=1)
    linear_pred = np.polyval(linear_coef, weights)

    through_origin_slope = float(np.sum(weights * volumes) / np.sum(weights * weights))
    through_origin_pred = through_origin_slope * weights

    log_coef = np.polyfit(np.log(w_pos), np.log(v_pos), deg=1)
    power_exponent = float(log_coef[0])
    power_scale = float(np.exp(log_coef[1]))
    power_pred = power_scale * np.power(weights, power_exponent)

    return {
        "linear": {
            "formula": "volume = a * weight + b",
            "a": float(linear_coef[0]),
            "b": float(linear_coef[1]),
            "r2": r2_score(volumes, linear_pred),
        },
        "through_origin": {
            "formula": "volume = a * weight",
            "a": through_origin_slope,
            "r2": r2_score(volumes, through_origin_pred),
        },
        "power": {
            "formula": "volume = a * weight ** b",
            "a": power_scale,
            "b": power_exponent,
            "r2": r2_score(volumes[positive_mask], power_scale * np.power(w_pos, power_exponent)),
        },
    }


def plot_scatter(weights: np.ndarray, volumes: np.ndarray, models: dict) -> None:
    plt.rcParams["font.sans-serif"] = [
        "Microsoft YaHei",
        "SimHei",
        "Arial Unicode MS",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False

    fig, ax = plt.subplots(figsize=(11, 7), dpi=160)
    ax.scatter(
        weights,
        volumes,
        s=18,
        alpha=0.45,
        c="#2671b8",
        edgecolors="none",
        label="Orders",
    )

    x_line = np.linspace(0, float(np.max(weights)) * 1.02, 300)
    linear = models["linear"]
    origin = models["through_origin"]
    power = models["power"]

    ax.plot(
        x_line,
        linear["a"] * x_line + linear["b"],
        color="#d24b35",
        linewidth=2,
        label=f"Linear R2={linear['r2']:.4f}",
    )
    ax.plot(
        x_line,
        origin["a"] * x_line,
        color="#2f9b58",
        linewidth=2,
        linestyle="--",
        label=f"Through origin R2={origin['r2']:.4f}",
    )
    ax.plot(
        x_line[1:],
        power["a"] * np.power(x_line[1:], power["b"]),
        color="#7b4ab8",
        linewidth=2,
        linestyle=":",
        label=f"Power R2={power['r2']:.4f}",
    )

    ax.set_title("Order Weight vs Volume")
    ax.set_xlabel("Weight (kg)")
    ax.set_ylabel("Volume (m^3)")
    ax.grid(True, color="#d9d9d9", linewidth=0.8, alpha=0.8)
    ax.legend(loc="upper left", frameon=True)

    summary = (
        f"n={len(weights)}\n"
        f"weight range: {np.min(weights):.3f}-{np.max(weights):.3f} kg\n"
        f"volume range: {np.min(volumes):.5f}-{np.max(volumes):.5f} m^3"
    )
    ax.text(
        0.99,
        0.02,
        summary,
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=9,
        bbox={"boxstyle": "round,pad=0.35", "facecolor": "white", "edgecolor": "#bbbbbb", "alpha": 0.9},
    )

    fig.tight_layout()
    fig.savefig(SCATTER_PATH)
    plt.close(fig)


def main() -> None:
    weights, volumes, all_rows = load_orders()
    missing_rows = [
        row for row in all_rows if not isinstance(row["weight"], (int, float)) or not isinstance(row["volume"], (int, float))
    ]

    models = fit_models(weights, volumes)
    plot_scatter(weights, volumes, models)

    report = {
        "input": str(CUSTOMERS_JSON),
        "scatter_plot": str(SCATTER_PATH),
        "total_orders": len(all_rows),
        "valid_orders_for_plot": int(len(weights)),
        "missing_or_non_numeric_orders": len(missing_rows),
        "weight": {
            "min": float(np.min(weights)),
            "max": float(np.max(weights)),
            "mean": float(np.mean(weights)),
            "median": float(np.median(weights)),
        },
        "volume": {
            "min": float(np.min(volumes)),
            "max": float(np.max(volumes)),
            "mean": float(np.mean(volumes)),
            "median": float(np.median(volumes)),
        },
        "fits": models,
        "suggestion": "Compare scatter shape and R2. If a strong near-linear relation is visible, volume can be imputed from weight, preferably with robust/outlier-aware fitting.",
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
