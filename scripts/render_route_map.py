"""Render a route map from a validated graph and a JSON request on stdin."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


def _load_font(size: int) -> ImageFont.ImageFont:
    candidates = (
        Path("C:/Windows/Fonts/meiryo.ttc"),
        Path("C:/Windows/Fonts/YuGothM.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    )
    for candidate in candidates:
        if candidate.is_file():
            try:
                return ImageFont.truetype(str(candidate), size)
            except OSError:
                pass
    return ImageFont.load_default()


def _load_base_image(
    graph_file: Path,
    graph: dict[str, Any],
    floor_key: str,
    width: int,
    height: int,
) -> Image.Image:
    relative = graph.get("maps", {}).get(floor_key)
    if relative:
        candidate = (graph_file.parent / str(relative)).resolve()
        # data/facility_graph.json からプロジェクト内の既存Skill画像を参照できる。
        # プロジェクト外の任意ファイルは読み込まない。
        project_root = graph_file.parent.parent.resolve()
        try:
            candidate.relative_to(project_root)
        except ValueError:
            candidate = Path("__invalid__")
        if candidate.is_file():
            return Image.open(candidate).convert("RGB").resize((width, height))
    return Image.new("RGB", (width, height), "white")


def _draw_marker(
    draw: ImageDraw.ImageDraw,
    x: float,
    y: float,
    color: str,
    label: str,
    font: ImageFont.ImageFont,
) -> None:
    radius = 14
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color, outline="black", width=2)
    text_x = x + 20
    text_y = y - 16
    text_box = draw.textbbox((text_x, text_y), label, font=font)
    padding = 5
    draw.rounded_rectangle(
        (
            text_box[0] - padding,
            text_box[1] - padding,
            text_box[2] + padding,
            text_box[3] + padding,
        ),
        radius=6,
        fill="white",
        outline=color,
        width=3,
    )
    draw.text((text_x, text_y), label, fill="#17212b", font=font)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    graph_file = Path(args.graph).resolve()
    output_path = Path(args.output).resolve()
    graph = json.loads(graph_file.read_text(encoding="utf-8"))
    request = json.loads(sys.stdin.read())
    nodes = {str(node["id"]): node for node in graph["nodes"]}
    route_ids = [str(item) for item in request["route_node_ids"]]
    if not route_ids or any(node_id not in nodes for node_id in route_ids):
        raise ValueError("route_node_ids contains an unknown node")
    current_id = str(request["current_id"])
    destination_id = str(request["destination_id"])

    canvas = graph.get("canvas", {})
    width = int(canvas.get("width", 1000))
    height = int(canvas.get("height", 650))
    header_height = 56
    floor_keys: list[str] = []
    for node_id in route_ids:
        node = nodes[node_id]
        key = f"{node['building']}-{node['floor']}"
        if key not in floor_keys:
            floor_keys.append(key)

    panels: list[Image.Image] = []
    title_font = _load_font(24)
    label_font = _load_font(18)
    for floor_key in floor_keys:
        base = _load_base_image(graph_file, graph, floor_key, width, height)
        panel = Image.new("RGB", (width, height + header_height), "#f4f6f8")
        panel.paste(base, (0, header_height))
        draw = ImageDraw.Draw(panel)
        draw.text((20, 14), f"{floor_key.replace('-', '棟 ')}階", fill="#17212b", font=title_font)

        floor_node_ids = {
            node_id
            for node_id, node in nodes.items()
            if f"{node['building']}-{node['floor']}" == floor_key
        }
        for source_id, target_id in zip(route_ids, route_ids[1:]):
            if source_id not in floor_node_ids or target_id not in floor_node_ids:
                continue
            source = nodes[source_id]
            target = nodes[target_id]
            draw.line(
                (
                    float(source["x"]),
                    float(source["y"]) + header_height,
                    float(target["x"]),
                    float(target["y"]) + header_height,
                ),
                fill="#1463d6",
                width=10,
            )
            draw.ellipse(
                (
                    float(target["x"]) - 7,
                    float(target["y"]) + header_height - 7,
                    float(target["x"]) + 7,
                    float(target["y"]) + header_height + 7,
                ),
                fill="#1463d6",
            )

        if current_id in floor_node_ids:
            node = nodes[current_id]
            _draw_marker(
                draw,
                float(node["x"]),
                float(node["y"]) + header_height,
                "#27ae60",
                f"現在地: {node['name']}",
                label_font,
            )
        if destination_id in floor_node_ids:
            node = nodes[destination_id]
            _draw_marker(
                draw,
                float(node["x"]),
                float(node["y"]) + header_height,
                "#e74c3c",
                f"目的地: {node['name']}",
                label_font,
            )
        panels.append(panel)

    gap = 18
    composite = Image.new(
        "RGB",
        (width, sum(panel.height for panel in panels) + gap * (len(panels) - 1)),
        "#dfe4e8",
    )
    offset = 0
    for panel in panels:
        composite.paste(panel, (0, offset))
        offset += panel.height + gap
    output_path.parent.mkdir(parents=True, exist_ok=True)
    composite.save(output_path, format="PNG")
    print(json.dumps({"map_path": str(output_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
