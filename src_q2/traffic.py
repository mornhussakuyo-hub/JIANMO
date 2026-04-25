from __future__ import annotations

from .constants import Q1Constants, SpeedSegment
from .model import TravelSegmentRecord


class TrafficProfile:
    """Q1/Q2 共用的时变速度模型。"""

    def __init__(self, constants: Q1Constants | None = None) -> None:
        self.constants = constants or Q1Constants()

    def get_speed_kmh(self, minute_of_day: float) -> float:
        """
        给定某一时刻，返回该时刻对应的期望车速。

        实现思路很简单：
        1. 在 speed_segments 里查当前分钟落在哪个区间
        2. 找到就返回该区间速度
        3. 若超出显式区间，就返回 fallback_speed_kmh
        """

        for segment in self.constants.speed_segments:
            if segment.start_min <= minute_of_day < segment.end_min:
                return segment.speed_kmh
        return self.constants.fallback_speed_kmh

    def get_segment_for_minute(self, minute_of_day: float) -> SpeedSegment | None:
        """返回当前时刻所在的交通时段。若是外推时段则返回 None。"""

        for segment in self.constants.speed_segments:
            if segment.start_min <= minute_of_day < segment.end_min:
                return segment
        return None

    def get_segment_end_minute(self, minute_of_day: float) -> float:
        """
        返回当前交通时段的结束时刻。

        如果已经落到外推区间，就可以返回一个很大的值或正无穷，
        表示后面都按 fallback 速度走。
        """

        segment = self.get_segment_for_minute(minute_of_day)
        if segment is None:
            return float("inf")
        return float(segment.end_min)

    def travel_segments(self, distance_km: float, depart_min: float) -> list[TravelSegmentRecord]:
        """
        把一条弧按交通时段切成多个片段。

        计算过程：
        1. 初始化剩余距离 `remaining_distance = distance_km`
        2. 当前时间从 `depart_min` 开始
        3. 判断当前属于哪个时段，该时段还能走多久
        4. 算出该时段最多能走多远
        5. 如果已经能走完剩余距离，就生成最后一个片段并结束
        6. 否则生成一个完整片段，扣掉这段距离，时间推进到下一个时段

        这个函数是后面：
        - 路程时间计算
        - 能耗计算
        的共同基础
        """
        if distance_km < 0:
            raise ValueError("distance_km 不能为负数。")
        
        if distance_km == 0:
            return []

        remaining_distance = float(distance_km)
        current_min = float(depart_min)
        segments: list[TravelSegmentRecord]=[]
        eps=1e-9

        while remaining_distance > eps:
            speed_kmh=self.get_speed_kmh(current_min)
            if speed_kmh<=0:
                raise ValueError("速度必须为正数。")
            
            segment=self.get_segment_for_minute(current_min)

            # 如果已经超出显式时段，一直按 fallback 速度走到终点
            if segment is None:
                travel_hours = remaining_distance / speed_kmh 
                travel_minutes = travel_hours * self.constants.hour_to_min
                end_min = current_min + travel_minutes


                segments.append(
                    TravelSegmentRecord(
                        start_min=current_min,
                        end_min=end_min,
                        speed_kmh=speed_kmh,
                        distance_km=remaining_distance,
                        period_label="FALLBACK",
                    )
                )
                remaining_distance = 0.0
                break

            available_minutes = float(segment.end_min)-current_min
            available_hours   = available_minutes / self.constants.hour_to_min
            max_distance_this_segment = speed_kmh*available_hours

            if remaining_distance <= max_distance_this_segment +eps:
                travel_hours=remaining_distance/speed_kmh
                travel_minutes = travel_hours * self.constants.hour_to_min
                end_min = current_min + travel_minutes

                segments.append(
                    TravelSegmentRecord(
                        start_min=current_min,
                        end_min=end_min,
                        speed_kmh=speed_kmh,
                        distance_km=remaining_distance,
                        period_label=segment.label,
                    )
                )
                remaining_distance =0.0

            else:
                segments.append(
                    TravelSegmentRecord(
                        start_min=current_min,
                        end_min=float(segment.end_min),
                        speed_kmh=speed_kmh,
                        distance_km=max_distance_this_segment,
                        period_label=segment.label,
                    )
                )
                remaining_distance -= max_distance_this_segment
                current_min =float(segment.end_min)

        return segments

    def travel_time_minutes(self, distance_km: float, depart_min: float) -> float:
        """
        计算在给定出发时刻下，走完某段距离需要多少分钟。

        最稳的写法是直接复用 `travel_segments`：
        - 每个片段的时间 = 距离 / 速度
        - 最后把所有片段时间加总
        """
        segments = self.travel_segments(distance_km=distance_km,depart_min=depart_min)
        return sum(segment.end_min - segment.start_min   for segment in segments)


