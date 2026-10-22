from __future__ import annotations

import unittest
from pathlib import Path

from agent_framework import AgentExecutor, SkillsProvider, ToolApprovalMiddleware
from agent_framework.openai import OpenAIChatClient
from agent_framework.orchestrations import GroupChatBuilder

from hospital_agents.agents.navigation import create_navigation_agent, create_navigation_tools
from hospital_agents.agents.researcher import create_researcher_agent
from hospital_agents.middleware.navigation import NavigationExecutionMiddleware
from hospital_agents.services.map_renderer import RouteMapRenderer
from hospital_agents.services.rag import LlamaIndexSearchService
from hospital_agents.services.routing import RouteEngine


ROOT = Path(__file__).resolve().parents[1]


class FrameworkApiSmokeTests(unittest.TestCase):
    def test_current_agent_framework_constructors(self) -> None:
        client = OpenAIChatClient(model="gpt-4.1-mini", api_key="test-only")
        rag = LlamaIndexSearchService(ROOT / "scripts" / "demo_search.py")
        route_engine = RouteEngine(ROOT / "data" / "facility_graph.json")
        renderer = RouteMapRenderer(
            ROOT / "scripts" / "render_route_map.py",
            ROOT / "data" / "facility_graph.json",
            ROOT / "runtime" / "test-maps",
        )
        route_middleware = NavigationExecutionMiddleware(route_engine, renderer)
        navigator = create_navigation_agent(client, rag, route_middleware)
        self.assertEqual(navigator.name, "HospitalNavigator")

        tools = create_navigation_tools(rag)
        self.assertEqual(
            {tool.name for tool in tools},
            {"search_facility", "commit_navigation"},
        )

        skills = SkillsProvider.from_paths(ROOT / "skills", disable_caching=True)
        approvals = ToolApprovalMiddleware(
            auto_approval_rules=[SkillsProvider.read_only_tools_auto_approval_rule]
        )
        researcher = create_researcher_agent(client, skills, approvals)
        executor = AgentExecutor(researcher, session=researcher.create_session())
        workflow = GroupChatBuilder(
            participants=[executor],
            max_rounds=1,
            selection_func=lambda _state: "Researcher",
            intermediate_output_from=[executor],
        ).build()
        self.assertIsNotNone(workflow)


if __name__ == "__main__":
    unittest.main()
