from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from hospital_agents.errors import SearchScriptError


class LlamaIndexSearchService:
    """Adapter for the existing search.py --query ... --top-k ... contract."""

    def __init__(self, search_script: Path, *, timeout_seconds: int = 120) -> None:
        self.search_script = search_script.resolve()
        self.timeout_seconds = timeout_seconds

    def search(self, question: str, *, top_k: int = 5) -> str:
        question = question.strip()
        if not question:
            raise SearchScriptError("検索質問が空です。")
        if not 1 <= top_k <= 20:
            raise SearchScriptError("top_k は1〜20で指定してください。")
        if not self.search_script.is_file():
            raise SearchScriptError(
                "LlamaIndex検索スクリプトが見つかりません。\n"
                f"確認した場所: {self.search_script}"
            )

        command = [
            sys.executable,
            "-X",
            "utf8",
            str(self.search_script),
            "--query",
            question,
            "--top-k",
            str(top_k),
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                cwd=str(self.search_script.parent),
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise SearchScriptError(
                f"search.py が {self.timeout_seconds} 秒以内に完了しませんでした。"
            ) from error
        except OSError as error:
            raise SearchScriptError(f"search.py を起動できませんでした: {error}") from error

        if completed.returncode != 0:
            detail = completed.stderr.strip() or "標準エラー出力なし"
            raise SearchScriptError(
                f"search.py が終了コード {completed.returncode} で失敗しました。\n{detail}"
            )

        result = completed.stdout.strip()
        if not result:
            raise SearchScriptError("search.py から検索結果が返されませんでした。")
        return result
