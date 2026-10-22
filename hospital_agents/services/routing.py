from __future__ import annotations

import heapq
import json
import math
import re
import unicodedata
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

from hospital_agents.errors import (
    AmbiguousLocationError,
    ConfigurationError,
    LocationNotFoundError,
    RouteNotFoundError,
)
from hospital_agents.models import FacilityNode, RouteEdge, RouteResult, RouteStep


def normalize_location_name(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"[\s　・/／()（）\-]+", "", normalized)


class RouteEngine:
    """Loads a facility graph and performs deterministic name resolution and Dijkstra routing."""

    def __init__(self, graph_file: Path) -> None:
        self.graph_file = graph_file.resolve()
        self.raw_graph = self._load_graph()
        self.distance_note = str(
            self.raw_graph.get("metadata", {}).get(
                "distance_note",
                "距離は施設グラフに登録された値です。",
            )
        )
        self.nodes = self._load_nodes(self.raw_graph)
        self.edges = self._load_edges(self.raw_graph)
        self._adjacency = self._build_adjacency()
        self._aliases = self._build_alias_index()

    def _load_graph(self) -> dict[str, Any]:
        if not self.graph_file.is_file():
            raise ConfigurationError(f"施設グラフが見つかりません: {self.graph_file}")
        try:
            value = json.loads(self.graph_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ConfigurationError(f"施設グラフを読み込めません: {error}") from error
        if not isinstance(value, dict):
            raise ConfigurationError("施設グラフのルートはJSON objectである必要があります。")
        return value

    @staticmethod
    def _load_nodes(raw_graph: dict[str, Any]) -> dict[str, FacilityNode]:
        nodes: dict[str, FacilityNode] = {}
        for raw_node in raw_graph.get("nodes", []):
            node = FacilityNode.from_dict(raw_node)
            if node.id in nodes:
                raise ConfigurationError(f"施設グラフのnode idが重複しています: {node.id}")
            nodes[node.id] = node
        if not nodes:
            raise ConfigurationError("施設グラフにnodesがありません。")
        return nodes

    def _load_edges(self, raw_graph: dict[str, Any]) -> tuple[RouteEdge, ...]:
        edges = tuple(RouteEdge.from_dict(item) for item in raw_graph.get("edges", []))
        for edge in edges:
            if edge.source not in self.nodes or edge.target not in self.nodes:
                raise ConfigurationError(
                    f"edgeが存在しないnodeを参照しています: {edge.source} -> {edge.target}"
                )
            if edge.distance_m <= 0:
                raise ConfigurationError("edge.distance_m は正数である必要があります。")
        if not edges:
            raise ConfigurationError("施設グラフにedgesがありません。")
        return edges

    def _build_adjacency(self) -> dict[str, list[tuple[str, RouteEdge]]]:
        adjacency: dict[str, list[tuple[str, RouteEdge]]] = defaultdict(list)
        for edge in self.edges:
            adjacency[edge.source].append((edge.target, edge))
            if edge.bidirectional:
                adjacency[edge.target].append((edge.source, edge))
        return dict(adjacency)

    def _build_alias_index(self) -> dict[str, set[str]]:
        aliases: dict[str, set[str]] = defaultdict(set)
        for node in self.nodes.values():
            for label in node.labels:
                normalized = normalize_location_name(label)
                if normalized:
                    aliases[normalized].add(node.id)
        return dict(aliases)

    def resolve(self, query: str) -> FacilityNode:
        normalized_query = normalize_location_name(query)
        if not normalized_query:
            raise LocationNotFoundError("場所が空です。")

        exact_ids = self._aliases.get(normalized_query, set())
        if exact_ids:
            return self._require_unique(query, exact_ids)

        candidates: set[str] = set()
        longest_match = 0
        for alias, node_ids in self._aliases.items():
            if alias in normalized_query or normalized_query in alias:
                match_length = min(len(alias), len(normalized_query))
                if match_length > longest_match:
                    candidates = set(node_ids)
                    longest_match = match_length
                elif match_length == longest_match:
                    candidates.update(node_ids)
        if not candidates:
            raise LocationNotFoundError(
                f"施設名を特定できません: {query!r}。施設グラフのname/aliasesを確認してください。"
            )
        return self._require_unique(query, candidates)

    def _require_unique(self, query: str, node_ids: set[str]) -> FacilityNode:
        if len(node_ids) != 1:
            names = ", ".join(sorted(self.nodes[node_id].name for node_id in node_ids))
            raise AmbiguousLocationError(
                f"場所 {query!r} は複数候補に一致します: {names}。棟・階・部屋名を追加してください。"
            )
        return self.nodes[next(iter(node_ids))]

    def calculate(self, current_query: str, destination_query: str) -> RouteResult:
        current = self.resolve(current_query)
        destination = self.resolve(destination_query)
        return self.calculate_between(current, destination)

    def calculate_between(
        self,
        current: FacilityNode,
        destination: FacilityNode,
    ) -> RouteResult:
        if current.id == destination.id:
            return RouteResult(
                route_id=uuid.uuid4().hex,
                current=current,
                destination=destination,
                node_ids=(current.id,),
                distance_m=0.0,
                overall_direction="現在地が目的地です",
                steps=(),
                distance_note=self.distance_note,
            )

        distances = {node_id: math.inf for node_id in self.nodes}
        distances[current.id] = 0.0
        previous: dict[str, tuple[str, RouteEdge]] = {}
        queue: list[tuple[float, str]] = [(0.0, current.id)]

        while queue:
            distance, node_id = heapq.heappop(queue)
            if distance > distances[node_id]:
                continue
            if node_id == destination.id:
                break
            for neighbor_id, edge in self._adjacency.get(node_id, []):
                next_distance = distance + edge.distance_m
                if next_distance < distances[neighbor_id]:
                    distances[neighbor_id] = next_distance
                    previous[neighbor_id] = (node_id, edge)
                    heapq.heappush(queue, (next_distance, neighbor_id))

        if destination.id not in previous:
            raise RouteNotFoundError(
                f"{current.name} から {destination.name} への経路がありません。"
            )

        reversed_node_ids = [destination.id]
        reversed_edges: list[RouteEdge] = []
        cursor = destination.id
        while cursor != current.id:
            parent_id, edge = previous[cursor]
            reversed_node_ids.append(parent_id)
            reversed_edges.append(edge)
            cursor = parent_id
        node_ids = tuple(reversed(reversed_node_ids))
        path_edges = tuple(reversed(reversed_edges))
        steps = self._make_steps(node_ids, path_edges)

        first_target = self.nodes[node_ids[1]]
        overall_direction = self._direction_between(current, first_target)
        if first_target.floor_key != current.floor_key:
            overall_direction = path_edges[0].instruction or "別フロアへ移動"

        return RouteResult(
            route_id=uuid.uuid4().hex,
            current=current,
            destination=destination,
            node_ids=node_ids,
            distance_m=distances[destination.id],
            overall_direction=overall_direction,
            steps=steps,
            distance_note=self.distance_note,
        )

    def _make_steps(
        self,
        node_ids: tuple[str, ...],
        edges: tuple[RouteEdge, ...],
    ) -> tuple[RouteStep, ...]:
        steps: list[RouteStep] = []
        for source_id, target_id, edge in zip(node_ids, node_ids[1:], edges):
            source = self.nodes[source_id]
            target = self.nodes[target_id]
            if edge.instruction:
                instruction = edge.instruction
            elif source.floor_key != target.floor_key:
                instruction = f"{target.building}棟{target.floor}階へ移動"
            else:
                direction = self._direction_between(source, target)
                instruction = f"{direction}へ進み、{target.name}へ向かう"
            steps.append(
                RouteStep(
                    from_id=source_id,
                    to_id=target_id,
                    instruction=instruction,
                    distance_m=edge.distance_m,
                )
            )
        return tuple(steps)

    @staticmethod
    def _direction_between(source: FacilityNode, target: FacilityNode) -> str:
        dx = target.x - source.x
        dy = source.y - target.y  # Map y grows downward; north is up.
        if dx == 0 and dy == 0:
            return "同じ位置"
        angle = math.degrees(math.atan2(dy, dx)) % 360
        labels = (
            "画像の右方向",
            "画像の右上方向",
            "画像の上方向",
            "画像の左上方向",
            "画像の左方向",
            "画像の左下方向",
            "画像の下方向",
            "画像の右下方向",
        )
        return labels[int((angle + 22.5) // 45) % 8]

    def destination_is_present_in_rag(self, destination: FacilityNode, rag_output: str) -> bool:
        normalized_output = normalize_location_name(rag_output)
        return any(
            normalize_location_name(label) in normalized_output
            for label in destination.labels
            if len(normalize_location_name(label)) >= 2
        )
