import asyncio
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv
from agent_framework import (
    Agent,
    AgentResponseUpdate,
    SkillsProvider,ToolApprovalMiddleware
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

def load_skill_instructions() -> str:
    """SKILL.mdを読み込み、文字列として返す。"""

    skill_file = (
        BASE_DIR
        / "skills"
        / "dental-care"
        / "SKILL.md"
    )
    skill_instructions = skill_file.read_text(
        encoding="utf-8"
    ).strip()
    return skill_instructions


def select_next_speaker(state: GroupChatState) -> str:
    """奇数ラウンドはResearcher、偶数ラウンドはWriterを選ぶ。"""

    # current_roundは0から始まるため、表示用には1を足す
    round_number = state.current_round + 1

    if round_number % 2 == 1:
        return "Researcher"

    return "Writer"


def reached_maximum_rounds(conversation) -> bool:
    """ResearcherとWriterの発言が合計4回になったら終了する。"""

    assistant_message_count = sum(
        1
        for message in conversation
        if message.role == "assistant"
    )

    return assistant_message_count >= 4
def search_documents(
    question: str,
    top_k: int = 5,
) -> str:
    """Group Chat開始前にsearch.pyを実行する。"""

    search_script = (
        BASE_DIR
        / "skills"
        / "dental-care"
        / "scripts"
        / "search.py"
    )

    if not search_script.exists():
        raise FileNotFoundError(
            "search.pyが見つかりません。\n"
            f"確認した場所: {search_script}"
        )

    command = [
        sys.executable,
        str(search_script),
        "--query",
        question,
        "--top-k",
        str(top_k),
    ]

    print("LlamaIndexで資料を検索しています...")

    completed_process = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        cwd=str(search_script.parent),
    )

    if completed_process.returncode != 0:
        raise RuntimeError(
            "search.pyの実行に失敗しました。\n"
            f"{completed_process.stderr}"
        )

    search_result = completed_process.stdout.strip()

    if not search_result:
        raise RuntimeError(
            "search.pyから検索結果が返されませんでした。"
        )

    print("資料検索が完了しました。\n")

    return search_result
async def main() -> None:
    # OpenAIクライアント
    skills_provider = SkillsProvider.from_paths(
    #フォルダからSKiLLを見つけ変数に格納
        skill_paths=BASE_DIR / "skills",
    # 開発中はSKILL.mdやCSVの変更を毎回反映させる
        disable_caching=True,
    )
    approval_middleware = ToolApprovalMiddleware(
    #Agentを実行するのに実行を許可するか確認
        auto_approval_rules=[
    #どのツールを用いてよいのかを指定
            SkillsProvider.read_only_tools_auto_approval_rule
        ],
    #読み取り専用ツールを自動承認するルールをMiddlewareに引き渡す
    )
    client = OpenAIChatClient()

    # 資料検索と検証を担当
    researcher = Agent(
    client=client,
    name="Researcher",
    description="SKILL.mdと検索済みの歯科資料を調査し、根拠を整理します。",
    instructions=(
        "あなたは歯科資料の調査担当です。"
        "ユーザーメッセージには、LlamaIndexによる検索結果が含まれています。"
        "検索結果のresultsにあるcontentだけを根拠にしてください。"
        "最初の発言から具体的な調査結果を提示してください。"
        "「これから調べます」「少々お待ちください」などとは回答しないでください。"
        "質問に関連するSkillがある場合は、必ずそのSkillを読み込んでください。"
        "資料にない時間、回数、効果などを追加しないでください。"
        "根拠として使用したsourceを必ず列挙してください。"
        "Writerがすでに回答している場合は、その回答と検索結果を比較し、"
        "資料にない記述や誤りを指摘してください。"
    ),
        context_providers=[skills_provider],
    #skill providerをAgentに渡す
         middleware=[approval_middleware],
    #middlewareをAgentに引き渡す
)

    # Researcherの内容を文章化
    writer = Agent(
    client=client,
    name="Writer",
    description="Researcherの調査結果から最終回答を作成します。",
    instructions=(
        "あなたは回答作成担当です。"
        "Researcherが提示した検索結果と調査結果だけを根拠にしてください。"
        "資料に書かれていない時間、頻度、数値、効果を追加しないでください。"
        "根拠がない内容は削除してください。"
        "最初の発言では回答案を作成してください。"
        "Researcherによる確認結果がある場合は、指摘を反映して修正してください。"
        "回答の最後に、実際のsourceファイル名を列挙してください。"
        "『一般的なガイドライン』のような曖昧な出典名は使わないでください。"
    ),
)

    # Group Chatを作成
    workflow = GroupChatBuilder(
        participants=[
            researcher,
            writer,
        ],
    

        # Researcher、Writerの合計発言数が4回で終了
        termination_condition=reached_maximum_rounds,

        # 奇数Researcher、偶数Writer
        selection_func=select_next_speaker,

        # 両方の発言をストリーミング出力する
        intermediate_output_from=[
            researcher,
            writer,
        ],
    ).build()

    question = "虫歯にならないためには？"

    print(f"質問：{question}")

    # Group Chatを開始する前に資料を検索
    search_result = search_documents(
        question=question,
        top_k=5,
    )
    skill_instructions=load_skill_instructions()

    # 質問と検索結果をResearcherへ渡す
    task = (
        "以下の質問に、検索結果だけを根拠として回答してください。\n\n"
        f"【ユーザーの質問】\n{question}\n\n"
        f"【LlamaIndexによる検索結果】\n{search_result}\n\n"
        f"【SKILL.md】\n{skill_instructions}\n\n"
        "【必須ルール】\n"
        "- Researcherは最初の発言から検索結果を整理する\n"
        "- 「これから調べます」とは回答しない\n"
        "- results内のcontentだけを根拠にする\n"
        "- 資料にない数値、時間、頻度、効果を追加しない\n"
        "- 使用したsourceを正確に記載する\n"
    )

    print("Group Chatを実行しています...\n")

    current_author: str | None = None
    latest_writer_chunks: list[str] = []

    stream = workflow.run(
        task,
        stream=True,
    )

    async for event in stream:
        if event.type not in ("intermediate", "output"):
            continue

        data = event.data

        if not isinstance(data, AgentResponseUpdate):
            continue

        author_name = data.author_name

        if author_name not in ("Researcher", "Writer"):
            continue

        text_chunk = data.text or ""

        if author_name != current_author:
            if current_author is not None:
                print("\n")

            print(f"===== {author_name} =====")

            if author_name == "Writer":
                latest_writer_chunks = []

            current_author = author_name

        print(
            text_chunk,
            end="",
            flush=True,
        )

        if author_name == "Writer":
            latest_writer_chunks.append(text_chunk)

    await stream.get_final_response()

    final_answer = "".join(latest_writer_chunks).strip()

    print("\n\n===== 最終回答 =====")

    if final_answer:
        print(final_answer)
    else:
        print("Writerの最終回答を取得できませんでした。")

if __name__ == "__main__":
    asyncio.run(main())