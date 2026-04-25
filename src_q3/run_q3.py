from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from .dynamic_solver import Q3DynamicSolver
from .log_utils import log


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    data_dir = Path(os.environ.get("Q3_DATA_DIR", "") or (repo_root / "cleaned_data"))
    q1_run_dir = Path(
        os.environ.get("Q3_Q1_RUN_DIR", "")
        or (repo_root / "outputs" / "q1" / "run_20260425_182112")
    )
    events_path = Path(
        os.environ.get("Q3_EVENTS_PATH", "")
        or (data_dir / "q3_events_reasonable_samples_from_q1_run_20260425_182112.json")
    )

    output_root = Path(os.environ.get("Q3_OUTPUT_DIR", "") or (repo_root / "outputs" / "q3"))
    if os.environ.get("Q3_OUTPUT_TIMESTAMP", "1") != "0":
        output_dir = output_root / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    else:
        output_dir = output_root

    solver = Q3DynamicSolver(
        data_dir=data_dir,
        q1_run_dir=q1_run_dir,
        events_path=events_path,
        output_dir=output_dir,
    )
    results = solver.solve_all()

    log("========== Q3 最终结果摘要 ==========")
    for result in results:
        status = "通过" if result.validation_ok else "失败"
        log(
            f"{result.event_id}: {status}, 成本 {result.total_cost:.2f}, "
            f"路线 {result.route_count}, 车辆 {result.used_vehicle_count}, "
            f"扰动 {result.disruption_proxy:.2f}",
            indent=1,
        )
        for error in result.validation_errors[:3]:
            log(f"错误: {error}", indent=2)
    log(f"Q3 输出目录: {output_dir}", indent=1)


if __name__ == "__main__":
    main()
