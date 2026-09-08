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
        description="LlamaIndexで歯科資料を検索し、根拠を整理します。",
        instructions=(
            "あなたは歯科資料の調査担当です。"
            "虫歯に関する質問ではdental-care Skillを読み込んでください。"
            "必ずscripts/search.pyをrun_skill_scriptで実行してください。"
            "検索時のqueryにはユーザーの質問を渡し、top_kは5にしてください。"
            "最初の発言では、検索結果を整理してください。"
            "Writerがすでに回答している場合は、検索結果とWriterの回答を比較し、"
            "誤り、不足、資料にない断定がないかを確認してください。"
            "使用したsourceを必ず示してください。"
        ),
        context_providers=[skills_provider],
        middleware=[approval_middleware],
    )

    # Researcherの内容を文章化
    writer = Agent(
        client=client,
        name="Writer",
        description="Researcherの調査結果から日本語の回答を作成します。",
        instructions=(
            "あなたは回答作成担当です。"
            "Researcherが提示した検索結果だけを根拠として回答してください。"
            "最初の発言では回答案を作成してください。"
            "Researcherによる確認結果がすでにある場合は、"
            "その指摘を反映した最終回答を作成してください。"
            "資料に書かれていない内容を追加しないでください。"
            "日本語で分かりやすく回答し、最後に使用資料を示してください。"
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
    print("Group Chatを実行しています...\n")

    current_author: str | None = None

    # 最後のWriterの発言を保存する
    latest_writer_chunks: list[str] = []

    stream = workflow.run(
        question,
        stream=True,
    )

    async for event in stream:
        if event.type not in ("intermediate", "output"):
            continue

        data = event.data

        if not isinstance(data, AgentResponseUpdate):
            continue

        author_name = data.author_name

        # オーケストレーターの終了メッセージは表示しない
        if author_name not in ("Researcher", "Writer"):
            continue

        text_chunk = data.text or ""

        # 発言者が切り替わったときに見出しを表示
        if author_name != current_author:
            if current_author is not None:
                print("\n")

            print(f"===== {author_name} =====")

            # Writerの新しい発言が始まったら、
            # 前回のWriter回答をリセットする
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

    # Workflowの終了処理を完了させる
    await stream.get_final_response()

    final_answer = "".join(
        latest_writer_chunks
    ).strip()

    print("\n\n===== 最終回答 =====")

    if final_answer:
        print(final_answer)
    else:
        print("Writerの最終回答を取得できませんでした。")


if __name__ == "__main__":
    asyncio.run(main())