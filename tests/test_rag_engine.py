"""
test_rag_engine.py — Tests for RAG retrieval components.

Tests cover:
    - Index building
    - Hybrid search
    - Reranking
    - Context formatting
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Conditional imports
try:
    from rag_engine import build_index, hybrid_search, rerank, format_context_block
    HAS_RAG = True
except ImportError:
    HAS_RAG = False
    pytest.skip("rag_engine not available", allow_module_level=True)


@pytest.fixture
def mock_kb_data():
    """Create minimal mock knowledge base data."""
    return [
        {
            "id": "doc1",
            "source": "USP",
            "title": "Vitamin D3 Monograph",
            "content": "USP Vitamin D3 (cholecalciferol) requires 97-103% potency assay. Heavy metals must be below 10ppm.",
            "type": "monograph",
        },
        {
            "id": "doc2", 
            "source": "FDA",
            "title": "21 CFR 111 - GMP Requirements",
            "content": "Dietary supplement manufacturers must follow current Good Manufacturing Practices (CGMP).",
            "type": "regulation",
        },
        {
            "id": "doc3",
            "source": "NSF",
            "title": "NSF/ANSI 173",
            "content": "Independent testing and certification program for dietary supplements.",
            "type": "standard",
        },
    ]


@pytest.fixture
def temp_kb_file(mock_kb_data):
    """Create temporary KB file."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(mock_kb_data, f)
        f.flush()
        yield f.name
        Path(f.name).unlink()


class TestIndexBuilding:
    """Test index construction."""
    
    def test_build_index_loads_docs(self, temp_kb_file):
        """Should load documents from KB file."""
        idx = build_index(temp_kb_file)
        assert len(idx.docs) == 3
    
    def test_build_index_creates_faiss(self, temp_kb_file):
        """Should create FAISS index."""
        idx = build_index(temp_kb_file)
        assert idx.faiss_index is not None
    
    def test_build_index_creates_bm25(self, temp_kb_file):
        """Should create BM25 index."""
        idx = build_index(temp_kb_file)
        assert idx.bm25 is not None


class TestHybridSearch:
    """Test hybrid retrieval."""
    
    def test_search_returns_results(self, temp_kb_file):
        """Should return documents matching query."""
        idx = build_index(temp_kb_file)
        results = hybrid_search(idx, "vitamin D3 potency requirements", top_k=2)
        
        assert len(results) > 0
        assert len(results) <= 2
    
    def test_search_returns_scores(self, temp_kb_file):
        """Results should have scores."""
        idx = build_index(temp_kb_file)
        results = hybrid_search(idx, "GMP manufacturing", top_k=2)
        
        for r in results:
            assert "score" in r or "rag_score" in r
    
    def test_search_empty_query(self, temp_kb_file):
        """Should handle empty query gracefully."""
        idx = build_index(temp_kb_file)
        results = hybrid_search(idx, "", top_k=2)
        
        # Should return some results (possibly random) or empty
        assert isinstance(results, list)


class TestReranking:
    """Test cross-encoder reranking."""
    
    def test_rerank_filters_top_n(self, temp_kb_file):
        """Should filter to top_n results."""
        idx = build_index(temp_kb_file)
        initial = hybrid_search(idx, "vitamin D3", top_k=5)
        
        if len(initial) >= 2:
            reranked = rerank("vitamin D3", initial, top_n=2)
            assert len(reranked) <= 2
    
    def test_rerank_preserves_structure(self, temp_kb_file):
        """Should preserve document structure."""
        idx = build_index(temp_kb_file)
        initial = hybrid_search(idx, "supplement testing", top_k=3)
        
        if initial:
            reranked = rerank("supplement testing", initial, top_n=2)
            for doc in reranked:
                assert "id" in doc
                assert "title" in doc or "content" in doc


class TestContextFormatting:
    """Test context block formatting."""
    
    def test_format_context_includes_sources(self, temp_kb_file):
        """Should include source citations."""
        idx = build_index(temp_kb_file)
        docs = hybrid_search(idx, "vitamin D3", top_k=2)
        
        if docs:
            context = format_context_block(docs)
            assert "REGULATORY CONTEXT" in context
            # Should have source brackets
            assert "[" in context and "]" in context


class TestEdgeCases:
    """Edge case handling."""
    
    def test_missing_kb_file(self):
        """Should handle missing KB file gracefully."""
        with pytest.raises((FileNotFoundError, OSError)):
            build_index("/nonexistent/path/kb.json")
    
    def test_invalid_json(self):
        """Should handle invalid JSON gracefully."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("not valid json")
            f.flush()
            
            with pytest.raises(json.JSONDecodeError):
                build_index(f.name)
            
            Path(f.name).unlink()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
