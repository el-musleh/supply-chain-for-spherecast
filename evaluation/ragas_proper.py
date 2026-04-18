"""
ragas_proper.py — Full RAGAS (Retrieval-Augmented Generation Assessment) metrics.

RAGAS is a framework for evaluating RAG pipelines without human-annotated references.
This implementation provides four key metrics:

    1. Faithfulness      — Factual consistency between answer and context
    2. Answer Relevance  — How well the answer addresses the question
    3. Context Precision — Precision of retrieved context (relevant chunks / total)
    4. Context Recall    — Coverage of question aspects in retrieved context

Implementation uses:
    - Cross-encoders for semantic similarity (faithfulness)
    - LLM-as-judge for relevance scoring
    - Heuristics for quick evaluation

References:
    - Original paper: https://arxiv.org/abs/2309.15217
    - Framework: https://docs.ragas.io/
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional

import numpy as np

try:
    from sentence_transformers import CrossEncoder
    HAS_CROSS_ENCODER = True
except ImportError:
    HAS_CROSS_ENCODER = False

try:
    import google.genai as genai
    from google.genai import types
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False


@dataclass
class RAGASScores:
    """Container for RAGAS evaluation scores."""
    faithfulness: float  # 0.0 - 1.0
    answer_relevance: float
    context_precision: float
    context_recall: float
    overall: float  # Mean of above
    
    # Metadata
    method: str = "ragas_proper"
    llm_judge_used: bool = False
    
    def to_dict(self) -> dict:
        return {
            "faithfulness": round(self.faithfulness, 3),
            "answer_relevance": round(self.answer_relevance, 3),
            "context_precision": round(self.context_precision, 3),
            "context_recall": round(self.context_recall, 3),
            "overall": round(self.overall, 3),
            "method": self.method,
            "llm_judge_used": self.llm_judge_used,
        }


class RAGASEvaluator:
    """
    Production-grade RAGAS evaluator with multiple backends.
    
    Supports:
        - Cross-encoder for faithfulness (NLI-style)
        - LLM-as-judge for answer relevance
        - Heuristic fallbacks when models unavailable
    """
    
    def __init__(
        self,
        gemini_client: Optional[genai.Client] = None,
        use_llm_judge: bool = True,
        faithfulness_model: str = "cross-encoder/nli-deberta-v3-base",
        verbose: bool = False,
    ):
        self.client = gemini_client
        self.use_llm_judge = use_llm_judge and HAS_GENAI and gemini_client is not None
        self.verbose = verbose
        
        # Load faithfulness model (NLI for entailment)
        self._faithfulness_model = None
        if HAS_CROSS_ENCODER:
            try:
                self._faithfulness_model = CrossEncoder(faithfulness_model)
                if verbose:
                    print(f"✓ Loaded faithfulness model: {faithfulness_model}")
            except Exception as e:
                if verbose:
                    print(f"⚠ Could not load faithfulness model: {e}")
    
    def evaluate(
        self,
        query: str,
        retrieved_documents: list[dict],
        llm_answer: str,
        evidence_trail: Optional[list[str]] = None,
    ) -> RAGASScores:
        """
        Evaluate a RAG response with full RAGAS metrics.
        
        Args:
            query: The original user query
            retrieved_documents: List of retrieved docs with 'content' and 'title'
            llm_answer: The LLM-generated answer
            evidence_trail: Optional list of evidence items from the LLM
            
        Returns:
            RAGASScores with all four metrics
        """
        # Prepare context
        context = "\n\n".join([
            f"[{doc.get('source', 'Unknown')}] {doc.get('title', 'Untitled')}\n{doc.get('content', doc.get('text', ''))[:500]}"
            for doc in retrieved_documents
        ])
        
        # Compute metrics
        faithfulness = self._compute_faithfulness(llm_answer, context, evidence_trail)
        answer_relevance = self._compute_answer_relevance(query, llm_answer)
        context_precision = self._compute_context_precision(query, retrieved_documents)
        context_recall = self._compute_context_recall(query, retrieved_documents)
        
        overall = np.mean([faithfulness, answer_relevance, context_precision, context_recall])
        
        return RAGASScores(
            faithfulness=faithfulness,
            answer_relevance=answer_relevance,
            context_precision=context_precision,
            context_recall=context_recall,
            overall=overall,
            method="ragas_proper",
            llm_judge_used=self.use_llm_judge and answer_relevance > 0,
        )
    
    def _compute_faithfulness(
        self,
        answer: str,
        context: str,
        evidence_trail: Optional[list[str]] = None,
    ) -> float:
        """
        Measure factual consistency between answer and context.
        
        Uses:
            1. Evidence trail grounding (if provided)
            2. NLI entailment (if model available)
            3. Token overlap fallback
        """
        scores = []
        
        # 1. Evidence trail grounding
        if evidence_trail:
            grounded = 0
            for item in evidence_trail:
                # Check if evidence item has significant overlap with context
                item_tokens = set(self._tokenize(item))
                context_tokens = set(self._tokenize(context))
                
                if len(item_tokens) > 0:
                    overlap = len(item_tokens & context_tokens) / len(item_tokens)
                    if overlap > 0.3:  # 30% overlap threshold
                        grounded += 1
            
            if evidence_trail:
                scores.append(grounded / len(evidence_trail))
        
        # 2. NLI entailment (cross-encoder)
        if self._faithfulness_model and len(answer) > 20:
            try:
                # Split answer into claims
                claims = self._extract_claims(answer)
                entailments = []
                
                for claim in claims[:3]:  # Check first 3 claims
                    # Premise: context, Hypothesis: claim
                    prediction = self._faithfulness_model.predict([[context[:1000], claim]])
                    # prediction is logits: [contradiction, neutral, entailment]
                    entailment_score = prediction[2]  # Entailment logit
                    entailments.append(entailment_score)
                
                if entailments:
                    # Normalize to 0-1 range (rough approximation)
                    avg_entailment = np.mean(entailments)
                    # Convert logit to probability-like score
                    score = 1 / (1 + np.exp(-avg_entailment))  # Sigmoid
                    scores.append(score)
            except Exception as e:
                if self.verbose:
                    print(f"  NLI faithfulness failed: {e}")
        
        # 3. Token overlap fallback
        if not scores:
            answer_tokens = set(self._tokenize(answer))
            context_tokens = set(self._tokenize(context))
            
            if answer_tokens:
                overlap = len(answer_tokens & context_tokens) / len(answer_tokens)
                scores.append(overlap)
        
        return np.mean(scores) if scores else 0.5  # Default neutral
    
    def _compute_answer_relevance(self, query: str, answer: str) -> float:
        """
        Measure how well the answer addresses the query.
        
        Uses LLM-as-judge if available, otherwise semantic similarity.
        """
        if self.use_llm_judge and self.client:
            try:
                prompt = f"""Rate how well the ANSWER addresses the QUERY.

QUERY: {query}

ANSWER: {answer}

Rate 1-5 where:
1 = Completely irrelevant
2 = Partially relevant but misses main point
3 = Addresses query but incomplete
4 = Good answer with minor gaps
5 = Perfect answer

Respond with ONLY a number 1-5."""
                
                response = self.client.models.generate_content(
                    model="gemini-flash-latest",
                    contents=prompt,
                    config=types.GenerateContentConfig(temperature=0.0),
                )
                
                # Extract number
                text = response.text.strip()
                match = re.search(r'\b([1-5])\b', text)
                if match:
                    score = int(match.group(1)) / 5.0  # Normalize to 0-1
                    return score
            except Exception as e:
                if self.verbose:
                    print(f"  LLM judge failed: {e}")
        
        # Fallback: Keyword overlap heuristic
        query_keywords = set(self._extract_keywords(query))
        answer_keywords = set(self._extract_keywords(answer))
        
        if query_keywords:
            coverage = len(query_keywords & answer_keywords) / len(query_keywords)
            return coverage
        
        return 0.5
    
    def _compute_context_precision(
        self,
        query: str,
        retrieved_documents: list[dict],
    ) -> float:
        """
        Measure precision: relevant chunks / total chunks retrieved.
        
        Simple heuristic: count how many docs contain query keywords.
        """
        if not retrieved_documents:
            return 0.0
        
        query_keywords = set(self._extract_keywords(query))
        if not query_keywords:
            return 1.0  # No keywords = assume all relevant
        
        relevant = 0
        for doc in retrieved_documents:
            content = doc.get('content', doc.get('text', '')).lower()
            doc_tokens = set(self._tokenize(content))
            
            # Doc is relevant if it contains at least one query keyword
            if query_keywords & doc_tokens:
                relevant += 1
        
        return relevant / len(retrieved_documents)
    
    def _compute_context_recall(
        self,
        query: str,
        retrieved_documents: list[dict],
    ) -> float:
        """
        Measure recall: coverage of query aspects in retrieved docs.
        
        Heuristic: what fraction of query keywords appear in any document.
        """
        if not retrieved_documents:
            return 0.0
        
        query_keywords = set(self._extract_keywords(query))
        if not query_keywords:
            return 1.0
        
        # Collect all tokens from retrieved docs
        all_doc_tokens = set()
        for doc in retrieved_documents:
            content = doc.get('content', doc.get('text', ''))
            all_doc_tokens.update(self._tokenize(content))
        
        # Coverage of query keywords
        covered = len(query_keywords & all_doc_tokens)
        return covered / len(query_keywords)
    
    def _tokenize(self, text: str) -> list[str]:
        """Simple tokenization for overlap calculations."""
        # Lowercase, remove punctuation, split
        text = text.lower()
        text = re.sub(r'[^\w\s]', ' ', text)
        tokens = text.split()
        # Filter very short tokens and common stopwords
        stopwords = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
                     'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
                     'would', 'could', 'should', 'may', 'might', 'must', 'shall',
                     'can', 'need', 'dare', 'ought', 'used', 'to', 'of', 'in',
                     'for', 'on', 'with', 'at', 'by', 'from', 'as', 'into',
                     'through', 'during', 'before', 'after', 'above', 'below',
                     'between', 'under', 'and', 'but', 'or', 'yet', 'so', 'if',
                     'because', 'although', 'though', 'while', 'where', 'when',
                     'that', 'which', 'who', 'whom', 'whose', 'what', 'this',
                     'these', 'those', 'i', 'me', 'my', 'myself', 'we', 'our',
                     'you', 'your', 'he', 'him', 'his', 'she', 'her', 'it',
                     'its', 'they', 'them', 'their', 's', 're', 't'}
        return [t for t in tokens if len(t) > 2 and t not in stopwords]
    
    def _extract_keywords(self, text: str) -> list[str]:
        """Extract important keywords from text."""
        tokens = self._tokenize(text)
        # Return unique tokens, preserving order
        seen = set()
        keywords = []
        for t in tokens:
            if t not in seen:
                seen.add(t)
                keywords.append(t)
        return keywords[:20]  # Limit to top 20
    
    def _extract_claims(self, text: str) -> list[str]:
        """Extract individual claims/sentences from text."""
        # Split on sentence boundaries
        sentences = re.split(r'[.!?]+', text)
        # Filter short sentences
        claims = [s.strip() for s in sentences if len(s.strip()) > 20]
        return claims[:5]  # Limit to first 5 claims


def evaluate_retrieval_quality(
    query: str,
    retrieved_docs: list[dict],
    gemini_client: Optional[genai.Client] = None,
) -> dict:
    """
    Quick evaluation of retrieval quality without full answer generation.
    
    Returns metrics focused on retrieval performance:
        - relevance_score: Query-doc relevance (heuristic)
        - diversity_score: Variety of sources
        - coverage_score: Query aspect coverage
    """
    evaluator = RAGASEvaluator(gemini_client=gemini_client, use_llm_judge=False)
    
    precision = evaluator._compute_context_precision(query, retrieved_docs)
    recall = evaluator._compute_context_recall(query, retrieved_docs)
    
    # Diversity: count unique sources
    sources = set(d.get('source', 'Unknown') for d in retrieved_docs)
    diversity = len(sources) / len(retrieved_docs) if retrieved_docs else 0
    
    return {
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "diversity": round(diversity, 3),
        "f1": round(2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0, 3),
        "unique_sources": len(sources),
        "docs_retrieved": len(retrieved_docs),
    }


if __name__ == "__main__":
    # Simple demo
    print("RAGAS Proper — Demo Evaluation")
    print("=" * 50)
    
    evaluator = RAGASEvaluator(verbose=True)
    
    # Mock data
    query = "What are the USP requirements for vitamin D3?"
    retrieved = [
        {"source": "USP", "title": "Vitamin D3 Monograph", "content": "USP Vitamin D3 requires 97-103% potency..."},
        {"source": "FDA", "title": "21 CFR 111", "content": "Dietary supplement CGMP requirements..."},
    ]
    answer = "USP requires vitamin D3 to have 97-103% potency and meet heavy metal limits."
    evidence = ["USP requires 97-103% potency", "Heavy metal limits specified"]
    
    scores = evaluator.evaluate(query, retrieved, answer, evidence)
    
    print("\nScores:")
    for k, v in scores.to_dict().items():
        print(f"  {k}: {v}")
