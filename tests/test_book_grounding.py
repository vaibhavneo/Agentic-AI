"""
Tests for Phase 9's book_grounding.py. Uses a fake KnowledgeBase (no
dependency on the real ~10k-chunk corpus) so these stay fast and
deterministic, but the fake's shape exactly matches knowledge.ingest's real
KnowledgeBase.search() contract (list of {"text","source","page"} dicts).
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import book_grounding


class FakeKB:
    def __init__(self, results):
        self._results = results
        self.last_query = None
        self.last_top_k = None

    def search(self, query, top_k=6):
        self.last_query = query
        self.last_top_k = top_k
        return self._results[:top_k]


BUNDLE = {
    "divisional_charts": {
        "D1": {"ascendant": {"sign": "Cancer"}},
    },
}


class TestBuildQuery(unittest.TestCase):
    def test_includes_question_and_topics(self):
        q = book_grounding.build_query("When will I marry?", ["marriage"], None, "D1")
        self.assertIn("When will I marry?", q)
        self.assertIn("marriage", q)

    def test_includes_ascendant_and_division(self):
        q = book_grounding.build_query("career?", ["career"], BUNDLE, "D10")
        self.assertIn("Cancer ascendant", q)
        self.assertIn("D10", q)

    def test_no_division_suffix_for_d1(self):
        q = book_grounding.build_query("career?", ["career"], BUNDLE, "D1")
        self.assertNotIn(" D1", q)


class TestBuildBookContext(unittest.TestCase):
    def test_no_kb_returns_empty_context(self):
        result = book_grounding.build_book_context(None, "question", [], None, "D1")
        self.assertEqual(result["context"], "")
        self.assertEqual(result["passages"], [])

    def test_real_chunk_gets_page_cited(self):
        kb = FakeKB([{"text": "The seventh house governs marriage.", "source": "Test Book", "page": 42}])
        result = book_grounding.build_book_context(kb, "marriage", ["marriage"], None, "D1")
        self.assertEqual(len(result["passages"]), 1)
        self.assertEqual(result["passages"][0]["source"], "Test Book")
        self.assertEqual(result["passages"][0]["page"], 42)
        self.assertIn("[Test Book, page 42]", result["context"])
        self.assertIn("The seventh house governs marriage.", result["context"])

    def test_no_results_gives_empty_context_not_fabricated(self):
        kb = FakeKB([])
        result = book_grounding.build_book_context(kb, "obscure question", [], None, "D1")
        self.assertEqual(result["context"], "")
        self.assertEqual(result["passages"], [])

    def test_respects_top_k(self):
        kb = FakeKB([
            {"text": "A" * 50, "source": "Book1", "page": 1},
            {"text": "B" * 50, "source": "Book2", "page": 2},
            {"text": "C" * 50, "source": "Book3", "page": 3},
        ])
        result = book_grounding.build_book_context(kb, "q", [], None, "D1", top_k=2)
        self.assertEqual(len(result["passages"]), 2)
        self.assertEqual(kb.last_top_k, 2)

    def test_respects_max_chars_truncation(self):
        kb = FakeKB([{"text": "X" * 1000, "source": "LongBook", "page": 5}])
        result = book_grounding.build_book_context(kb, "q", [], None, "D1", max_chars=100)
        # citation header + truncated text should stay well under the original 1000 chars
        self.assertLess(len(result["context"]), 200)

    def test_citations_match_retrieved_passages_exactly(self):
        # Regression guard: context and passages must come from ONE retrieval,
        # not two separate kb.search() calls that could theoretically disagree.
        kb = FakeKB([{"text": "Some real text.", "source": "OnlyBook", "page": 7}])
        result = book_grounding.build_book_context(kb, "q", [], None, "D1")
        self.assertIn("OnlyBook", result["context"])
        self.assertEqual(result["passages"][0]["source"], "OnlyBook")


if __name__ == "__main__":
    unittest.main()
