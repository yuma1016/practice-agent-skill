import asyncio
from pathlib import Path

from dotenv import load_dotenv
from agent_framework import (
    Agent,
    AgentResponseUpdate,
    SkillsProvider,
)
from agent_framework.openai import OpenAIChatClient
from agent_framework.orchestrations import (
    GroupChatBuilder,
    GroupChatState,
)


# group_chat.pyが置かれているプロジェクトフォルダ
BASE_DIR = Path(__file__).resolve().parent

# プロジェクト直下の.envを読み込む
load_dotenv(BASE_DIR / ".env")


def select_next_speaker(state: GroupChatState) -> str:
    """
    Group Chatで次に発言するAgentを決める。

    0回目：Researcher
    1回目：Writer
    """

    if state.current_round == 0:
        return "Researcher"

    return "Writer"


def writer_has_finished(conversation) -> bool:
    """
    Writerが1回発言したらGroup Chatを終了する。
    """

    for message in conversation:
        author_name = getattr(message, "author_name", None)

        if author_name == "Writer":
            return True

    return False


async def main() -> None:
    # skillsフォルダからファイルベースSkillを探す
    skills_provider = SkillsProvider.from_paths(
        skill_paths=BASE_DIR / "skills",

        # 開発中はSKILL.mdやCSVの変更を毎回反映させる
        disable_caching=True,

        # 自分で作成したローカルSkillの読み取りを許可する
        disable_load_skill_approval=True,
        disable_read_skill_resource_approval=True,
    )

    # OpenAIのAPIを使用するクライアント
    client = OpenAIChatClient()

    # SkillとCSVを使用して情報を調査するAgent
    researcher = Agent(
        client=client,
        name="Researcher",
        description=(
            "虫歯予防のSkillとCSVを使用して、"
            "質問に関係する情報を調査する担当です。"
        ),
        instructions=(
            "あなたは虫歯予防について調査するResearcherです。"
            "質問に関係するSkillを必ず読み込んでください。"
            "Skillに参照ファイルが指定されている場合は、"
            "read_skill_resourceを使ってCSVを読み込んでください。"
            "CSVに書かれている情報を根拠として、"
            "Writer向けの調査結果を日本語で作成してください。"
            "使用したrecord_idも必ず明記してください。"
            "この段階では文章をきれいにまとめることより、"
            "根拠を正確に伝えることを優先してください。"
        ),
        context_providers=[
            skills_provider,
        ],
    )

    # Researcherの結果を読みやすい文章にするAgent
    writer = Agent(
        client=client,
        name="Writer",
        description=(
            "Researcherの調査結果を、"
            "ユーザー向けの読みやすい日本語にまとめる担当です。"
        ),
        instructions=(
    "あなたは一般の利用者向けに文章を作成するWriterです。"
    "会話履歴にあるResearcherの調査メモを使用して、"
    "ユーザーへの最終回答を日本語で作成してください。"

    "Researcherが提示していない医学情報を追加しないでください。"
    "Researcherの調査メモをそのままコピーするのではなく、"
    "複数の情報を整理して自然な文章にしてください。"

    "最終回答は必ず次の構成にしてください。"

    "1. 最初に質問への結論を1〜2文で書く"
    "2. 実践することを箇条書きで示す"
    "3. 注意事項を短く説明する"
    "4. 最後に使用したrecord_idをまとめる"

    "最後は必ず次の形式にしてください。"
    "参照データ：C001, C002"
)
    )

    # Group Chatワークフローを作成する
    workflow = GroupChatBuilder(
        participants=[
            researcher,
            writer,
        ],

        # Researcher→Writerの順番を決める
        selection_func=select_next_speaker,

        # Writerが発言したら終了する
        termination_condition=writer_has_finished,

        # Researcherの回答は途中経過として出力する
        intermediate_output_from=[
            researcher,
        ],

        # Writerの回答を最終出力にする
        output_from=[
            writer,
        ],
    ).build()

    question = "虫歯にならないためには？"

    print(f"質問：{question}")
    print("Group Chatを実行しています...\n")

    # ストリーミング中の文章を保存するリスト
    researcher_parts = []
    writer_parts = []

    # ストリーミング完了後の文章
    researcher_complete = ""
    writer_complete = ""

    # Group Chatを実行する
    async for event in workflow.run(question, stream=True):
        if event.type not in ("intermediate", "output"):
            continue

        data = event.data

        # Agentの回答が少しずつ返ってきた場合
        if isinstance(data, AgentResponseUpdate):
            text = data.text or ""
            author_name = data.author_name

            # author_nameが空の場合はイベントの種類から判断する
            if author_name is None:
                if event.type == "intermediate":
                    author_name = "Researcher"
                elif event.type == "output":
                    author_name = "Writer"

            if author_name == "Researcher":
                researcher_parts.append(text)

            elif author_name == "Writer":
                writer_parts.append(text)

        # 完成したメッセージがリストで返ってきた場合
        elif isinstance(data, (list, tuple)):
            for message in data:
                author_name = getattr(
                    message,
                    "author_name",
                    None,
                )
                text = getattr(
                    message,
                    "text",
                    "",
                )

                if author_name == "Researcher" and text:
                    researcher_complete = text

                elif author_name == "Writer" and text:
                    writer_complete = text

        # 完成したメッセージが1件だけ返ってきた場合
        else:
            author_name = getattr(
                data,
                "author_name",
                None,
            )
            text = getattr(
                data,
                "text",
                "",
            )

            if author_name == "Researcher" and text:
                researcher_complete = text

            elif author_name == "Writer" and text:
                writer_complete = text

    # 完成したメッセージがあればそれを優先する
    researcher_text = (
        researcher_complete
        if researcher_complete
        else "".join(researcher_parts)
    ).strip()

    writer_text = (
        writer_complete
        if writer_complete
        else "".join(writer_parts)
    ).strip()

    # Researcherの調査結果を表示する
    if researcher_text:
        print("===== Researcherの調査結果 =====")
        print(researcher_text)
        print()
    else:
        print("Researcherの調査結果を取得できませんでした。\n")

    # Writerの最終回答を表示する
    if writer_text:
        print("===== Writerの最終回答 =====")
        print(writer_text)
    else:
        print("Writerの最終回答を取得できませんでした。")


if __name__ == "__main__":
    asyncio.run(main())