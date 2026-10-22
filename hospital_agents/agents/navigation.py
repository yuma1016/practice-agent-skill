from __future__ import annotations

from typing import Annotated

from agent_framework import Agent, FunctionInvocationContext, tool
from pydantic import Field

from hospital_agents.navigation_contract import (
    COMMIT_NAVIGATION_TOOL_NAME,
    RAG_SESSION_STATE_KEY,
    SEARCH_FACILITY_TOOL_NAME,
)
from hospital_agents.services.rag import LlamaIndexSearchService


def create_navigation_tools(
    rag: LlamaIndexSearchService,
    *,
    top_k: int = 5,
) -> list[object]:
    @tool(name=SEARCH_FACILITY_TOOL_NAME, approval_mode="never_require")
    def search_facility(
        question: Annotated[
            str,
            Field(
                description=(
                    "目的地候補の正式名称、棟、階、部屋番号、説明を施設資料から検索する質問。"
                )
            ),
        ],
        ctx: FunctionInvocationContext,
    ) -> str:
        """Search facility information through the existing LlamaIndex search.py."""

        result = rag.search(question, top_k=top_k)
        if ctx.session is not None:
            ctx.session.state[RAG_SESSION_STATE_KEY] = {
                "query": question,
                "result": result[:100_000],
            }
        return result

    @tool(name=COMMIT_NAVIGATION_TOOL_NAME, approval_mode="never_require")
    def commit_navigation(
        current_location: Annotated[
            str,
            Field(description="利用者が確認した現在地。棟、階、施設名を含める。"),
        ],
        destination: Annotated[
            str,
            Field(description="RAG検索で確認した目的地の正式な施設名。"),
        ],
    ) -> str:
        """Commit confirmed locations; middleware performs the actual route and map work."""

        return (
            "現在地と目的地を受け付けました。"
            f" current={current_location}, destination={destination}"
        )

    return [search_facility, commit_navigation]


def create_navigation_agent(
    client: object,
    rag: LlamaIndexSearchService,
    route_middleware: object,
    *,
    top_k: int = 5,
) -> Agent:
    return Agent(
        client=client,
        name="HospitalNavigator",
        description="院内施設を検索し、確認済みの現在地から目的地まで案内します。",
        instructions=(
            "あなたは院内案内担当です。ユーザーの発話から目的地候補を抽出してください。"
            "目的地については、必ず最初にsearch_facility Toolで施設資料を検索してください。"
            "検索結果にない施設名、棟、階、部屋番号を推測してはいけません。"
            "現在地が不明なら、棟・階・近くの部屋や目印を一つずつ短く質問してください。"
            "目的地が曖昧、または複数候補なら、検索結果を示してユーザーに選択を求めてください。"
            "現在地と目的地が両方確定した場合だけcommit_navigationを呼び出してください。"
            "commit_navigationの結果がstatus=okなら、距離、最初の方角、steps、地図パスを"
            "日本語で簡潔に案内してください。status=needs_inputまたはerrorなら、"
            "その理由を説明し、不足情報だけを質問してください。"
        ),
        tools=create_navigation_tools(rag, top_k=top_k),
        middleware=[route_middleware],
    )
