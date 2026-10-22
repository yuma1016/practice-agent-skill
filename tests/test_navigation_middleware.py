from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from hospital_agents.middleware.navigation import NavigationExecutionMiddleware
from hospital_agents.navigation_contract import (
    COMMIT_NAVIGATION_TOOL_NAME,
    RAG_SESSION_STATE_KEY,
    ROUTE_SESSION_STATE_KEY,
)
from hospital_agents.services.map_renderer import RouteMapRenderer
from hospital_agents.services.routing import RouteEngine


ROOT = Path(__file__).resolve().parents[1]
GRAPH = ROOT / "data" / "facility_graph.json"
RENDERER = ROOT / "scripts" / "render_route_map.py"


class NavigationMiddlewareTests(unittest.TestCase):
    @staticmethod
    def _run_immediate(coroutine) -> None:
        """Drive this middleware coroutine without creating a Windows event loop.

        The test's call_next coroutine never suspends. This also lets restricted CI
        sandboxes test the middleware when asyncio's Windows self-pipe is unavailable.
        """
        try:
            coroutine.send(None)
        except StopIteration:
            return
        finally:
            coroutine.close()
        raise AssertionError("middleware unexpectedly suspended")

    @staticmethod
    def _temporary_output():
        # Some sandboxed Windows runners expose the OS temp directory to the parent
        # process but not to its child process. Keep this integration-test directory
        # below the project so render_route_map.py can write to it as well.
        test_runtime = ROOT / "runtime" / "middleware-tests"
        test_runtime.mkdir(parents=True, exist_ok=True)
        return tempfile.TemporaryDirectory(dir=test_runtime)

    def _middleware(self, output_dir: Path) -> NavigationExecutionMiddleware:
        engine = RouteEngine(GRAPH)
        renderer = RouteMapRenderer(RENDERER, GRAPH, output_dir)
        return NavigationExecutionMiddleware(engine, renderer)

    def test_commit_runs_renderer_only_after_rag_evidence(self) -> None:
        with self._temporary_output() as temp_dir:
            session = SimpleNamespace(
                state={
                    RAG_SESSION_STATE_KEY: {
                        "query": "初診相談室はどこ",
                        "result": "施設名: A棟1階 初診相談室",
                    }
                }
            )
            context = SimpleNamespace(
                function=SimpleNamespace(name=COMMIT_NAVIGATION_TOOL_NAME),
                arguments={
                    "current_location": "正面玄関",
                    "destination": "初診相談室",
                },
                session=session,
                result=None,
            )
            call_count = 0

            async def call_next() -> None:
                nonlocal call_count
                call_count += 1
                context.result = "base tool result"

            self._run_immediate(
                self._middleware(Path(temp_dir)).process(context, call_next)
            )
            self.assertEqual(call_count, 1)
            route = session.state[ROUTE_SESSION_STATE_KEY]
            self.assertEqual(route["status"], "ok")
            self.assertTrue(Path(route["map_path"]).is_file())
            self.assertIn('"status": "ok"', context.result)

    def test_commit_without_rag_is_short_circuited(self) -> None:
        with self._temporary_output() as temp_dir:
            session = SimpleNamespace(state={})
            context = SimpleNamespace(
                function=SimpleNamespace(name=COMMIT_NAVIGATION_TOOL_NAME),
                arguments={
                    "current_location": "正面玄関",
                    "destination": "初診相談室",
                },
                session=session,
                result=None,
            )
            call_count = 0

            async def call_next() -> None:
                nonlocal call_count
                call_count += 1

            self._run_immediate(
                self._middleware(Path(temp_dir)).process(context, call_next)
            )
            self.assertEqual(call_count, 0)
            self.assertIn('"status": "needs_input"', context.result)
            self.assertEqual(list(Path(temp_dir).glob("*.png")), [])


if __name__ == "__main__":
    unittest.main()
