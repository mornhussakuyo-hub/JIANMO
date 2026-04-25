from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
FONT_REGULAR = Path(r"C:\Windows\Fonts\msyh.ttc")
FONT_BOLD = Path(r"C:\Windows\Fonts\msyhbd.ttc")


def load_font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size=size)


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> str:
    lines: list[str] = []
    current = ""
    for ch in text:
        trial = current + ch
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = ch
    if current:
        lines.append(current)
    return "\n".join(lines)


def draw_flowchart(
    output_path: Path,
    title: str,
    subtitle: str,
    steps: list[tuple[str, str]],
) -> None:
    width = 1800
    margin_x = 90
    top = 70
    box_x = 240
    box_w = width - 2 * box_x
    box_h = 150
    box_gap = 56
    arrow_h = 34
    footer_h = 52
    height = top + 70 + 40 + len(steps) * box_h + (len(steps) - 1) * (box_gap + arrow_h) + footer_h + 70

    image = Image.new("RGB", (width, height), (244, 247, 252))
    draw = ImageDraw.Draw(image)

    title_font = load_font(FONT_BOLD, 46)
    subtitle_font = load_font(FONT_REGULAR, 22)
    step_title_font = load_font(FONT_BOLD, 26)
    step_body_font = load_font(FONT_REGULAR, 19)
    footer_font = load_font(FONT_REGULAR, 14)

    draw.text((margin_x, 38), title, fill=(32, 47, 79), font=title_font)
    draw.text((margin_x, 92), subtitle, fill=(92, 105, 128), font=subtitle_font)

    fills = [
        (224, 235, 249),
        (224, 235, 249),
        (226, 241, 236),
        (226, 241, 236),
        (248, 237, 211),
        (248, 237, 211),
        (228, 222, 244),
        (244, 225, 225),
        (224, 242, 242),
    ]
    outline = (193, 208, 228)
    arrow_color = (63, 78, 102)

    y = 145
    for index, (step_title, step_body) in enumerate(steps, start=1):
        fill = fills[(index - 1) % len(fills)]
        draw.rounded_rectangle(
            (box_x, y, box_x + box_w, y + box_h),
            radius=22,
            fill=fill,
            outline=outline,
            width=3,
        )
        draw.text((box_x + 26, y + 18), f"{index}. {step_title}", fill=(33, 48, 79), font=step_title_font)
        body_text = wrap_text(draw, step_body, step_body_font, box_w - 52)
        draw.multiline_text(
            (box_x + 26, y + 62),
            body_text,
            fill=(54, 66, 84),
            font=step_body_font,
            spacing=6,
        )
        if index < len(steps):
            cx = width // 2
            start_y = y + box_h + 8
            end_y = start_y + arrow_h
            draw.line((cx, start_y, cx, end_y), fill=arrow_color, width=5)
            head = [(cx - 12, end_y - 6), (cx + 12, end_y - 6), (cx, end_y + 14)]
            draw.polygon(head, fill=arrow_color)
            y += box_h + box_gap + arrow_h

    footer = f"输出文件: {output_path.as_posix()}"
    draw.text((margin_x, height - 38), footer, fill=(110, 122, 140), font=footer_font)

    image.save(output_path)


def main() -> None:
    q3_steps = [
        (
            "读取 Q1 基准解与 Q3 事件",
            "读取 cleaned_data、Q1 基准输出目录和 Q3 事件文件，当前口径是每条事件样例单独求解，不串成全天连续状态。",
        ),
        (
            "加载基准路线与服务单元",
            "恢复原始路线、停靠点、服务单元覆盖、车辆使用与客户映射，作为每个事件场景的共同起点。",
        ),
        (
            "按事件时刻切分执行状态",
            "识别已完成、已出发和未开始部分；冻结不可回退的执行前缀，只释放可调整的未来任务。",
        ),
        (
            "应用事件并更新残余任务",
            "处理新增订单、取消订单、地址变化和时间窗变化，为变化后的需求生成新的待配送任务集合。",
        ),
        (
            "构造虚拟客户与安全候选路线",
            "对事件引入的新需求创建 synthetic customer，必要时生成从仓库出发的单任务安全路线作为稳定兜底。",
        ),
        (
            "重排残余任务并搜索发车时刻",
            "优先尝试把任务并入可行未来路线，同时枚举发车候选，兼顾时间窗、容量和车辆周转可行性。",
        ),
        (
            "校验真实车辆复用与约束",
            "检查同一物理车辆多趟路线是否时间重叠，并统一复核容量、时间窗、服务覆盖和返仓时刻。",
        ),
        (
            "事件级多核并行求解",
            "各事件场景彼此独立，因此可通过 Q3_PARALLEL_WORKERS 同时分发到多个进程批量计算。",
        ),
        (
            "汇总结果并输出报告",
            "输出 q3_cases.json、q3_case_summary.csv、q3_routes.csv、q3_route_stops.csv 和 q3_report.md。",
        ),
    ]

    q3_continue_steps = [
        (
            "读取 Q1 基准解与事件序列",
            "加载 cleaned_data、Q1 基准输出和 Q3 事件文件，本版本目标是把全部事件按真实时间顺序串起来滚动。",
        ),
        (
            "初始化连续滚动系统状态",
            "建立当前路线、客户映射、服务单元集合、车辆使用记录和 synthetic customer 映射，后续事件共享这份状态。",
        ),
        (
            "按 event_time_min 排序事件",
            "对全部事件按发生时刻排序，确保后续每次重优化都承接上一事件处理后的真实残余状态。",
        ),
        (
            "在事件时刻切分当前计划",
            "把系统切成已完成前缀、在途部分和未来未执行部分，只允许对未来任务和新扰动进行调整。",
        ),
        (
            "应用事件并更新客户需求",
            "处理新增、取消、地址变化和时间窗变化，把变化直接写回主状态，而不是生成一次性独立副本。",
        ),
        (
            "重优化未来路线与残余任务",
            "尽量保持已执行前缀不动，优先在未来计划中重插服务单元，必要时使用单任务安全路线兜底。",
        ),
        (
            "刷新车辆复用与连续可行性",
            "重新检查车辆时间重叠、周转时间、服务覆盖和路线评价，确保新的系统状态仍然合法。",
        ),
        (
            "写回状态并进入下一事件",
            "把当前事件后的路线、客户、服务单元和车辆状态保存下来，供下一条事件继续滚动使用。",
        ),
        (
            "输出全天连续演化结果",
            "输出 q3_cases.json、q3_case_summary.csv、q3_routes.csv、q3_route_stops.csv 和 q3_report.md，展示整天动态演化轨迹。",
        ),
    ]

    draw_flowchart(
        output_path=ROOT / "q3_algorithm_flowchart.png",
        title="Q3 独立事件版算法流程图",
        subtitle="基于 Q1 基准解的单事件动态重优化 + 事件级多核并行",
        steps=q3_steps,
    )
    draw_flowchart(
        output_path=ROOT / "q3_continue_algorithm_flowchart.png",
        title="Q3 连续滚动版算法流程图",
        subtitle="16 条事件按时间顺序串联的连续滚动重优化",
        steps=q3_continue_steps,
    )


if __name__ == "__main__":
    main()
