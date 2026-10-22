from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (root / path).resolve()


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class AppSettings:
    project_root: Path
    skills_root: Path
    dental_skill_file: Path
    floor_map_guide: Path
    search_script: Path
    facility_graph: Path
    map_renderer_script: Path
    generated_maps_dir: Path
    search_top_k: int
    open_images: bool
    @classmethod
    def load(cls, project_root: Path) -> "AppSettings":
        root = project_root.resolve()
        load_dotenv(root / ".env")

        default_search = root / "skills" / "dental-care" / "scripts" / "search.py"
        default_graph = root / "data" / "facility_graph.json"
        skills_root = _resolve(root, os.getenv("SKILLS_ROOT", "skills"))
        dental_skill_dir = skills_root / "dental-care"

        return cls(
            project_root=root,
            skills_root=skills_root,
            dental_skill_file=dental_skill_dir / "SKILL.md",
            floor_map_guide=dental_skill_dir
            / "references"
            / "aoba-dental-floor-maps"
            / "README.md",
            search_script=_resolve(
                root,
                os.getenv("DENTAL_SEARCH_SCRIPT", str(default_search)),
            ),
            facility_graph=_resolve(
                root,
                os.getenv("FACILITY_GRAPH_FILE", str(default_graph)),
            ),
            map_renderer_script=_resolve(
                root,
                os.getenv("MAP_RENDERER_SCRIPT", "scripts/render_route_map.py"),
            ),
            generated_maps_dir=_resolve(
                root,
                os.getenv("GENERATED_MAPS_DIR", "runtime/maps"),
            ),
            search_top_k=int(os.getenv("RAG_TOP_K", "5")),
            open_images=_env_bool("OPEN_MAP_VIEWER", os.name == "nt"),
        )

    def validation_errors(self) -> list[str]:
        required = {
            "dental-care SKILL.md": self.dental_skill_file,
            "floor-map README": self.floor_map_guide,
            "RAG search.py": self.search_script,
            "facility graph": self.facility_graph,
            "map renderer": self.map_renderer_script,
        }
        errors = [
            f"{label} が見つかりません: {path}"
            for label, path in required.items()
            if not path.is_file()
        ]
        if not 1 <= self.search_top_k <= 20:
            errors.append("RAG_TOP_K は1〜20で指定してください。")
        return errors
