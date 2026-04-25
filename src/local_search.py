from __future__ import annotations

from .model import Solution
from .route_evaluator import RouteEvaluator


class LocalSearchEngine:
    """Q1 局部搜索改进器。"""

    def __init__(self, route_evaluator: RouteEvaluator) -> None:
        self.route_evaluator = route_evaluator

    def improve(self, solution: Solution) -> Solution:
        """
        局部搜索主循环。

        推荐你按这个顺序实现：
        1. 先做 `relocate`
        2. 再做 `swap`
        3. 再做 `2-opt`
        4. 最后再做车型重分配

        一般策略是：
        - 只要找到改进就接受
        - 接受后重新开始扫描
        - 直到所有邻域都找不到更优解
        """

        raise NotImplementedError("请实现局部搜索主循环。")

    def try_relocate(self, solution: Solution) -> bool:
        """
        尝试 relocate 邻域。

        思路：
        1. 从一条路线拿出一个 service unit。
        2. 插到另一条路线或同一条路线的另一个位置。
        3. 重算受影响的路线。
        4. 若总成本下降且仍可行，则接受。
        """

        raise NotImplementedError("请实现 relocate 邻域。")

    def try_swap(self, solution: Solution) -> bool:
        """
        尝试 swap 邻域。

        思路：
        1. 选两条路线中的两个 unit。
        2. 交换它们。
        3. 重算两条路线。
        4. 若总成本下降且可行，则接受。
        """

        raise NotImplementedError("请实现 swap 邻域。")

    def try_two_opt(self, solution: Solution) -> bool:
        """
        尝试 2-opt 邻域。

        思路：
        1. 在单条路线中取两个切点 i、j。
        2. 反转中间这一段访问顺序。
        3. 精确重算整条路线。
        4. 若成本下降则接受。
        """

        raise NotImplementedError("请实现 2-opt 邻域。")

    def try_vehicle_reassignment(self, solution: Solution) -> bool:
        """
        尝试换车型但不改访问顺序。

        思路：
        1. 保持路线 stops 不变。
        2. 用别的可用车型替换当前车辆。
        3. 检查容量、能耗成本、碳成本是否更优。
        4. 若更优且车型数量约束没被破坏，则接受。
        """

        raise NotImplementedError("请实现车型重分配邻域。")

