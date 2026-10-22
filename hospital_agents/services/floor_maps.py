from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path

from hospital_agents.models import FloorMap


def _normalize_for_match(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"\s+", "", normalized)


def _facility_aliases(facility_name: str) -> set[str]:
    aliases = {_normalize_for_match(facility_name)}
    for part in re.split(r"[／/・、]", facility_name):
        normalized_part = _normalize_for_match(part)
        if len(normalized_part) >= 3:
            aliases.add(normalized_part)
        name_without_room_number = re.sub(
            r"[ab]\d{3}(?:[〜~-][ab]?\d{3})?",
            "",
            normalized_part,
            flags=re.IGNORECASE,
        ).strip()
        if len(name_without_room_number) >= 3:
            aliases.add(name_without_room_number)
    return aliases


def load_floor_maps(guide_path: Path) -> list[FloorMap]:
    """Load the original dental-care floor-map README contract."""

    guide_path = guide_path.resolve()
    if not guide_path.is_file():
        return []

    guide_text = guide_path.read_text(encoding="utf-8")
    section_pattern = re.compile(
        r"^##\s+(?P<building>[AB])棟\s*(?P<floor>\d+)F\s*[^\n]*\n"
        r"(?P<body>.*?)(?=^---\s*$|^##\s+|\Z)",
        flags=re.MULTILINE | re.DOTALL,
    )
    image_pattern = re.compile(
        r"!\[(?P<title>[^\]]+)]\((?P<path>[^)]+\.png)\)",
        flags=re.IGNORECASE,
    )
    floor_maps: list[FloorMap] = []
    maps_root = (guide_path.parent / "maps").resolve()

    for section_match in section_pattern.finditer(guide_text):
        body = section_match.group("body")
        image_match = image_pattern.search(body)
        if image_match is None:
            continue
        candidate_path = (guide_path.parent / image_match.group("path")).resolve()
        try:
            candidate_path.relative_to(maps_root)
        except ValueError:
            continue
        if not candidate_path.is_file():
            continue

        facility_names: list[str] = []
        for line in body.splitlines():
            if not line.startswith("|"):
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if not cells or cells[0] in ("施設", "---") or set(cells[0]) == {"-"}:
                continue
            facility_names.append(cells[0])

        floor_maps.append(
            FloorMap(
                building=section_match.group("building"),
                floor=section_match.group("floor"),
                title=image_match.group("title"),
                image_path=candidate_path,
                facility_names=tuple(facility_names),
            )
        )
    return floor_maps


def find_floor_maps_in_researcher_output(
    researcher_output: str,
    floor_maps: list[FloorMap],
) -> list[FloorMap]:
    normalized_output = _normalize_for_match(researcher_output)
    image_path_matches: set[tuple[str, str]] = set()
    room_number_matches: set[tuple[str, str]] = set()
    building_floor_matches: set[tuple[str, str]] = set()
    mentioned_buildings: set[str] = set()
    facility_aliases_by_floor: dict[tuple[str, str], set[str]] = {}
    floors_by_facility_alias: dict[str, set[tuple[str, str]]] = {}

    for floor_map in floor_maps:
        key = (floor_map.building, floor_map.floor)
        aliases = {
            alias
            for facility_name in floor_map.facility_names
            for alias in _facility_aliases(facility_name)
        }
        facility_aliases_by_floor[key] = aliases
        for alias in aliases:
            floors_by_facility_alias.setdefault(alias, set()).add(key)

    matched_facility_aliases: list[tuple[str, tuple[str, str]]] = []
    for floor_map in floor_maps:
        building = floor_map.building.casefold()
        floor = floor_map.floor
        key = (floor_map.building, floor_map.floor)
        if f"{building}棟" in normalized_output:
            mentioned_buildings.add(floor_map.building)
        if floor_map.image_path.name.casefold() in normalized_output:
            image_path_matches.add(key)
        if any(
            marker in normalized_output
            for marker in (f"{building}棟{floor}f", f"{building}棟{floor}階")
        ):
            building_floor_matches.add(key)
        if re.search(
            rf"(?<![a-z0-9]){re.escape(building)}{re.escape(floor)}\d{{2}}(?!\d)",
            normalized_output,
            flags=re.IGNORECASE,
        ):
            room_number_matches.add(key)
        matched_facility_aliases.extend(
            (alias, key)
            for alias in facility_aliases_by_floor[key]
            if alias in normalized_output
        )

    def maps_for(keys: set[tuple[str, str]]) -> list[FloorMap]:
        return [
            floor_map
            for floor_map in floor_maps
            if (floor_map.building, floor_map.floor) in keys
        ]

    if image_path_matches:
        return maps_for(image_path_matches)
    if room_number_matches:
        return maps_for(room_number_matches)

    unique_facility_matches = {
        key
        for alias, key in matched_facility_aliases
        if len(floors_by_facility_alias[alias]) == 1
    }
    if unique_facility_matches:
        return maps_for(unique_facility_matches)
    if building_floor_matches:
        return maps_for(building_floor_matches)
    if matched_facility_aliases:
        minimum_floor_count = min(
            len(floors_by_facility_alias[alias])
            for alias, _ in matched_facility_aliases
        )
        return maps_for(
            {
                key
                for alias, key in matched_facility_aliases
                if len(floors_by_facility_alias[alias]) == minimum_floor_count
            }
        )

    return maps_for(
        {
            (floor_map.building, floor_map.floor)
            for floor_map in floor_maps
            if floor_map.building in mentioned_buildings
        }
    )


def format_floor_map_output(floor_maps: list[FloorMap], project_root: Path) -> str:
    output_lines = ["該当するフロアマップです。"]
    for floor_map in floor_maps:
        try:
            display_path = floor_map.image_path.relative_to(project_root).as_posix()
        except ValueError:
            display_path = str(floor_map.image_path)
        output_lines.extend(
            (
                "",
                f"### {floor_map.title}",
                "",
                f"![{floor_map.title}]({display_path})",
                "",
                f"画像ファイル: `{display_path}`",
            )
        )
    return "\n".join(output_lines)


def show_images(image_paths: list[Path]) -> None:
    if not hasattr(os, "startfile"):
        return
    for image_path in image_paths:
        try:
            os.startfile(str(image_path))  # type: ignore[attr-defined]
        except OSError as error:
            print(f"画像を開けませんでした: {image_path} ({error})")
