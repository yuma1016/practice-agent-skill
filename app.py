from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from agent_framework import AgentResponseUpdate, SkillsProvider, ToolApprovalMiddleware
from agent_framework.openai import OpenAIChatClient

from hospital_agents.agents.navigation import create_navigation_agent
from hospital_agents.agents.researcher import ResearcherRunner, create_researcher_agent
from hospital_agents.config import AppSettings
from hospital_agents.middleware.navigation import NavigationExecutionMiddleware
from hospital_agents.navigation_contract import ROUTE_SESSION_STATE_KEY
from hospital_agents.router import ChatMode, ConversationRouter
from hospital_agents.services.floor_maps import (
    find_floor_maps_in_researcher_output,
    format_floor_map_output,
    load_floor_maps,
    show_images,
)
from hospital_agents.services.map_renderer import RouteMapRenderer
from hospital_agents.services.rag import LlamaIndexSearchService
from hospital_agents.services.routing import RouteEngine


PROJECT_ROOT = Path(__file__).resolve().parent


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="歯科相談・院内案内エージェント")
    parser.add_argument(
        "--validate",
        action="store_true",
        help="ローカル依存ファイルの有無だけを確認して終了する",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="画像ビューアーを自動起動しない",
    )
    return parser.parse_args()


async def _run_navigation(agent: object, question: str, session: object) -> str:
    chunks: list[str] = []
    print("HospitalNavigator: ", end="", flush=True)
    stream = agent.run(question, stream=True, session=session)
    async for update in stream:
        if not isinstance(update, AgentResponseUpdate):
            continue
        text_chunk = update.text or ""
        if text_chunk:
            print(text_chunk, end="", flush=True)
            chunks.append(text_chunk)
    final_response = await stream.get_final_response()
    print()
    return "".join(chunks).strip() or final_response.text.strip()


def _validate(settings: AppSettings) -> int:
    errors = settings.validation_errors()
    if errors:
        print("構成エラー:")
        for error in errors:
            print(f"- {error}")
        print("\nMISSING_INPUTS_AGENT_APP.md を確認してください。")
        return 2
    print("ローカル依存ファイルの検証に成功しました。")
    return 0


async def _run_chat(args: argparse.Namespace, settings: AppSettings) -> int:
    rag = LlamaIndexSearchService(settings.search_script)
    route_engine = RouteEngine(settings.facility_graph)
    map_renderer = RouteMapRenderer(
        settings.map_renderer_script,
        settings.facility_graph,
        settings.generated_maps_dir,
    )
    navigation_middleware = NavigationExecutionMiddleware(route_engine, map_renderer)

    skills_provider = SkillsProvider.from_paths(
        skill_paths=settings.skills_root,
        disable_caching=True,
    )
    approval_middleware = ToolApprovalMiddleware(
        auto_approval_rules=[SkillsProvider.read_only_tools_auto_approval_rule]
    )
    model = os.getenv("OPENAI_CHAT_MODEL") or None
    client = OpenAIChatClient(model=model)

    researcher = create_researcher_agent(client, skills_provider, approval_middleware)
    navigator = create_navigation_agent(
        client,
        rag,
        navigation_middleware,
        top_k=settings.search_top_k,
    )
    researcher_runner = ResearcherRunner(
        researcher,
        rag,
        settings.dental_skill_file,
        top_k=settings.search_top_k,
    )
    researcher_session = researcher.create_session()
    navigation_session = navigator.create_session()
    floor_maps = load_floor_maps(settings.floor_map_guide)
    router = ConversationRouter()
    last_shown_route_id: str | None = None
    should_open = settings.open_images and not args.no_open

    print("歯科相談・院内案内チャットを開始します。")
    print("注意: 経路距離はフロア図から作成した未実測の推定値です。")
    print("/guide で案内モード、/research で資料相談、/reset で履歴消去、/exit で終了します。")

    while True:
        try:
            raw_input = input("\nあなた: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nチャットを終了します。")
            break
        if not raw_input:
            continue
        if raw_input.casefold() in {"/exit", "終了", "exit", "quit"}:
            print("チャットを終了します。")
            break
        if raw_input.casefold() == "/reset":
            researcher_session = researcher.create_session()
            navigation_session = navigator.create_session()
            router.set_mode(ChatMode.RESEARCH)
            last_shown_route_id = None
            print("会話履歴をリセットしました。")
            continue
        if raw_input.casefold().startswith("/guide"):
            router.set_mode(ChatMode.NAVIGATION)
            question = raw_input[len("/guide") :].strip()
            if not question:
                print("案内モードです。目的地を教えてください。")
                continue
        elif raw_input.casefold().startswith("/research"):
            router.set_mode(ChatMode.RESEARCH)
            question = raw_input[len("/research") :].strip()
            if not question:
                print("資料相談モードです。質問を入力してください。")
                continue
        else:
            question = raw_input

        try:
            mode = router.classify(question)
            if mode is ChatMode.RESEARCH:
                print("Researcher: ", end="", flush=True)
                output = await researcher_runner.answer(
                    question,
                    researcher_session,
                    lambda chunk: print(chunk, end="", flush=True),
                )
                print()
                matched = find_floor_maps_in_researcher_output(output, floor_maps)
                if matched:
                    print(format_floor_map_output(matched, settings.project_root))
                    if should_open:
                        show_images([item.image_path for item in matched])
            else:
                await _run_navigation(navigator, question, navigation_session)
                route_record = navigation_session.state.get(ROUTE_SESSION_STATE_KEY)
                if isinstance(route_record, dict):
                    route_id = str(route_record.get("route_id", ""))
                    map_path_text = route_record.get("map_path")
                    if route_id and route_id != last_shown_route_id and map_path_text:
                        map_path = Path(str(map_path_text))
                        print(f"生成した案内図: {map_path}")
                        if should_open:
                            show_images([map_path])
                        last_shown_route_id = route_id
        except Exception as error:
            print(f"回答の生成中にエラーが発生しました: {error}")

    return 0


def main() -> int:
    args = _parse_args()
    settings = AppSettings.load(PROJECT_ROOT)
    validation_result = _validate(settings)
    if validation_result != 0 or args.validate:
        return validation_result
    return asyncio.run(_run_chat(args, settings))


if __name__ == "__main__":
    raise SystemExit(main())
