from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model import Solution


class Q1ReportBuilder:
    """负责把 Q1 结果整理成可交付输出。"""

    def build_summary_dict(self, solution: Solution) -> dict[str, Any]:
        """
        把解对象转成可序列化的字典。

        你后面可以在这里组织这些输出块：
        1. 车辆使用情况
        2. 路线方案
        3. 客户分配情况
        4. 成本拆分
        5. 到达/服务/离开时刻明细
        """

        raise NotImplementedError("请实现 Q1 结果汇总。")

    def write_json(self, solution: Solution, output_path: Path) -> None:
        """把结果写成 JSON 文件。"""

        payload = self.build_summary_dict(solution)
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

