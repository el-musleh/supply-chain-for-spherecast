"""
evaluation — RAG quality evaluation and benchmarking.

Modules:
    ragas_proper      — Full RAGAS metrics implementation
    benchmark_queries — Curated test queries with relevance judgments
"""

from .ragas_proper import RAGASEvaluator, evaluate_retrieval_quality
from .benchmark_queries import BENCHMARK_QUERIES, load_benchmark_dataset

__all__ = [
    "RAGASEvaluator",
    "evaluate_retrieval_quality",
    "BENCHMARK_QUERIES",
    "load_benchmark_dataset",
]
