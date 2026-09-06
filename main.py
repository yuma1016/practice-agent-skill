import asyncio
#非同期処理を実行する
from pathlib import Path
#ファイルやフォルダのpathを読み込む

from dotenv import load_dotenv
from agent_framework import Agent, SkillsProvider
from agent_framework.openai import OpenAIChatClient


# main.pyが置かれているプロジェクトの場所
BASE_DIR = Path(__file__).resolve().parent
#ファイルの場所を取得し、絶対パスにする、そして親フォルダを取得
# プロジェクト直下の.envを読み込む
load_dotenv(BASE_DIR / ".env")
#BASE_DIRの中の.envを読み込む

async def main() -> None:
#非同期処理を含む関数だと定義
    # skillsフォルダからファイルベースSkillを探す
    skills_provider = SkillsProvider.from_paths(
    #フォルダからSKiLLを見つけ変数に格納
        skill_paths=BASE_DIR / "skills",
    #検索するフォルダ、ファイルを指定
    )

    # OpenAIを利用するエージェントを作成
    agent = Agent(
        client=OpenAIChatClient(),
        name="DentalCareAgent",
        instructions=(
            "あなたは日本語で回答するアシスタントです。"
            "ユーザーの質問に関連するSkillがある場合は、"
            "必ずそのSkillを読み込んで、Skillの指示に従って回答してください。"
        ),
        context_providers=[skills_provider],
    #skill providerをAgentに渡す
    )

    question = "虫歯にならないためには？"
    #質問を変数の保存
    print(f"質問：{question}")
    #質問を表示
    print("回答を生成しています...\n")
    #処理中のメッセージを表示

    result = await agent.run(question)
    #非同期処理の結果が返ってくるまで待機する

    print("回答：")
    print(result)
    #生成された回答を表示


if __name__ == "__main__":
#実行されたか確認
    asyncio.run(main())
#非同期関数を実行