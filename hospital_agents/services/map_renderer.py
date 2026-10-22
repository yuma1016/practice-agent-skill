from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from hospital_agents.errors import MapRenderError
from hospital_agents.models import RouteResult


class RouteMapRenderer:
    """Runs the one allow-listed Python renderer in a child process."""

    def __init__(
        self,
        renderer_script: Path,
        graph_file: Path,
        output_dir: Path,
        *,
        timeout_seconds: int = 30,
    ) -> None:
        self.renderer_script = renderer_script.resolve()
        self.graph_file = graph_file.resolve()
        self.output_dir = output_dir.resolve()
        self.timeout_seconds = timeout_seconds

    def render(self, route: RouteResult) -> Path:
        if not self.renderer_script.is_file():
            raise MapRenderError(f"地図描画スクリプトが見つかりません: {self.renderer_script}")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.output_dir / f"route_{route.route_id}.png"
        payload = {
            "route_id": route.route_id,
            "route_node_ids": list(route.node_ids),
            "current_id": route.current.id,
            "destination_id": route.destination.id,
            "distance_m": route.distance_m,
        }
        command = [
            sys.executable,
            "-X",
            "utf8",
            str(self.renderer_script),
            "--graph",
            str(self.graph_file),
            "--output",
            str(output_path),
        ]
        try:
            completed = subprocess.run(
                command,
                input=json.dumps(payload, ensure_ascii=False),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                cwd=str(self.renderer_script.parent),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise MapRenderError(f"地図描画処理を実行できませんでした: {error}") from error

        if completed.returncode != 0:
            detail = completed.stderr.strip() or "標準エラー出力なし"
            raise MapRenderError(
                f"地図描画処理が終了コード {completed.returncode} で失敗しました。\n{detail}"
            )
        if not output_path.is_file():
            raise MapRenderError(f"地図描画処理が出力ファイルを作成しませんでした: {output_path}")
        return output_path
