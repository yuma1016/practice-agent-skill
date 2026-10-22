from __future__ import annotations

import json
import unittest
from pathlib import Path

from hospital_agents.services.rag import LlamaIndexSearchService


ROOT = Path(__file__).resolve().parents[1]


class DemoSearchTests(unittest.TestCase):
    def test_demo_script_implements_search_contract(self) -> None:
        service = LlamaIndexSearchService(ROOT / "scripts" / "demo_search.py")
        result = json.loads(service.search("初診相談室へ行きたい", top_k=3))
        self.assertTrue(result["results"])
        self.assertIn("初診相談室", result["results"][0]["content"])


if __name__ == "__main__":
    unittest.main()
