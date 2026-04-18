"""
Agnes — AI Supply Chain Decision-Support System

A hackathon-ready RAG-augmented supply chain consolidation tool for CPG companies.

Public API
----------
from rag_engine import (
    build_index,
    hybrid_search,
    rerank,
    store_decision,
    retrieve_similar_cases,
    format_context_block,
    format_precedent_block,
    evaluate_rag_quality,
    evaluate_substitutability_rag,
)
"""

# Import from rag_engine module for convenience
from rag_engine import (
    build_index,
    hybrid_search,
    rerank,
    store_decision,
    retrieve_similar_cases,
    format_context_block,
    format_precedent_block,
    evaluate_rag_quality,
    evaluate_substitutability_rag,
    RagIndex,
)

__all__ = [
    "build_index",
    "hybrid_search",
    "rerank",
    "store_decision",
    "retrieve_similar_cases",
    "format_context_block",
    "format_precedent_block",
    "evaluate_rag_quality",
    "evaluate_substitutability_rag",
    "RagIndex",
]

__version__ = "2.0.0"
