from __future__ import annotations

import unittest
from pathlib import Path

from hospital_agents.errors import AmbiguousLocationError
from hospital_agents.services.routing import RouteEngine


ROOT = Path(__file__).resolve().parents[1]
GRAPH = ROOT / "data" / "facility_graph.json"


class RouteEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = RouteEngine(GRAPH)

    def test_resolves_alias_and_calculates_shortest_path(self) -> None:
        route = self.engine.calculate("正面入口", "初診相談室")
        self.assertEqual(route.current.id, "a1_entrance")
        self.assertEqual(route.destination.id, "a1_consult")
        self.assertGreater(route.distance_m, 0)
        self.assertGreaterEqual(len(route.steps), 2)
        self.assertIn("推定値", route.distance_note)

    def test_cross_floor_route_uses_fixed_transition_instruction(self) -> None:
        route = self.engine.calculate("総合受付", "小児歯科A201")
        instructions = [step.instruction for step in route.steps]
        self.assertIn("A棟エレベーターで1階・2階間を移動", instructions)
        self.assertGreater(route.distance_m, 0)

    def test_cross_building_route_uses_connector(self) -> None:
        route = self.engine.calculate("正面入口", "CT撮影室")
        self.assertTrue(
            any("A棟とB棟の1階連絡通路" in step.instruction for step in route.steps)
        )

    def test_ambiguous_alias_requires_floor(self) -> None:
        with self.assertRaises(AmbiguousLocationError):
            self.engine.resolve("エレベーター")

    def test_rag_evidence_uses_destination_labels(self) -> None:
        destination = self.engine.resolve("A棟1F初診相談室")
        self.assertTrue(
            self.engine.destination_is_present_in_rag(
                destination,
                '{"results":[{"content":"施設名: 初診相談室"}]}',
            )
        )
        self.assertFalse(
            self.engine.destination_is_present_in_rag(
                destination,
                '{"results":[{"content":"施設名: 総合受付"}]}',
            )
        )


if __name__ == "__main__":
    unittest.main()
