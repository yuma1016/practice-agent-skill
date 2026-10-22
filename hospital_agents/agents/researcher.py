from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from agent_framework import (
    Agent,
    AgentExecutor,
    AgentResponseUpdate,
    AgentSession,
    SkillsProvider,
    ToolApprovalMiddleware,
)
from agent_framework.orchestrations import GroupChatBuilder, GroupChatState

from hospital_agents.errors import ConfigurationError
from hospital_agents.services.rag import LlamaIndexSearchService


def create_researcher_agent(
    client: object,
    skills_provider: SkillsProvider,
    approval_middleware: ToolApprovalMiddleware,
) -> Agent:
    return Agent(
        client=client,
        name="Researcher",
        description="SKILL.mdと検索済みの歯科資料を調査し、根拠を整理します。",
        instructions=(
            "あなたは歯科資料の調査担当です。"
            "ユーザーメッセージには、LlamaIndexによる検索結果が含まれています。"
            "今回と過去の検索結果のresultsにあるcontentだけを根拠にしてください。"
            "最初の発言から具体的な調査結果を提示してください。"
            "『これから調べます』『少々お待ちください』とは回答しないでください。"
            "質問に関連するSkillがある場合は、そのSkillを読み込んでください。"
            "資料にない時間、回数、効果などを追加しないでください。"
            "根拠として使用したsourceを必ず列挙してください。"
            "施設名、部屋名、A棟、B棟、階数が回答に含まれる場合は、"
            "フロアマップ資料に記載された対応画像の相対パスも正確に列挙してください。"
        ),
        context_providers=[skills_provider],
        middleware=[approval_middleware],
    )


def _select_researcher(_state: GroupChatState) -> str:
    return "Researcher"


class ResearcherRunner:
    def __init__(
        self,
        agent: Agent,
        rag: LlamaIndexSearchService,
        skill_file: Path,
        *,
        top_k: int = 5,
    ) -> None:
        self.agent = agent
        self.rag = rag
        self.skill_file = skill_file.resolve()
        self.top_k = top_k

    def _load_skill_instructions(self) -> str:
        if not self.skill_file.is_file():
            raise ConfigurationError(f"SKILL.mdが見つかりません: {self.skill_file}")
        return self.skill_file.read_text(encoding="utf-8").strip()

    async def answer(
        self,
        question: str,
        session: AgentSession,
        emit: Callable[[str], None],
    ) -> str:
        search_result = self.rag.search(question, top_k=self.top_k)
        skill_instructions = self._load_skill_instructions()
        task = (
            "以下の質問に、今回と過去の検索結果だけを根拠として回答してください。\n\n"
            f"【ユーザーの質問】\n{question}\n\n"
            f"【LlamaIndexによる今回の検索結果】\n{search_result}\n\n"
            f"【SKILL.md】\n{skill_instructions}\n\n"
            "【必須ルール】\n"
            "- 最初の発言から検索結果を整理する\n"
            "- 『これから調べます』とは回答しない\n"
            "- 今回と過去のresults内のcontentだけを根拠にする\n"
            "- 資料にない数値、時間、頻度、効果を追加しない\n"
            "- 使用したsourceを正確に記載する\n"
            "- 施設名、部屋名、棟、階が含まれる場合は画像の相対パスも記載する\n"
        )

        researcher_executor = AgentExecutor(self.agent, session=session)
        workflow = GroupChatBuilder(
            participants=[researcher_executor],
            max_rounds=1,
            selection_func=_select_researcher,
            intermediate_output_from=[researcher_executor],
        ).build()
        chunks: list[str] = []
        stream = workflow.run(task, stream=True)
        async for event in stream:
            if event.type not in ("intermediate", "output"):
                continue
            data = event.data
            if not isinstance(data, AgentResponseUpdate):
                continue
            if data.author_name != "Researcher":
                continue
            text_chunk = data.text or ""
            if text_chunk:
                emit(text_chunk)
                chunks.append(text_chunk)
        await stream.get_final_response()
        output = "".join(chunks).strip()
        if not output:
            raise RuntimeError("Researcherの回答を取得できませんでした。")
        return output
