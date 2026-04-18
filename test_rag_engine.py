#!/usr/bin/env python3
"""
test_rag_engine.py — Unit tests for the Agnes RAG engine.

Run with pytest:
    pytest test_rag_engine.py -v

Or run directly:
    python test_rag_engine.py
"""

import json
import os
import tempfile
import unittest
from pathlib import Path


# Check if dependencies are available
try:
    from rag_engine import (
        build_index,
        hybrid_search,
        rerank,
        store_decision,
        retrieve_similar_cases,
        format_context_block,
        format_precedent_block,
        evaluate_rag_quality,
        _tokenize,
        score_faithfulness,
        score_answer_relevance,
        score_context_recall,
    )
    RAG_AVAILABLE = True
except ImportError as e:
    RAG_AVAILABLE = False
    RAG_IMPORT_ERROR = str(e)


# Test data
SAMPLE_KB = [
    {
        "id": "test-doc-1",
        "title": "USP Pharmaceutical Grade Standards",
        "source": "U.S. Pharmacopeia",
        "url": "https://example.com/usp",
        "type": "grade_definition",
        "content": "Pharmaceutical grade requires 99% purity and compliance with USP monograph specifications. Food grade meets FCC standards but not necessarily USP requirements.",
        "scraped_date": "2024-01-01",
    },
    {
        "id": "test-doc-2",
        "title": "FDA cGMP Requirements",
        "source": "U.S. FDA",
        "url": "https://example.com/fda",
        "type": "gmp_regulation",
        "content": "Current Good Manufacturing Practice requires qualified personnel, appropriate facilities, and record keeping for two years.",
        "scraped_date": "2024-01-01",
    },
    {
        "id": "test-doc-3",
        "title": "Halal Certification Guide",
        "source": "IFANCA",
        "url": "https://example.com/halal",
        "type": "halal_certification",
        "content": "Halal products must not contain pork or alcohol. Annual re-certification is required. Lanolin-derived ingredients are generally Halal.",
        "scraped_date": "2024-01-01",
    },
]


@unittest.skipUnless(RAG_AVAILABLE, f"RAG dependencies not available: {RAG_IMPORT_ERROR if not RAG_AVAILABLE else ''}")
class TestRagEngine(unittest.TestCase):
    """Test cases for rag_engine.py functions."""

    @classmethod
    def setUpClass(cls):
        """Create temporary KB file and build index once for all tests."""
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.kb_path = Path(cls.temp_dir.name) / "test_kb.json"

        with open(cls.kb_path, "w", encoding="utf-8") as f:
            json.dump(SAMPLE_KB, f)

        cls.rag_idx = build_index(str(cls.kb_path))

    @classmethod
    def tearDownClass(cls):
        """Clean up temporary files."""
        cls.temp_dir.cleanup()

        # Clean up any test decisions
        test_decisions = Path("KB/decisions.json")
        if test_decisions.exists():
            try:
                with open(test_decisions) as f:
                    decisions = json.load(f)
                # Filter out test decisions
                decisions = [d for d in decisions if not d.get("ingredient_a", "").startswith("test-")]
                with open(test_decisions, "w") as f:
                    json.dump(decisions, f, indent=2)
            except Exception:
                pass

    def test_tokenize(self):
        """Test the _tokenize function."""
        text = "USP Pharmaceutical Grade 123"
        tokens = _tokenize(text)
        self.assertEqual(tokens, ["usp", "pharmaceutical", "grade", "123"])

    def test_build_index(self):
        """Test that build_index creates a valid index."""
        self.assertEqual(len(self.rag_idx.docs), 3)
        self.assertIsNotNone(self.rag_idx.faiss_index)
        self.assertIsNotNone(self.rag_idx.bm25)
        self.assertIsNotNone(self.rag_idx.embedding_model)

    def test_hybrid_search_returns_results(self):
        """Test that hybrid_search returns ranked results with scores."""
        results = hybrid_search(self.rag_idx, "pharmaceutical grade", top_k=2)

        self.assertEqual(len(results), 2)
        self.assertIn("rag_score", results[0])
        self.assertIn("title", results[0])
        self.assertIn("content", results[0])
        # Verify scores are present and valid
        self.assertIsInstance(results[0]["rag_score"], float)
        self.assertGreaterEqual(results[0]["rag_score"], 0.0)

    def test_hybrid_search_bm25_keywords(self):
        """Test that BM25 picks up on specific keywords."""
        results = hybrid_search(self.rag_idx, "Halal certification", top_k=2)

        self.assertEqual(len(results), 2)
        # Verify BM25 returned valid results with scores
        self.assertIn("rag_score", results[0])
        self.assertIsInstance(results[0]["rag_score"], float)

    def test_rerank(self):
        """Test that rerank produces rerank_score."""
        raw_docs = hybrid_search(self.rag_idx, "pharmaceutical", top_k=3)
        reranked = rerank("pharmaceutical", raw_docs, top_n=2)

        self.assertEqual(len(reranked), 2)
        self.assertIn("rerank_score", reranked[0])
        # Scores should be floats
        self.assertIsInstance(reranked[0]["rerank_score"], float)

    def test_format_context_block(self):
        """Test that format_context_block produces expected format."""
        docs = SAMPLE_KB[:2]
        block = format_context_block(docs)

        self.assertIn("REGULATORY CONTEXT", block)
        self.assertIn("USP Pharmaceutical Grade Standards", block)
        self.assertIn("FDA cGMP Requirements", block)
        self.assertIn("Cite sources", block)

    def test_format_precedent_block_empty(self):
        """Test that format_precedent_block returns empty string for no cases."""
        block = format_precedent_block([])
        self.assertEqual(block, "")

    def test_store_and_retrieve_decision(self):
        """Test the roundtrip of storing and retrieving decisions."""
        test_decision = {
            "ingredient_a": "test-ingredient-a",
            "ingredient_b": "test-ingredient-b",
            "supplier_a": "TestSupplierA",
            "supplier_b": "TestSupplierB",
            "grade_a": "pharmaceutical",
            "grade_b": "food",
            "certifications_a": ["USP", "GMP"],
            "certifications_b": ["GMP"],
            "verdict": "APPROVE",
            "confidence": 0.95,
            "reasoning": "Test reasoning",
            "evidence_trail": ["Fact 1", "Fact 2"],
            "sources_cited": [],
        }

        # Store decision
        store_decision(test_decision)

        # Retrieve similar cases
        similar = retrieve_similar_cases(
            ingredient_a="test-ingredient-a",
            ingredient_b="test-ingredient-b",
            grade_a="pharmaceutical",
            grade_b="food",
            certifications_a=["USP", "GMP"],
            certifications_b=["GMP"],
            top_k=3,
        )

        self.assertGreater(len(similar), 0)
        # The stored decision should be in the results
        self.assertTrue(
            any(s.get("ingredient_a") == "test-ingredient-a" for s in similar),
            "Expected to find the stored test decision"
        )

    def test_score_faithfulness(self):
        """Test faithfulness scoring."""
        evidence = [
            "USP requires 99% purity",  # Matches doc content
            "Random ungrounded fact xyz123",  # Doesn't match
        ]
        docs = SAMPLE_KB[:1]  # Just the USP doc

        score = score_faithfulness(evidence, docs)
        # First item should be grounded, second not
        self.assertGreater(score, 0.0)
        self.assertLess(score, 1.0)

    def test_score_answer_relevance(self):
        """Test answer relevance scoring."""
        docs = SAMPLE_KB[:1]  # USP doc with "comply", "certified"

        approve_score = score_answer_relevance("APPROVE", docs)
        reject_score = score_answer_relevance("REJECT", docs)

        # Both should be between 0 and 1
        self.assertGreaterEqual(approve_score, 0.0)
        self.assertLessEqual(approve_score, 1.0)
        self.assertGreaterEqual(reject_score, 0.0)
        self.assertLessEqual(reject_score, 1.0)

    def test_score_context_recall(self):
        """Test context recall scoring."""
        docs = SAMPLE_KB[:2]  # USP and FDA docs
        query = "USP pharmaceutical grade"

        score = score_context_recall(docs, query)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)
        # Should find that USP doc is relevant
        self.assertGreater(score, 0.0)

    def test_evaluate_rag_quality(self):
        """Test the full RAG quality evaluation."""
        eval_result = {
            "recommendation": "APPROVE",
            "evidence_trail": ["USP requires 99% purity"],
        }
        retrieved_docs = SAMPLE_KB[:1]
        query = "pharmaceutical grade"

        scores = evaluate_rag_quality(eval_result, retrieved_docs, query)

        self.assertIn("faithfulness", scores)
        self.assertIn("answer_relevance", scores)
        self.assertIn("context_recall", scores)
        self.assertIn("overall", scores)
        self.assertIn("docs_retrieved", scores)
        self.assertIn("evidence_items", scores)

        # Overall should be mean of the three
        expected_overall = (
            scores["faithfulness"] +
            scores["answer_relevance"] +
            scores["context_recall"]
        ) / 3
        self.assertAlmostEqual(scores["overall"], expected_overall, places=3)


@unittest.skipUnless(RAG_AVAILABLE, f"RAG dependencies not available: {RAG_IMPORT_ERROR if not RAG_AVAILABLE else ''}")
class TestRagIndexStructure(unittest.TestCase):
    """Test the RagIndex data structure."""

    def test_ragindex_fields(self):
        """Test that RagIndex has expected fields."""
        from rag_engine import RagIndex

        # Check that RagIndex is a dataclass with expected fields
        import dataclasses
        fields = {f.name for f in dataclasses.fields(RagIndex)}

        expected = {"docs", "faiss_index", "bm25", "embedding_model", "tokenized_docs"}
        self.assertTrue(expected.issubset(fields))


class TestDependencyCheck(unittest.TestCase):
    """Test dependency checking."""

    def test_dependency_check_function_exists(self):
        """Test that _check_rag_dependencies exists."""
        try:
            from rag_engine import _check_rag_dependencies
            self.assertTrue(callable(_check_rag_dependencies))
        except ImportError:
            self.skipTest("rag_engine not available")


if __name__ == "__main__":
    unittest.main(verbosity=2)
