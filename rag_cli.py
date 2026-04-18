#!/usr/bin/env python3
"""
rag_cli.py — Command-line interface for the Agnes RAG engine.

Commands:
    python rag_cli.py stats              Show knowledge base statistics
    python rag_cli.py search "query"     Run hybrid search and show results
    python rag_cli.py test               Quick sanity check that index builds

Examples:
    python rag_cli.py search "USP pharmaceutical grade vitamin D3"
    python rag_cli.py search "Halal certification requirements"
"""

import argparse
import json
import sys
from pathlib import Path


def cmd_stats(args):
    """Show knowledge base statistics."""
    kb_path = Path(args.kb_path)
    if not kb_path.exists():
        print(f"Error: Knowledge base not found at '{kb_path}'")
        print("Run: python scrape_kb.py")
        return 1

    with open(kb_path, encoding="utf-8") as f:
        docs = json.load(f)

    print("=" * 60)
    print("  Agnes RAG — Knowledge Base Statistics")
    print("=" * 60)
    print(f"\n  Total documents: {len(docs)}")
    print(f"  KB file: {kb_path}")

    # Count by type
    from collections import Counter
    type_counts = Counter(d.get("type", "unknown") for d in docs)

    print("\n  Documents by type:")
    for doc_type, count in sorted(type_counts.items()):
        print(f"    {doc_type:30s}: {count}")

    # Count by source
    source_counts = Counter(d.get("source", "unknown") for d in docs)
    print("\n  Documents by source:")
    for source, count in sorted(source_counts.items()):
        print(f"    {source:30s}: {count}")

    # Total content size
    total_chars = sum(len(d.get("content", "")) for d in docs)
    print(f"\n  Total content: {total_chars:,} characters")
    print(f"  Average per doc: {total_chars // len(docs):,} characters")

    print("\n" + "=" * 60)
    print("  Run 'python rag_cli.py test' to verify index builds")
    print("=" * 60)
    return 0


def cmd_search(args):
    """Run hybrid search and display results."""
    from rag_engine import build_index, hybrid_search, rerank

    kb_path = Path(args.kb_path)
    if not kb_path.exists():
        print(f"Error: Knowledge base not found at '{kb_path}'")
        print("Run: python scrape_kb.py")
        return 1

    print("=" * 60)
    print("  Agnes RAG — Hybrid Search")
    print("=" * 60)
    print(f"\n  Query: {args.query}")
    print(f"  Top-k: {args.top_k}")
    print(f"  Re-rank top-n: {args.top_n}")

    print("\n  Building index...")
    rag_idx = build_index(str(kb_path))

    print(f"\n  Running hybrid search (alpha=0.65)...")
    raw_docs = hybrid_search(rag_idx, args.query, top_k=args.top_k)

    print(f"  Re-ranking with cross-encoder...")
    results = rerank(args.query, raw_docs, top_n=args.top_n)

    print("\n" + "=" * 60)
    print("  Results (ranked by relevance)")
    print("=" * 60)

    for i, doc in enumerate(results, 1):
        score = doc.get("rerank_score", doc.get("rag_score", 0))
        print(f"\n[{i}] {doc['title'][:65]}")
        print(f"    Source: {doc['source']}")
        print(f"    Type: {doc['type']}")
        print(f"    Score: {score:.4f}")
        # Show first 200 chars of content
        content_preview = doc.get("content", "")[:200].replace("\n", " ")
        print(f"    Preview: {content_preview}...")

    print("\n" + "=" * 60)
    return 0


def cmd_test(args):
    """Quick sanity check that index builds and searches work."""
    from rag_engine import build_index, hybrid_search

    kb_path = Path(args.kb_path)
    if not kb_path.exists():
        print(f"Error: Knowledge base not found at '{kb_path}'")
        print("Run: python scrape_kb.py")
        return 1

    print("=" * 60)
    print("  Agnes RAG — Sanity Check")
    print("=" * 60)

    print("\n[1] Building index...")
    try:
        rag_idx = build_index(str(kb_path))
        print(f"    ✓ Index built: {len(rag_idx.docs)} documents")
    except Exception as e:
        print(f"    ✗ Failed: {e}")
        return 1

    print("\n[2] Testing vector search...")
    try:
        results = hybrid_search(rag_idx, "USP pharmaceutical grade", top_k=3)
        print(f"    ✓ Search returned {len(results)} results")
        if results:
            print(f"    ✓ Top result: {results[0]['title'][:50]}")
    except Exception as e:
        print(f"    ✗ Failed: {e}")
        return 1

    print("\n[3] Testing BM25 keyword search...")
    try:
        results = hybrid_search(rag_idx, "Halal certification", top_k=3)
        print(f"    ✓ Search returned {len(results)} results")
        if results:
            print(f"    ✓ Top result: {results[0]['title'][:50]}")
    except Exception as e:
        print(f"    ✗ Failed: {e}")
        return 1

    print("\n" + "=" * 60)
    print("  ✓ All checks passed — RAG engine is working")
    print("=" * 60)
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Agnes RAG — Command-line interface",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s stats
  %(prog)s search "USP pharmaceutical grade vitamin D3"
  %(prog)s search "Halal certification requirements" --top-k 10
  %(prog)s test
""",
    )
    parser.add_argument(
        "--kb-path",
        default="KB/regulatory_docs.json",
        help="Path to knowledge base JSON (default: KB/regulatory_docs.json)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # stats command
    stats_parser = subparsers.add_parser("stats", help="Show knowledge base statistics")
    stats_parser.set_defaults(func=cmd_stats)

    # search command
    search_parser = subparsers.add_parser("search", help="Run hybrid search")
    search_parser.add_argument("query", help="Search query string")
    search_parser.add_argument("--top-k", type=int, default=5, help="Number of candidates (default: 5)")
    search_parser.add_argument("--top-n", type=int, default=3, help="Number after re-ranking (default: 3)")
    search_parser.set_defaults(func=cmd_search)

    # test command
    test_parser = subparsers.add_parser("test", help="Run sanity check")
    test_parser.set_defaults(func=cmd_test)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
