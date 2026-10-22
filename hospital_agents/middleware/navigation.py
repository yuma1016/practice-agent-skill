from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from agent_framework import FunctionInvocationContext, FunctionMiddleware
from pydantic import BaseModel

from hospital_agents.errors import (
    LocationResolutionError,
    MapRenderError,
    RouteNotFoundError,
)
from hospital_agents.navigation_contract import (
    COMMIT_NAVIGATION_TOOL_NAME,
    RAG_SESSION_STATE_KEY,
    ROUTE_SESSION_STATE_KEY,
)
from hospital_agents.services.map_renderer import RouteMapRenderer
from hospital_agents.services.routing import RouteEngine


def _arguments_to_dict(arguments: BaseModel | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(arguments, BaseModel):
        return arguments.model_dump()
    return dict(arguments)


def _tool_result(status: str, message: str, **extra: Any) -> str:
    return json.dumps(
        {"status": status, "message": message, **extra},
        ensure_ascii=False,
    )


class NavigationExecutionMiddleware(FunctionMiddleware):
    """The deterministic trigger boundary for route calculation and map generation."""

    def __init__(self, route_engine: RouteEngine, map_renderer: RouteMapRenderer) -> None:
        self.route_engine = route_engine
        self.map_renderer = map_renderer

    async def process(
        self,
        context: FunctionInvocationContext,
        call_next: Callable[[], Awaitable[None]],
    ) -> None:
        if context.function.name != COMMIT_NAVIGATION_TOOL_NAME:
            await call_next()
            return

        arguments = _arguments_to_dict(context.arguments)
        current_text = str(arguments.get("current_location", "")).strip()
        destination_text = str(arguments.get("destination", "")).strip()
        if not current_text or not destination_text:
            context.result = _tool_result(
                "needs_input",
                "現在地と目的地の両方が必要です。",
            )
            return

        session = context.session
        search_record = session.state.get(RAG_SESSION_STATE_KEY) if session else None
        if not isinstance(search_record, Mapping):
            context.result = _tool_result(
                "needs_input",
                "目的地の施設情報を先にsearch_facilityで検索してください。",
            )
            return

        try:
            current = self.route_engine.resolve(current_text)
            destination = self.route_engine.resolve(destination_text)
            rag_output = str(search_record.get("result", ""))
            if not self.route_engine.destination_is_present_in_rag(destination, rag_output):
                context.result = _tool_result(
                    "needs_input",
                    "直前のRAG検索結果で目的地を確認できません。目的地を再検索してください。",
                    destination=destination.name,
                )
                return

            route = self.route_engine.calculate_between(current, destination)
            map_path = self.map_renderer.render(route)
            route = route.with_map_path(map_path)
        except LocationResolutionError as error:
            context.result = _tool_result("needs_input", str(error))
            return
        except (RouteNotFoundError, MapRenderError) as error:
            context.result = _tool_result("error", str(error))
            return

        await call_next()
        result = route.to_dict()
        context.result = json.dumps(result, ensure_ascii=False)
        if session is not None:
            session.state[ROUTE_SESSION_STATE_KEY] = result
