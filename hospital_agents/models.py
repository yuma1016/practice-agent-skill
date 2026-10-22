from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FacilityNode:
    id: str
    name: str
    aliases: tuple[str, ...]
    building: str
    floor: str
    x: float
    y: float
    description: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "FacilityNode":
        return cls(
            id=str(value["id"]),
            name=str(value["name"]),
            aliases=tuple(str(item) for item in value.get("aliases", [])),
            building=str(value["building"]),
            floor=str(value["floor"]),
            x=float(value["x"]),
            y=float(value["y"]),
            description=str(value.get("description", "")),
        )

    @property
    def floor_key(self) -> str:
        return f"{self.building}-{self.floor}"

    @property
    def labels(self) -> tuple[str, ...]:
        return (self.id, self.name, *self.aliases)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "building": self.building,
            "floor": self.floor,
            "x": self.x,
            "y": self.y,
            "description": self.description,
        }


@dataclass(frozen=True)
class RouteEdge:
    source: str
    target: str
    distance_m: float
    instruction: str = ""
    bidirectional: bool = True

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RouteEdge":
        return cls(
            source=str(value["from"]),
            target=str(value["to"]),
            distance_m=float(value["distance_m"]),
            instruction=str(value.get("instruction", "")),
            bidirectional=bool(value.get("bidirectional", True)),
        )


@dataclass(frozen=True)
class RouteStep:
    from_id: str
    to_id: str
    instruction: str
    distance_m: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_id": self.from_id,
            "to_id": self.to_id,
            "instruction": self.instruction,
            "distance_m": round(self.distance_m, 1),
        }


@dataclass(frozen=True)
class RouteResult:
    route_id: str
    current: FacilityNode
    destination: FacilityNode
    node_ids: tuple[str, ...]
    distance_m: float
    overall_direction: str
    steps: tuple[RouteStep, ...]
    distance_note: str = ""
    map_path: Path | None = None

    def with_map_path(self, map_path: Path) -> "RouteResult":
        return RouteResult(
            route_id=self.route_id,
            current=self.current,
            destination=self.destination,
            node_ids=self.node_ids,
            distance_m=self.distance_m,
            overall_direction=self.overall_direction,
            steps=self.steps,
            distance_note=self.distance_note,
            map_path=map_path,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "route_id": self.route_id,
            "current": self.current.to_dict(),
            "destination": self.destination.to_dict(),
            "route_node_ids": list(self.node_ids),
            "distance_m": round(self.distance_m, 1),
            "overall_direction": self.overall_direction,
            "steps": [step.to_dict() for step in self.steps],
            "distance_note": self.distance_note,
            "map_path": str(self.map_path.resolve()) if self.map_path else None,
        }


@dataclass(frozen=True)
class FloorMap:
    building: str
    floor: str
    title: str
    image_path: Path
    facility_names: tuple[str, ...]
