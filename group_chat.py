import asyncio
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv
from agent_framework import (
    Agent,
    AgentResponseUpdate,
    FileSkill,
    FileSkillScript,
    SkillsProvider,
    ToolApprovalMiddleware,
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


def subprocess_script_runner(
    skill: FileSkill,
    script: FileSkillScript,
    args: dict | list[str] | None = None,
) -> str:
    """Skill内のPythonスクリプトを別プロセスで実行する。"""

    script_path = Path(script.full_path)

    # uvが使用しているPythonでsearch.pyを実行
    command = [
        sys.executable,
        str(script_path),
    ]

    if isinstance(args, dict):
        # {"query": "...", "top_k": 5}
        # ↓
        # --query "..." --top-k 5
        for key, value in args.items():
            option_name = f"--{key.replace('_', '-')}"

            if isinstance(value, bool):
                if value:
                    command.append(option_name)

            elif isinstance(value, list):
                for item in value:
                    command.extend(
                        [option_name, str(item)]
                    )

            elif value is not None:
                command.extend(
                    [option_name, str(value)]
                )

    elif isinstance(args, list):
        # ["虫歯にならないためには？", "5"]
        command.extend(str(value) for value in args)

    completed_process = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        cwd=str(script_path.parent),
    )

    if completed_process.returncode != 0:
        raise RuntimeError(
            "Skillスクリプトの実行に失敗しました。\n"
            f"{completed_process.stderr}"
        )

    return completed_process.stdout.strip()


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
    # ファイルベースSkillを読み込む
    skills_provider = SkillsProvider.from_paths(
        skill_paths=BASE_DIR / "skills",

        # references/カテゴリ/ファイルまで探索
        search_depth=3,

        # Pythonスクリプトの実行関数を登録
        script_runner=subprocess_script_runner,

        # 開発中はファイル変更を毎回反映
        disable_caching=True,
    )

    # search.pyは自分で作った信頼できるスクリプトなので、
    # run_skill_scriptを含むSkillツールを自動承認する
    approval_middleware = ToolApprovalMiddleware(
        auto_approval_rules=[
            SkillsProvider.all_tools_auto_approval_rule
        ],
    )

    # OpenAIクライアント
    client = OpenAIChatClient()

    # 資料検索と検証を担当
    researcher = Agent(
    client=client,
    name="Researcher",
    description="検索済みの歯科資料を調査し、根拠を整理します。",
    instructions=(
        "あなたは歯科資料の調査担当です。"
        "ユーザーメッセージには、質問とLlamaIndexによる検索結果が含まれています。"
        "検索結果のresultsにあるcontentだけを根拠にしてください。"
        "最初の発言から具体的な調査結果を提示してください。"
        "「これから調べます」「少々お待ちください」などとは回答しないでください。"
        "資料にない時間、回数、効果などを追加しないでください。"
        "根拠として使用したsourceを必ず列挙してください。"
        "Writerがすでに回答している場合は、その回答と検索結果を比較し、"
        "資料にない記述や誤りを指摘してください。"
    ),
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

    # 質問と検索結果をResearcherへ渡す
    task = (
        "以下の質問に、検索結果だけを根拠として回答してください。\n\n"
        f"【ユーザーの質問】\n{question}\n\n"
        f"【LlamaIndexによる検索結果】\n{search_result}\n\n"
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