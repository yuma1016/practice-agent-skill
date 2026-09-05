import asyncio
from pathlib import Path

from dotenv import load_dotenv
from agent_framework import Agent, SkillsProvider
from agent_framework.openai import OpenAIChatClient


# main.pyが置かれているプロジェクトの場所
BASE_DIR = Path(__file__).resolve().parent

# プロジェクト直下の.envを読み込む
load_dotenv(BASE_DIR / ".env")


async def main() -> None:
    # skillsフォルダからファイルベースSkillを探す
    skills_provider = SkillsProvider.from_paths(
        skill_paths=BASE_DIR / "skills",
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
    )

    question = "虫歯にならないためには？"

    print(f"質問：{question}")
    print("回答を生成しています...\n")

    result = await agent.run(question)

    print("回答：")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())