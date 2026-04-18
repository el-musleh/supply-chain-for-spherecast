"""
benchmark_queries.py — Curated evaluation dataset for RAG testing.

Contains queries with expected relevant documents for measuring
retrieval quality. Used to validate RAG pipeline improvements.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class BenchmarkQuery:
    """A single benchmark query with relevance judgments."""
    query: str
    expected_sources: list[str]  # Which sources should be retrieved
    expected_keywords: list[str]  # Key concepts that should appear
    category: str  # "compliance", "substitution", "regulatory"
    difficulty: str  # "easy", "medium", "hard"
    description: Optional[str] = None


# Curated benchmark queries for Agnes RAG evaluation
BENCHMARK_QUERIES: list[BenchmarkQuery] = [
    # === COMPLIANCE QUERIES ===
    BenchmarkQuery(
        query="What are USP requirements for pharmaceutical grade vitamin D3?",
        expected_sources=["USP", "USP Vitamin D3 Monograph"],
        expected_keywords=["potency", "97-103%", "heavy metal", "assay", "cholecalciferol"],
        category="compliance",
        difficulty="easy",
        description="Direct lookup of USP monograph requirements",
    ),
    BenchmarkQuery(
        query="Does FDA 21 CFR 111 require GMP certification for dietary supplements?",
        expected_sources=["FDA", "21 CFR 111", "GMP"],
        expected_keywords=["CGMP", "current good manufacturing practice", "quality control", "testing"],
        category="compliance",
        difficulty="easy",
        description="FDA regulation on GMP requirements",
    ),
    BenchmarkQuery(
        query="What is the difference between pharmaceutical grade and food grade ingredients?",
        expected_sources=["USP", "FDA", "GMP"],
        expected_keywords=["purity", "impurities", "specifications", "testing", "standards"],
        category="compliance",
        difficulty="medium",
        description="Comparative analysis of grade standards",
    ),
    
    # === SUBSTITUTION QUERIES ===
    BenchmarkQuery(
        query="Can I substitute cholecalciferol for vitamin D3?",
        expected_sources=["USP Vitamin D3 Monograph", "DSHEA"],
        expected_keywords=["chemical identity", "cholecalciferol", "vitamin D3", "same compound"],
        category="substitution",
        difficulty="medium",
        description="Chemical identity equivalence question",
    ),
    BenchmarkQuery(
        query="What certifications are required for Halal vitamin D3?",
        expected_sources=["IFANCA", "Halal", "USP"],
        expected_keywords=["Halal certification", "pork-free", "animal-derived", "lanolin"],
        category="substitution",
        difficulty="medium",
        description="Religious certification requirements",
    ),
    BenchmarkQuery(
        query="Is USP-verified vitamin D3 equivalent to pharmaceutical grade?",
        expected_sources=["USP Verification Program", "USP Vitamin D3 Monograph"],
        expected_keywords=["USP Verified", "pharmaceutical grade", "potency", "third-party"],
        category="substitution",
        difficulty="hard",
        description="Nuanced equivalence between verification and grade",
    ),
    
    # === REGULATORY QUERIES ===
    BenchmarkQuery(
        query="What does DSHEA say about dietary supplement labeling?",
        expected_sources=["DSHEA", "FDA"],
        expected_keywords=["structure/function claims", "health claims", "disclaimer", "NDI"],
        category="regulatory",
        difficulty="medium",
        description="DSHEA labeling provisions",
    ),
    BenchmarkQuery(
        query="Are NSF/ANSI 173 certifications required for supplements?",
        expected_sources=["NSF", "NSF/ANSI 173"],
        expected_keywords=["voluntary", "certification program", "independent testing"],
        category="regulatory",
        difficulty="easy",
        description="NSF certification requirements",
    ),
    BenchmarkQuery(
        query="What are the heavy metal limits for supplements under California Prop 65?",
        expected_sources=["California Prop 65", "FDA", "USP"],
        expected_keywords=["lead", "cadmium", "arsenic", "mercury", "MADL", "NSRL"],
        category="regulatory",
        difficulty="hard",
        description="State-specific contaminant limits",
    ),
    
    # === EDGE CASES ===
    BenchmarkQuery(
        query="Can I use technical grade citric acid in dietary supplements?",
        expected_sources=["FDA", "21 CFR 111", "USP"],
        expected_keywords=["technical grade", "food grade", "pharmaceutical grade", "not acceptable"],
        category="compliance",
        difficulty="hard",
        description="Grade inappropriateness detection",
    ),
    BenchmarkQuery(
        query="What is the Kosher certification process for gelatin?",
        expected_sources=["OK Kosher", "Kosher", "USP"],
        expected_keywords=["bovine", "porcine", "supervision", "rabbinical"],
        category="substitution",
        difficulty="medium",
        description="Ingredient-specific religious certification",
    ),
    BenchmarkQuery(
        query="Does the Non-GMO Project require testing for every lot?",
        expected_sources=["Non-GMO Project"],
        expected_keywords=["verification", "ongoing compliance", "traceability", "testing"],
        category="compliance",
        difficulty="medium",
        description="Program-specific ongoing requirements",
    ),
]


def load_benchmark_dataset(
    category: Optional[str] = None,
    difficulty: Optional[str] = None,
) -> list[BenchmarkQuery]:
    """
    Load benchmark queries with optional filtering.
    
    Args:
        category: Filter by category ("compliance", "substitution", "regulatory")
        difficulty: Filter by difficulty ("easy", "medium", "hard")
        
    Returns:
        List of matching benchmark queries
    """
    queries = BENCHMARK_QUERIES
    
    if category:
        queries = [q for q in queries if q.category == category]
    
    if difficulty:
        queries = [q for q in queries if q.difficulty == difficulty]
    
    return queries


def get_statistics() -> dict:
    """Get statistics about the benchmark dataset."""
    stats = {
        "total_queries": len(BENCHMARK_QUERIES),
        "by_category": {},
        "by_difficulty": {},
    }
    
    for q in BENCHMARK_QUERIES:
        stats["by_category"][q.category] = stats["by_category"].get(q.category, 0) + 1
        stats["by_difficulty"][q.difficulty] = stats["by_difficulty"].get(q.difficulty, 0) + 1
    
    return stats


def evaluate_retrieval_against_benchmark(
    query: BenchmarkQuery,
    retrieved_docs: list[dict],
) -> dict:
    """
    Evaluate a single retrieval result against benchmark expectations.
    
    Returns precision/recall metrics against expected sources and keywords.
    """
    # Source matching
    retrieved_sources = set()
    for doc in retrieved_docs:
        source = doc.get('source', doc.get('title', ''))
        retrieved_sources.add(source)
    
    expected_sources = set(query.expected_sources)
    
    # Check for partial matches (e.g., "USP" matches "USP Vitamin D3 Monograph")
    source_hits = 0
    for expected in expected_sources:
        for retrieved in retrieved_sources:
            if expected.lower() in retrieved.lower() or retrieved.lower() in expected.lower():
                source_hits += 1
                break
    
    source_precision = source_hits / len(retrieved_docs) if retrieved_docs else 0
    source_recall = source_hits / len(expected_sources) if expected_sources else 1
    
    # Keyword matching
    all_content = " ".join([
        doc.get('content', doc.get('text', '')) + " " + doc.get('title', '')
        for doc in retrieved_docs
    ]).lower()
    
    keyword_hits = sum(1 for kw in query.expected_keywords if kw.lower() in all_content)
    keyword_coverage = keyword_hits / len(query.expected_keywords) if query.expected_keywords else 1
    
    return {
        "query": query.query,
        "category": query.category,
        "difficulty": query.difficulty,
        "source_precision": round(source_precision, 3),
        "source_recall": round(source_recall, 3),
        "source_f1": round(2 * source_precision * source_recall / (source_precision + source_recall) 
                          if (source_precision + source_recall) > 0 else 0, 3),
        "keyword_coverage": round(keyword_coverage, 3),
        "docs_retrieved": len(retrieved_docs),
        "expected_sources": list(expected_sources),
        "retrieved_sources": list(retrieved_sources),
    }


if __name__ == "__main__":
    print("Agnes Benchmark Queries")
    print("=" * 60)
    
    stats = get_statistics()
    print(f"\nTotal queries: {stats['total_queries']}")
    
    print("\nBy category:")
    for cat, count in stats["by_category"].items():
        print(f"  {cat}: {count}")
    
    print("\nBy difficulty:")
    for diff, count in stats["by_difficulty"].items():
        print(f"  {diff}: {count}")
    
    print("\nSample queries:")
    for q in BENCHMARK_QUERIES[:3]:
        print(f"\n  [{q.difficulty}] {q.category}: {q.query}")
        print(f"    Expected: {', '.join(q.expected_sources)}")
