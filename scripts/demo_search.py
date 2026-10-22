"""Offline test double for the existing search.py CLI contract.

The application itself always uses skills/dental-care/scripts/search.py.
"""

from __future__ import annotations

import argparse
import json
import unicodedata
from pathlib import Path


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold().replace(" ", "")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    graph_file = Path(__file__).resolve().parents[1] / "data" / "facility_graph.json"
    graph = json.loads(graph_file.read_text(encoding="utf-8"))
    normalized_query = _normalize(args.query)
    scored: list[tuple[int, dict[str, object]]] = []
    for node in graph["nodes"]:
        labels = [node["name"], node["id"], *node.get("aliases", [])]
        normalized_labels = [_normalize(str(label)) for label in labels]
        score = sum(3 for label in normalized_labels if label in normalized_query)
        score += sum(1 for token in normalized_query if any(token in label for label in normalized_labels))
        scored.append((score, node))
    scored.sort(key=lambda item: (-item[0], str(item[1]["id"])))
    selected = [node for score, node in scored if score > 0][: max(1, args.top_k)]
    if not selected:
        selected = [node for _, node in scored[: max(1, args.top_k)]]

    results = []
    for node in selected:
        content = (
            f"施設名: {node['name']}\n"
            f"場所: {node['building']}棟 {node['floor']}階\n"
            f"施設ID: {node['id']}\n"
            f"説明: {node.get('description', '')}"
        )
        results.append(
            {
                "content": content,
                "source": "data/facility_graph.json (オフラインテスト用)",
            }
        )
    print(json.dumps({"results": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
