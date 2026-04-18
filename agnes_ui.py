"""
agnes_ui.py — Agnes Interactive Multimodal Compliance Evaluator

Gradio web app that accepts interleaved text, image, audio, video, PDF,
and pasted URLs, evaluates supplier substitutability via the Agnes RAG
pipeline, and asks for user confirmation before persisting any decision.

Run:
    python agnes_ui.py

Inputs (6 types):
    text          — free-form notes + optional URLs (auto-detected)
    image         — CoA certificate image (PNG/JPG)
    audio         — spoken quality notes (MP3/WAV)
    video         — facility or product demo video
    PDF           — full Certificate of Analysis document
    URL (in text) — supplier page, PDF link, or image link; smart-routed

Confirmation flow:
    Apply       -> store_decision() -> KB/decisions.json
    Alternative -> re-evaluate at temperature=0.4 (up to 3 alternatives)
    Reject All  -> stores REJECT verdict
"""

from __future__ import annotations

import io
import json
import mimetypes
import os
import re
import sqlite3
import tempfile
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import gradio as gr
import google.genai as genai
from google.genai import types

from rag_engine import (
    build_index,
    hybrid_search,
    rerank,
    format_context_block,
    format_precedent_block,
    retrieve_similar_cases,
    store_decision,
)

from logging_config import (
    get_logger,
    create_session_logger,
    get_session_logger,
    close_session_logger,
    log_operation,
)

# Initialize loggers
logger = get_logger("ui")
session_logger = create_session_logger()

# ─────────────────────────────────────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────────────────────────────────────

load_dotenv()
_API_KEY = os.getenv("GEMINI_API_KEY", "")
client = genai.Client(api_key=_API_KEY)

print("Loading RAG index …")
try:
    rag_index = build_index("KB/regulatory_docs.json")
    print(f"  RAG index ready — {len(rag_index.docs)} documents")
except Exception as _e:
    rag_index = None
    print(f"  RAG index unavailable ({_e}) — evaluation will proceed without context")

_MODEL = "gemini-flash-latest"
_MAX_INLINE_BYTES = 15 * 1024 * 1024   # 15 MB inline limit (safe margin)
_URL_PATTERN = re.compile(r"https?://[^\s]+")

AGNES_SYSTEM_PROMPT = """\
You are Agnes, an AI supply chain reasoning agent for the CPG (Consumer Packaged Goods) industry.
Your role is to evaluate whether two raw-material ingredient variants are functionally substitutable
for sourcing consolidation purposes.

You reason carefully from:
1. Chemical and functional identity of the ingredients
2. Regulatory grade requirements (pharmaceutical vs. food vs. technical)
3. Certifications required by the end products (USP, NSF, GMP, Halal, Kosher, Non-GMO, Organic)
4. Lead time feasibility
5. Known industry standards (USP monographs, FDA 21 CFR, EU regulations)

CRITICAL RULES:
- A substitution is only valid if the replacement MEETS OR EXCEEDS the quality and compliance level.
- Downgrading from pharmaceutical grade to food grade is NEVER acceptable without explicit evidence.
- A missing certification on the replacement supplier is a compliance gap that must be flagged.
- You must produce an evidence trail: a list of specific, discrete facts supporting your conclusion.
- You must never hallucinate certifications or regulatory status.
- Confidence: 0.9+ = high certainty; 0.7-0.9 = reasonable inference; <0.7 = escalate to human.

OUTPUT FORMAT: Respond with valid JSON only matching this exact schema:
{
  "substitutable": <bool>,
  "confidence": <float 0.0-1.0>,
  "evidence_trail": ["<fact 1>", "<fact 2>", ...],
  "compliance_met": <bool>,
  "compliance_gaps": ["<gap description if any>"],
  "reasoning": "<2-4 sentence narrative>",
  "recommendation": "<APPROVE | APPROVE_WITH_CONDITIONS | REJECT | HUMAN_REVIEW_REQUIRED>"
}\
"""

_EXTRACTION_PROMPT = """\
You are a supply chain compliance extraction agent. Analyse ALL provided inputs
(images, audio transcripts, video content, PDF pages, scraped web text) and extract
the following compliance fields into valid JSON — no extra keys:

{
  "organic_certified" : <bool>,
  "fda_registered"    : <bool>,
  "non_gmo"           : <bool>,
  "grade"             : "<pharmaceutical | food | technical>",
  "lead_time_days"    : <int>,
  "certifications"    : ["<cert_name>", ...],
  "notes"             : "<one sentence summary of key compliance points>"
}

Rules:
- grade: use "pharmaceutical" if document states pharmaceutical grade
- certifications: list ONLY third-party certs with explicit evidence (GMP, USP, NSF, Halal, Kosher, ISO …)
- fda_registered: true if an FDA facility registration number is visible
- non_gmo: true if Non-GMO statement or certification is present
- lead_time_days: integer; default 14 if not found
- notes: concise summary of compliance highlights

Respond with valid JSON only — no markdown fences.\
"""


# ─────────────────────────────────────────────────────────────────────────────
# URL Smart Router
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_url(url: str) -> tuple[types.Part | None, str]:
    """
    Smart-route a URL to the appropriate Gemini Part type.
    Returns (Part | None, source_label).
    """
    try:
        head = requests.head(url, timeout=8, allow_redirects=True, headers={"User-Agent": "Agnes/2.0"})
        ct = head.headers.get("Content-Type", "")
    except Exception:
        ct = ""

    url_lower = url.lower().split("?")[0]
    is_pdf   = "application/pdf" in ct or url_lower.endswith(".pdf")
    is_image = ct.startswith("image/") or any(
        url_lower.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif")
    )

    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "Agnes/2.0"})
        resp.raise_for_status()

        if is_pdf:
            part = types.Part.from_bytes(data=resp.content, mime_type="application/pdf")
            return part, f"[pdf-url] {url[:70]}"

        if is_image:
            mime = ct.split(";")[0].strip() or "image/jpeg"
            part = types.Part.from_bytes(data=resp.content, mime_type=mime)
            return part, f"[img-url] {url[:70]}"

        # HTML page — strip to readable text
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)[:6000]
        part = types.Part.from_text(f"[Scraped from {url}]\n\n{text}")
        return part, f"[web] {url[:70]}"

    except Exception as exc:
        return None, f"[failed] {url[:50]} ({exc})"


# ─────────────────────────────────────────────────────────────────────────────
# Input Assembler
# ─────────────────────────────────────────────────────────────────────────────

def _build_parts(
    notes: str | None,
    coa_image: str | None,
    audio_file: str | None,
    video_file: str | None,
    pdf_file: str | None,
) -> tuple[list, list]:
    """
    Assemble all user inputs into an interleaved list of Gemini Parts.
    Returns (parts, source_labels).
    """
    parts: list = []
    labels: list[str] = []

    # 1. Text notes — detect and route URLs separately
    if notes and notes.strip():
        urls = _URL_PATTERN.findall(notes)
        clean_text = _URL_PATTERN.sub("", notes).strip()
        if clean_text:
            parts.append(types.Part.from_text(clean_text))
            labels.append("[text] user notes")
        for url in urls:
            part, label = _resolve_url(url)
            if part is not None:
                parts.append(part)
                labels.append(label)
            else:
                labels.append(label)  # keep failure label for display

    # 2. CoA image — inline bytes
    if coa_image:
        try:
            img_bytes = Path(coa_image).read_bytes()
            mime = mimetypes.guess_type(coa_image)[0] or "image/png"
            parts.append(types.Part.from_bytes(data=img_bytes, mime_type=mime))
            labels.append(f"[image] {Path(coa_image).name}")
        except Exception as exc:
            labels.append(f"[image-fail] {exc}")

    # Helper: read file as bytes and create Part
    def _file_part(path: str, default_mime: str, label_prefix: str):
        try:
            data = Path(path).read_bytes()
            if len(data) > _MAX_INLINE_BYTES:
                labels.append(f"[{label_prefix}-skip] file too large (>{_MAX_INLINE_BYTES//1024//1024}MB)")
                return
            mime = mimetypes.guess_type(path)[0] or default_mime
            parts.append(types.Part.from_bytes(data=data, mime_type=mime))
            labels.append(f"[{label_prefix}] {Path(path).name}")
        except Exception as exc:
            labels.append(f"[{label_prefix}-fail] {exc}")

    # 3. Audio
    if audio_file:
        _file_part(audio_file, "audio/mpeg", "audio")

    # 4. Video (Gradio 6 may return dict with 'video' key or a filepath string)
    if video_file:
        vpath = video_file.get("video", {}).get("path") if isinstance(video_file, dict) else video_file
        if vpath:
            _file_part(vpath, "video/mp4", "video")

    # 5. PDF
    if pdf_file:
        _file_part(pdf_file, "application/pdf", "pdf")

    return parts, labels


# ─────────────────────────────────────────────────────────────────────────────
# Multimodal Compliance Extraction
# ─────────────────────────────────────────────────────────────────────────────

def _extract_compliance(parts: list, supplier: str, ingredient: str) -> dict:
    """
    Ask Gemini to extract structured compliance data from all provided Parts.
    Falls back to a minimal default if no parts or extraction fails.
    """
    if not parts:
        return {
            "organic_certified": False, "fda_registered": True,
            "non_gmo": False, "grade": "food", "lead_time_days": 14,
            "certifications": [], "notes": "No documents provided — using defaults.",
        }
    try:
        response = client.models.generate_content(
            model=_MODEL,
            contents=parts + [types.Part.from_text(_EXTRACTION_PROMPT)],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,
            ),
        )
        extracted = json.loads(response.text.strip())
        extracted.setdefault("notes", f"Extracted from {len(parts)} input(s).")
        return extracted
    except Exception as exc:
        return {
            "organic_certified": False, "fda_registered": True,
            "non_gmo": False, "grade": "food", "lead_time_days": 14,
            "certifications": [], "notes": f"Extraction error: {exc}",
        }


# ─────────────────────────────────────────────────────────────────────────────
# RAG Evaluation (does NOT auto-store — confirmation required)
# ─────────────────────────────────────────────────────────────────────────────

def _evaluate(
    ing_a: str, sup_a: str, comp_a: dict,
    ing_b: str, sup_b: str, comp_b: dict,
    temperature: float = 0.2,
    exclude_verdict: str | None = None,
) -> tuple[dict, list]:
    """
    RAG-augmented evaluation without persisting. Returns (result_dict, retrieved_docs).
    exclude_verdict is used when requesting alternatives to avoid the same answer.
    """
    certs_a = ", ".join(comp_a.get("certifications", []))
    certs_b = ", ".join(comp_b.get("certifications", []))
    query = (
        f"{ing_a} {ing_b} {comp_a.get('grade','')} {comp_b.get('grade','')} "
        f"compliance certification {certs_a} {certs_b} substitution dietary supplement"
    )

    retrieved_docs: list = []
    context_block = ""
    precedent_block = ""

    if rag_index is not None:
        raw_docs = hybrid_search(rag_index, query, top_k=5)
        retrieved_docs = rerank(query, raw_docs, top_n=3)
        context_block = format_context_block(retrieved_docs)
        similar = retrieve_similar_cases(
            ingredient_a=ing_a, ingredient_b=ing_b,
            grade_a=comp_a.get("grade", ""),
            grade_b=comp_b.get("grade", ""),
            certifications_a=comp_a.get("certifications", []),
            certifications_b=comp_b.get("certifications", []),
            top_k=2,
        )
        precedent_block = format_precedent_block(similar)

    sys_prompt = AGNES_SYSTEM_PROMPT
    if context_block:
        sys_prompt = context_block + "\n\n" + sys_prompt
    if precedent_block:
        sys_prompt += "\n\n" + precedent_block
    if exclude_verdict:
        sys_prompt += f"\n\nIMPORTANT: Do NOT return '{exclude_verdict}' as the recommendation — provide the next-best alternative assessment."

    cert_a = ", ".join(comp_a.get("certifications", [])) or "None"
    cert_b = ", ".join(comp_b.get("certifications", [])) or "None"

    user_msg = f"""## Substitutability Evaluation Request

### Ingredient A — Current (consolidate FROM)
- Ingredient  : {ing_a}
- Supplier    : {sup_a}
- Grade       : {comp_a.get('grade')}
- FDA reg     : {comp_a.get('fda_registered')}
- Non-GMO     : {comp_a.get('non_gmo')}
- Certs       : {cert_a}
- Lead time   : {comp_a.get('lead_time_days')} days
- Notes       : {comp_a.get('notes','')}

### Ingredient B — Proposed (consolidate TO)
- Ingredient  : {ing_b}
- Supplier    : {sup_b}
- Grade       : {comp_b.get('grade')}
- FDA reg     : {comp_b.get('fda_registered')}
- Non-GMO     : {comp_b.get('non_gmo')}
- Certs       : {cert_b}
- Lead time   : {comp_b.get('lead_time_days')} days
- Notes       : {comp_b.get('notes','')}

Can Ingredient B substitute for Ingredient A? Provide structured JSON evaluation."""

    try:
        response = client.models.generate_content(
            model=_MODEL,
            contents=user_msg,
            config=types.GenerateContentConfig(
                system_instruction=sys_prompt,
                response_mime_type="application/json",
                temperature=temperature,
            ),
        )
        result = json.loads(response.text.strip())
    except Exception as exc:
        result = {
            "substitutable": False, "confidence": 0.0,
            "recommendation": "HUMAN_REVIEW_REQUIRED",
            "reasoning": f"Evaluation error: {exc}",
            "evidence_trail": [], "compliance_met": False, "compliance_gaps": [],
        }

    result["sources_cited"] = [
        {"id": d["id"], "source": d["source"], "title": d["title"]}
        for d in retrieved_docs
    ]
    return result, retrieved_docs


# ─────────────────────────────────────────────────────────────────────────────
# Recommendation Card Formatter
# ─────────────────────────────────────────────────────────────────────────────

_VERDICT_EMOJI = {
    "APPROVE": "✅", "APPROVE_WITH_CONDITIONS": "⚠️",
    "REJECT": "❌", "HUMAN_REVIEW_REQUIRED": "🔍",
}
_VERDICT_COLORS = {
    "APPROVE":                 ("#dcfce7", "#15803d", "#86efac"),
    "APPROVE_WITH_CONDITIONS": ("#fef9c3", "#854d0e", "#fde047"),
    "REJECT":                  ("#fee2e2", "#991b1b", "#fca5a5"),
    "HUMAN_REVIEW_REQUIRED":   ("#ede9fe", "#5b21b6", "#c4b5fd"),
}


def _verdict_badge(verdict: str) -> str:
    bg, fg, border = _VERDICT_COLORS.get(verdict, ("#f1f5f9", "#334155", "#cbd5e1"))
    emoji = _VERDICT_EMOJI.get(verdict, "❓")
    label = verdict.replace("_", " ")
    return (
        f'<div style="display:inline-block;background:{bg};color:{fg};border:2px solid {border};'
        f'border-radius:8px;padding:10px 22px;font-weight:bold;font-size:1.05rem;margin:6px 0">'
        f'{emoji}&nbsp;&nbsp;{label}</div>'
    )


def _make_card(result: dict, source_labels: list, comp_b: dict, alt_num: int = 0) -> str:
    verdict = result.get("recommendation", "HUMAN_REVIEW_REQUIRED")
    emoji   = _VERDICT_EMOJI.get(verdict, "❓")
    conf    = result.get("confidence", 0.0)
    alt_tag = f"  *(Alternative #{alt_num})*" if alt_num > 0 else ""

    lines = [
        f"## {emoji} Agnes Recommendation{alt_tag}",
        f"**Verdict:** `{verdict}`  |  **Confidence:** {conf:.0%}",
        "",
        f"**Grade:** {comp_b.get('grade','—')}  "
        f"| **Lead time:** {comp_b.get('lead_time_days','—')} days  "
        f"| **FDA reg:** {comp_b.get('fda_registered','—')}",
        f"**Certifications:** {', '.join(comp_b.get('certifications', [])) or 'None'}",
        "",
        f"**Reasoning:**  {result.get('reasoning', '—')}",
    ]

    gaps = result.get("compliance_gaps", [])
    if gaps:
        lines += ["", "**Compliance Gaps:**"]
        for g in gaps:
            lines.append(f"- {g}")

    trail = result.get("evidence_trail", [])
    if trail:
        lines += ["", "**Evidence Trail:**"]
        for t in trail:
            lines.append(f"- {t}")

    sources = result.get("sources_cited", [])
    if sources:
        lines += ["", "**Regulatory Sources:**"]
        for s in sources:
            lines.append(f"- [{s.get('source','')}] {s.get('title','')}")

    if source_labels:
        lines += ["", "**Input sources processed:**"]
        for lbl in source_labels:
            lines.append(f"- `{lbl}`")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Gradio Handlers
# ─────────────────────────────────────────────────────────────────────────────

def _load_history() -> list[list]:
    path = Path("KB/decisions.json")
    if not path.exists():
        return []
    try:
        decisions = json.loads(path.read_text())
        rows = []
        for d in reversed(decisions[-10:]):
            rows.append([
                d.get("ingredient_a", ""),
                d.get("ingredient_b", ""),
                d.get("supplier_b", ""),
                d.get("verdict", ""),
                f"{d.get('confidence', 0):.0%}",
            ])
        return rows
    except Exception:
        return []


def _load_session_logs(filter_level: str = "All", tail: int = 100) -> str:
    """Load recent session log entries."""
    if not session_logger:
        return "No active session logger."
    
    log_path = session_logger.session_file_path
    if not log_path.exists():
        return "Session log file not found."
    
    try:
        lines = log_path.read_text(encoding='utf-8').strip().split('\n')
        
        # Parse JSON lines and filter
        filtered = []
        for line in lines[-tail:]:  # Get last N lines
            try:
                entry = json.loads(line)
                level = entry.get('level', 'INFO')
                
                if filter_level != "All" and level != filter_level:
                    continue
                
                timestamp = entry.get('timestamp', 'Unknown')
                message = entry.get('message', '')
                component = entry.get('component', '')
                
                # Format based on level
                prefix = f"[{timestamp}] {level}"
                if component:
                    prefix += f" [{component}]"
                
                filtered.append(f"{prefix}: {message}")
            except json.JSONDecodeError:
                # Non-JSON line, include as-is
                filtered.append(line)
        
        return '\n'.join(filtered) if filtered else "No log entries found."
    except Exception as e:
        return f"Error loading session logs: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# URL Detection & Scraper Integration
# ─────────────────────────────────────────────────────────────────────────────

_URL_PATTERN = re.compile(r'https?://[^\s<>"\']+')


def detect_urls(notes: str) -> tuple[str, list]:
    """Detect URLs in notes and return status HTML and URL list."""
    if not notes:
        return '<div style="color:#94a3b8;font-size:0.85rem;padding:4px 0">URLs detected: 0</div>', []
    
    urls = _URL_PATTERN.findall(notes)
    
    if not urls:
        return '<div style="color:#94a3b8;font-size:0.85rem;padding:4px 0">No URLs detected</div>', []
    
    # Format URL list for display
    url_list_html = '<div style="color:#15803d;font-size:0.85rem;padding:4px 0">'
    url_list_html += f'<strong>URLs detected: {len(urls)}</strong><ul style="margin:4px 0;padding-left:16px">'
    for url in urls:
        # Truncate long URLs for display
        display_url = url[:60] + "..." if len(url) > 60 else url
        url_list_html += f'<li>{display_url}</li>'
    url_list_html += '</ul></div>'
    
    session_logger.info(f"URL detection: found {len(urls)} URLs", extra={"urls": urls})
    
    return url_list_html, urls


def fetch_url_details(urls: list) -> tuple[str, list]:
    """Fetch details from detected URLs using appropriate scraper."""
    if not urls:
        return '<div style="color:#dc2626;padding:8px">No URLs to fetch</div>', []
    
    results = []
    status_html = '<div style="color:#2563eb;font-size:0.85rem;padding:8px;border-left:3px solid #2563eb;background:#eff6ff;margin:8px 0">'
    status_html += '<strong>📥 Fetching URL details...</strong><ul style="margin:4px 0;padding-left:16px">'
    
    for url in urls:
        from time import perf_counter
        start = perf_counter()
        
        try:
            # Determine URL type and use appropriate method
            url_lower = url.lower()
            
            if url_lower.endswith('.pdf'):
                # PDF - download and extract text
                status_html += f'<li>📄 PDF detected: {url[:50]}... (downloading)</li>'
                resp = requests.get(url, timeout=15, headers={"User-Agent": "Agnes/2.0"})
                resp.raise_for_status()
                duration = (perf_counter() - start) * 1000
                status_html += f'<li style="color:#16a34a">✓ Downloaded PDF ({len(resp.content)//1024}KB, {duration:.0f}ms)</li>'
                results.append({"url": url, "type": "pdf", "data": resp.content, "success": True})
                session_logger.log_scraper(url, True, "pdf_download", duration, size_kb=len(resp.content)//1024)
                
            elif any(url_lower.endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.webp', '.gif']):
                # Image - download for Vision API
                status_html += f'<li>🖼️ Image detected: {url[:50]}... (downloading)</li>'
                resp = requests.get(url, timeout=15, headers={"User-Agent": "Agnes/2.0"})
                resp.raise_for_status()
                duration = (perf_counter() - start) * 1000
                status_html += f'<li style="color:#16a34a">✓ Downloaded image ({len(resp.content)//1024}KB, {duration:.0f}ms)</li>'
                results.append({"url": url, "type": "image", "data": resp.content, "success": True})
                session_logger.log_scraper(url, True, "image_download", duration, size_kb=len(resp.content)//1024)
                
            else:
                # HTML page - scrape with BeautifulSoup
                status_html += f'<li>🌐 Web page: {url[:50]}... (scraping)</li>'
                resp = requests.get(url, timeout=15, headers={"User-Agent": "Agnes/2.0"})
                resp.raise_for_status()
                
                soup = BeautifulSoup(resp.text, "html.parser")
                # Remove script/style tags
                for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                    tag.decompose()
                
                title = soup.title.string.strip() if soup.title else "No title"
                text = soup.get_text(separator="\n", strip=True)[:2000]
                duration = (perf_counter() - start) * 1000
                
                status_html += f'<li style="color:#16a34a">✓ Scraped: {title[:60]} ({duration:.0f}ms)</li>'
                results.append({
                    "url": url, 
                    "type": "web", 
                    "title": title,
                    "text": text, 
                    "success": True
                })
                session_logger.log_scraper(url, True, "web_scrape", duration, title=title[:100])
                
        except Exception as e:
            duration = (perf_counter() - start) * 1000
            status_html += f'<li style="color:#dc2626">✗ Failed: {str(e)[:60]}</li>'
            results.append({"url": url, "type": "error", "error": str(e), "success": False})
            session_logger.log_scraper(url, False, "fetch", duration, error=str(e)[:100])
    
    status_html += '</ul></div>'
    
    return status_html, results


def submit_handler(
    ing_a, sup_a, ing_b, sup_b,
    notes, coa_image, audio_file, video_file, pdf_file,
    state, progress=gr.Progress(),
):
    # Log evaluation start
    session_logger.info("Evaluation started", extra={
        "ingredient_a": ing_a,
        "ingredient_b": ing_b,
        "supplier_a": sup_a,
        "supplier_b": sup_b,
        "has_notes": bool(notes and notes.strip()),
        "has_coa_image": coa_image is not None,
        "has_audio": audio_file is not None,
        "has_video": video_file is not None,
        "has_pdf": pdf_file is not None,
    })
    
    if not ing_a.strip() or not ing_b.strip():
        session_logger.warning("Evaluation rejected - missing ingredient names")
        return (
            "**Please enter Ingredient A and Ingredient B names.**  \n"
            "*For an overall supply chain health check, use the **📊 General Assessment** tab.*",
            "<div style='color:#64748b;font-size:0.9rem;padding:8px 0'>Awaiting evaluation…</div>",
            gr.update(interactive=False), gr.update(interactive=False),
            gr.update(interactive=False), state,
        )

    # Progress: Document ingestion (0-20%)
    progress(0.05, desc="Processing uploaded documents...")
    
    # Assemble multimodal parts
    with log_operation(session_logger, "build_parts", "ui"):
        parts, labels = _build_parts(notes, coa_image, audio_file, video_file, pdf_file)
    
    session_logger.info("Parts assembled", extra={"part_count": len(parts), "labels": labels})
    
    # Progress: URL fetching (20-40%) - if URLs were detected
    progress(0.20, desc="Fetching external data...")

    # Progress: Compliance extraction (40-60%)
    progress(0.40, desc="Extracting compliance data...")
    
    # Extract compliance data for ingredient B from all uploaded documents
    comp_b = _extract_compliance(parts, sup_b or "Unknown Supplier", ing_b)
    comp_b.setdefault("organic_certified", False)
    
    # Progress: RAG retrieval (60-80%)
    progress(0.60, desc="Querying RAG index...")

    # Ingredient A: use a reasonable pharmaceutical baseline
    comp_a = {
        "organic_certified": False, "fda_registered": True, "non_gmo": True,
        "grade": "pharmaceutical", "lead_time_days": 14,
        "certifications": ["USP", "GMP", "Halal", "Kosher"],
        "notes": "Baseline — standard pharmaceutical-grade reference.",
    }

    # Progress: LLM evaluation (80-100%)
    progress(0.80, desc="Running LLM evaluation...")

    # Evaluate (no auto-store)
    with log_operation(session_logger, "rag_evaluate", "rag"):
        result, docs = _evaluate(
            ing_a, sup_a or "Current Supplier", comp_a,
            ing_b, sup_b or "Proposed Supplier", comp_b,
        )

    new_state = {
        "result": result, "docs": docs,
        "ing_a": ing_a, "sup_a": sup_a or "Current Supplier",
        "comp_a": comp_a,
        "ing_b": ing_b, "sup_b": sup_b or "Proposed Supplier",
        "comp_b": comp_b, "labels": labels,
        "alt_count": 0,
        "last_verdict": result.get("recommendation"),
    }

    # Progress: Complete
    progress(1.0, desc="Evaluation complete!")
    
    verdict = result.get("recommendation", "HUMAN_REVIEW_REQUIRED")
    confidence = result.get("confidence", 0.0)
    
    # Log evaluation completion
    session_logger.log_evaluation(
        ingredient_a=ing_a,
        ingredient_b=ing_b,
        verdict=verdict,
        confidence=confidence,
        supplier_a=sup_a or "Current Supplier",
        supplier_b=sup_b or "Proposed Supplier",
        docs_retrieved=len(docs),
    )
    
    card  = _make_card(result, labels, comp_b)
    badge = _verdict_badge(verdict)
    return (
        card,
        badge,
        gr.update(interactive=True),
        gr.update(interactive=True),
        gr.update(interactive=True),
        new_state,
    )


def apply_handler(state):
    if not state:
        session_logger.warning("Apply attempted with no evaluation")
        return "No evaluation to apply.", state, _load_history()
    r = state["result"]
    verdict = r.get("recommendation", "")
    
    session_logger.info("Decision applied by user", extra={
        "ingredient_a": state["ing_a"],
        "ingredient_b": state["ing_b"],
        "verdict": verdict,
        "confidence": r.get("confidence", 0.0),
    })
    
    store_decision({
        "ingredient_a":    state["ing_a"],
        "ingredient_b":    state["ing_b"],
        "supplier_a":      state["sup_a"],
        "supplier_b":      state["sup_b"],
        "grade_a":         state["comp_a"].get("grade", ""),
        "grade_b":         state["comp_b"].get("grade", ""),
        "certifications_a": state["comp_a"].get("certifications", []),
        "certifications_b": state["comp_b"].get("certifications", []),
        "verdict":         r.get("recommendation", ""),
        "confidence":      r.get("confidence", 0.0),
        "reasoning":       r.get("reasoning", "")[:400],
        "evidence_trail":  r.get("evidence_trail", []),
        "sources_cited":   r.get("sources_cited", []),
    })
    return (
        f"**Decision saved** — `{verdict}` stored in KB/decisions.json.",
        None,
        _load_history(),
    )


def alternative_handler(state):
    if not state:
        session_logger.warning("Alternative requested with no evaluation")
        return "Submit an evaluation first.", state
    
    if state["alt_count"] >= 3:
        session_logger.info("Maximum alternatives reached", extra={
            "alt_count": state["alt_count"],
            "ingredient_a": state["ing_a"],
            "ingredient_b": state["ing_b"],
        })
        return "**No more alternatives** — maximum 3 alternatives reached. Please apply or reject.", state
    
    alt_num = state["alt_count"] + 1
    last_verdict = state.get("last_verdict")
    
    session_logger.info(f"Generating alternative #{alt_num}", extra={
        "alt_num": alt_num,
        "ingredient_a": state["ing_a"],
        "ingredient_b": state["ing_b"],
        "previous_verdict": last_verdict,
    })

    result, docs = _evaluate(
        state["ing_a"], state["sup_a"], state["comp_a"],
        state["ing_b"], state["sup_b"], state["comp_b"],
        temperature=0.4 + alt_num * 0.1,
        exclude_verdict=last_verdict,
    )

    new_state = {**state, "result": result, "docs": docs,
                 "alt_count": alt_num, "last_verdict": result.get("recommendation")}
    verdict = result.get("recommendation", "HUMAN_REVIEW_REQUIRED")
    confidence = result.get("confidence", 0.0)
    
    session_logger.log_evaluation(
        ingredient_a=state["ing_a"],
        ingredient_b=state["ing_b"],
        verdict=verdict,
        confidence=confidence,
        supplier_a=state["sup_a"],
        supplier_b=state["sup_b"],
        is_alternative=True,
        alt_num=alt_num,
    )
    
    card  = _make_card(result, state["labels"], state["comp_b"], alt_num=alt_num)
    badge = _verdict_badge(verdict)
    return card, badge, new_state


def reject_handler(state):
    if not state:
        session_logger.warning("Reject attempted with no evaluation")
        return "No evaluation to reject.", state, _load_history()
    
    session_logger.info("Decision rejected by user", extra={
        "ingredient_a": state["ing_a"],
        "ingredient_b": state["ing_b"],
        "previous_verdict": state["result"].get("recommendation"),
        "confidence": state["result"].get("confidence", 0.0),
    })
    
    store_decision({
        "ingredient_a":    state["ing_a"],
        "ingredient_b":    state["ing_b"],
        "supplier_a":      state["sup_a"],
        "supplier_b":      state["sup_b"],
        "grade_a":         state["comp_a"].get("grade", ""),
        "grade_b":         state["comp_b"].get("grade", ""),
        "certifications_a": state["comp_a"].get("certifications", []),
        "certifications_b": state["comp_b"].get("certifications", []),
        "verdict":         "REJECT",
        "confidence":      state["result"].get("confidence", 0.0),
        "reasoning":       "User manually rejected all recommendations.",
        "evidence_trail":  [],
        "sources_cited":   [],
    })
    return "**Rejected** — stored in KB/decisions.json.", None, _load_history()


# ─────────────────────────────────────────────────────────────────────────────
# General Assessment — DB, Charts, Gemini Health Report
# ─────────────────────────────────────────────────────────────────────────────

_DB_PATH = Path(__file__).parent / "DB" / "db.sqlite"

_ASSESSMENT_PROMPT = """\
You are Agnes, an AI supply chain analyst for the CPG industry.
Analyze the supply chain statistics below and produce a health assessment in valid JSON only.

OUTPUT FORMAT (no markdown fences):
{
  "health_score": <float 1.0-10.0>,
  "headline": "<one concise sentence summarising the biggest finding>",
  "top_opportunities": [
    "<opportunity 1 with specific ingredient name and estimated impact>",
    "<opportunity 2>",
    "<opportunity 3>"
  ],
  "critical_risks": ["<risk 1>", "<risk 2>"],
  "quick_wins": ["<actionable win 1>", "<actionable win 2>", "<actionable win 3>"],
  "strategic_recommendation": "<2-3 sentence strategic narrative>"
}

Scoring guide: 9-10 excellent | 7-8 good | 5-6 moderate | 3-4 poor | 1-2 critical\
"""


def _load_db_stats() -> dict:
    conn = sqlite3.connect(str(_DB_PATH))
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM Company")
    n_companies = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM Supplier")
    n_suppliers = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM Product WHERE Type='raw-material'")
    n_raw = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM BOM_Component")
    n_bom = cur.fetchone()[0]

    cur.execute("""
        WITH ing AS (
          SELECT SUBSTR(SKU, INSTR(SUBSTR(SKU,4),'-')+4,
                 LENGTH(SKU)-INSTR(SUBSTR(SKU,4),'-')-3-9) AS ingredient, Id
          FROM Product WHERE Type='raw-material'
        )
        SELECT ingredient, COUNT(*) AS sku_count
        FROM ing GROUP BY ingredient ORDER BY sku_count DESC LIMIT 12
    """)
    fragmented = cur.fetchall()

    cur.execute("""
        SELECT s.Name, COUNT(DISTINCT bc.BOMId) AS bom_count
        FROM Supplier s
        JOIN Supplier_Product sp ON s.Id = sp.SupplierId
        JOIN BOM_Component bc ON bc.ConsumedProductId = sp.ProductId
        GROUP BY s.Id ORDER BY bom_count DESC LIMIT 10
    """)
    top_suppliers = cur.fetchall()

    cur.execute("""
        SELECT COUNT(*) FROM (
          SELECT ProductId FROM Supplier_Product
          JOIN Product ON Product.Id = Supplier_Product.ProductId
          WHERE Product.Type='raw-material'
          GROUP BY ProductId HAVING COUNT(SupplierId) = 1
        )
    """)
    single_supplier = cur.fetchone()[0]
    conn.close()

    return {
        "n_companies": n_companies, "n_suppliers": n_suppliers,
        "n_raw_materials": n_raw, "n_bom_links": n_bom,
        "fragmented": fragmented, "top_suppliers": top_suppliers,
        "single_supplier_skus": single_supplier,
    }


def _build_charts(stats: dict):
    import plotly.graph_objects as go

    frag = stats["fragmented"]
    ing_names = [r[0].replace("-", " ").title() for r in frag]
    ing_counts = [r[1] for r in frag]
    fig1 = go.Figure(go.Bar(
        x=ing_counts, y=ing_names, orientation="h",
        marker_color="#3b82f6", text=ing_counts, textposition="outside",
    ))
    fig1.update_layout(
        title="Most Fragmented Ingredients (duplicate SKUs across companies)",
        xaxis_title="Number of separate SKUs",
        yaxis=dict(autorange="reversed"),
        height=420, margin=dict(l=220, r=60, t=50, b=40),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    )

    sup_data = stats["top_suppliers"]
    sup_names  = [r[0] for r in sup_data]
    sup_counts = [r[1] for r in sup_data]
    colors = ["#ef4444" if b > 100 else "#f97316" if b > 60 else "#3b82f6" for b in sup_counts]
    fig2 = go.Figure(go.Bar(
        x=sup_counts, y=sup_names, orientation="h",
        marker_color=colors, text=sup_counts, textposition="outside",
    ))
    fig2.update_layout(
        title="Top Suppliers by BOM Coverage  (🔴 > 100 BOMs = concentration risk)",
        xaxis_title="Number of BOMs supplied",
        yaxis=dict(autorange="reversed"),
        height=380, margin=dict(l=180, r=60, t=50, b=40),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig1, fig2


def _build_kpi_html(stats: dict) -> str:
    cards = [
        ("🏢", stats["n_companies"],    "CPG Companies"),
        ("🏭", stats["n_suppliers"],    "Suppliers"),
        ("🧪", stats["n_raw_materials"],"Raw-Material SKUs"),
        ("🔗", stats["n_bom_links"],    "BOM Component Links"),
    ]
    items = "".join(
        f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;'
        f'padding:18px;text-align:center">'
        f'<div style="font-size:1.8rem">{icon}</div>'
        f'<div style="font-size:2rem;font-weight:bold;color:#1e40af">{num}</div>'
        f'<div style="font-size:0.82rem;color:#64748b;margin-top:4px">{label}</div>'
        f'</div>'
        for icon, num, label in cards
    )
    return (
        f'<div style="display:grid;grid-template-columns:repeat(4,1fr);'
        f'gap:12px;margin-bottom:8px">{items}</div>'
    )


def _generate_health_report(stats: dict) -> dict:
    top_frags = "\n".join(f"  - {r[0]}: {r[1]} SKUs" for r in stats["fragmented"][:6])
    top_sups  = "\n".join(f"  - {r[0]}: {r[1]} BOMs" for r in stats["top_suppliers"][:5])
    context = (
        f"Supply Chain Statistics:\n"
        f"- {stats['n_companies']} CPG companies, {stats['n_suppliers']} suppliers\n"
        f"- {stats['n_raw_materials']} raw-material SKUs "
        f"({stats['single_supplier_skus']} sourced from only 1 supplier)\n"
        f"- {stats['n_bom_links']} BOM component links\n\n"
        f"Top fragmented ingredients (most duplicate SKUs across companies):\n{top_frags}\n\n"
        f"Top suppliers by BOM coverage:\n{top_sups}\n\n"
        f"Core problem: identical ingredients are purchased under separate company-specific "
        f"SKUs, preventing volume consolidation and increasing compliance risk.\n\n"
        + _ASSESSMENT_PROMPT
    )
    try:
        response = client.models.generate_content(
            model=_MODEL,
            contents=context,
            config=types.GenerateContentConfig(
                response_mime_type="application/json", temperature=0.3,
            ),
        )
        return json.loads(response.text.strip())
    except Exception as exc:
        return {
            "health_score": 5.0,
            "headline": f"Assessment unavailable — {exc}",
            "top_opportunities": ["Check GEMINI_API_KEY in .env and restart."],
            "critical_risks": [str(exc)],
            "quick_wins": [],
            "strategic_recommendation": "Unable to generate assessment.",
        }


def _render_health_card(report: dict, stats: dict) -> str:
    score = float(report.get("health_score", 5.0))
    gauge = "🔴" if score < 4 else "🟡" if score < 7 else "🟢"
    lines = [
        f"## {gauge} Supply Chain Health Score: **{score:.1f} / 10**",
        "",
        f"**{report.get('headline', '')}**",
        "",
        f"*Based on {stats['n_companies']} companies · {stats['n_suppliers']} suppliers · "
        f"{stats['n_raw_materials']} raw-material SKUs · "
        f"{stats['single_supplier_skus']} single-source SKUs*",
        "",
        "---",
        "",
        "### 🎯 Top Consolidation Opportunities",
    ]
    for opp in report.get("top_opportunities", []):
        lines.append(f"- {opp}")
    lines += ["", "### ⚠️ Critical Risks"]
    for risk in report.get("critical_risks", []):
        lines.append(f"- {risk}")
    lines += ["", "### 💡 Quick Wins"]
    for win in report.get("quick_wins", []):
        lines.append(f"- {win}")
    lines += [
        "", "---", "",
        f"**Strategic Recommendation:** {report.get('strategic_recommendation', '')}",
    ]
    return "\n".join(lines)


def assessment_handler():
    try:
        stats = _load_db_stats()
    except Exception as exc:
        err = f"**Database error:** {exc}"
        return err, None, None, err
    kpi_html   = _build_kpi_html(stats)
    fig1, fig2 = _build_charts(stats)
    report     = _generate_health_report(stats)
    report_md  = _render_health_card(report, stats)
    return kpi_html, fig1, fig2, report_md


def _history_stats_html() -> str:
    path = Path("KB/decisions.json")
    if not path.exists():
        return "<p style='color:#94a3b8'>No decisions recorded yet.</p>"
    try:
        decisions = json.loads(path.read_text())
        total = len(decisions)
        if total == 0:
            return "<p style='color:#94a3b8'>No decisions recorded yet.</p>"
        approved = sum(1 for d in decisions if d.get("verdict") in
                       ("APPROVE", "APPROVE_WITH_CONDITIONS"))
        rejected = sum(1 for d in decisions if d.get("verdict") == "REJECT")
        avg_conf = sum(d.get("confidence", 0) for d in decisions) / total
        def _kpi(num, label, color="#1e40af"):
            return (
                f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;'
                f'padding:14px 10px;text-align:center;flex:1">'
                f'<div style="font-size:1.8rem;font-weight:bold;color:{color}">{num}</div>'
                f'<div style="font-size:0.8rem;color:#64748b;margin-top:2px">{label}</div>'
                f'</div>'
            )
        return (
            f'<div style="display:flex;gap:12px;margin-bottom:14px">'
            + _kpi(total,          "Total Decisions")
            + _kpi(approved,       "Approved",   "#15803d")
            + _kpi(rejected,       "Rejected",   "#dc2626")
            + _kpi(f"{avg_conf:.0%}", "Avg Confidence")
            + "</div>"
        )
    except Exception:
        return "<p style='color:#94a3b8'>Error loading history.</p>"


# ─────────────────────────────────────────────────────────────────────────────
# Gradio UI
# ─────────────────────────────────────────────────────────────────────────────

_CSS = """
/* ── Agnes UI v2 ── */
.recommendation-card { font-size: 0.95rem; line-height: 1.7; }
.status-ok  { color: #16a34a; font-weight: bold; }
.status-err { color: #dc2626; font-weight: bold; }
footer { display: none !important; }
.tab-nav button { font-size: 1rem; font-weight: 600; padding: 10px 20px; }
"""

_THEME = gr.themes.Base(
    primary_hue=gr.themes.colors.blue,
    neutral_hue=gr.themes.colors.slate,
    font=[gr.themes.GoogleFont("Inter"), "ui-sans-serif", "sans-serif"],
).set(
    button_primary_background_fill="#2563eb",
    button_primary_background_fill_hover="#1d4ed8",
    block_label_text_weight="600",
)

with gr.Blocks(title="Agnes 2.0 — Supply Chain Intelligence") as demo:

    gr.HTML(
        '<div style="padding:18px 0 10px;border-bottom:1px solid #e2e8f0;margin-bottom:16px">'
        '<h1 style="margin:0;font-size:1.6rem;font-weight:700;color:#1e293b">'
        '🧬 Agnes 2.0 — Supply Chain Intelligence</h1>'
        '<p style="margin:4px 0 0;color:#64748b;font-size:0.92rem">'
        'Multimodal compliance evaluation · RAG-augmented · Gemini Flash</p>'
        '</div>'
    )

    eval_state = gr.State(None)

    with gr.Tabs(elem_classes=["tab-nav"]):

        # ══════════════════════════════════════════════════════════════════
        # TAB 1 — Evaluate Substitution
        # ══════════════════════════════════════════════════════════════════
        with gr.TabItem("🔍  Evaluate Substitution"):
            with gr.Row():
                # ── Left: inputs ─────────────────────────────────────────
                with gr.Column(scale=1):
                    gr.Markdown("#### Ingredient A — Current (baseline)")
                    ing_a = gr.Textbox(label="Ingredient A name",
                                       placeholder="vitamin-d3-cholecalciferol")
                    sup_a = gr.Textbox(label="Current supplier",
                                       placeholder="Prinova USA")

                    gr.Markdown("#### Ingredient B — Proposed substitute")
                    ing_b = gr.Textbox(label="Ingredient B name",
                                       placeholder="vitamin-d3-cholecalciferol")
                    sup_b = gr.Textbox(label="Proposed supplier",
                                       placeholder="PureBulk")

                    with gr.Accordion("📎 Supporting Evidence (all optional)", open=False):
                        notes = gr.Textbox(
                            label="Notes / URLs",
                            placeholder=(
                                "Free-form notes, or paste URLs:\n"
                                "https://supplier.com/product-page\n"
                                "https://example.com/coa.pdf"
                            ),
                            lines=3,
                        )
                        # URL detection UI
                        url_status = gr.HTML(
                            '<div style="color:#94a3b8;font-size:0.85rem;padding:4px 0">'
                            'URLs detected: 0</div>',
                            visible=True,
                        )
                        with gr.Row():
                            detect_btn = gr.Button("🔍 Detect URLs", size="sm", variant="secondary")
                            fetch_btn = gr.Button("📥 Fetch URL Details", size="sm", variant="primary", interactive=False)
                        fetch_status = gr.HTML(visible=False)
                        
                        coa_image  = gr.Image(label="CoA Image (PNG/JPG)",  type="filepath")
                        audio_file = gr.Audio(label="Audio Note (MP3/WAV)", type="filepath")
                        video_file = gr.Video(label="Video (facility/demo)")
                        pdf_file   = gr.File(label="PDF Document",          file_types=[".pdf"])
                        
                        # Hidden state for detected URLs
                        detected_urls_state = gr.State([])

                    evaluate_btn = gr.Button("⚡ Evaluate", variant="primary", size="lg")

                # ── Right: outputs ────────────────────────────────────────
                with gr.Column(scale=1):
                    gr.Markdown("#### Agnes Recommendation")
                    verdict_badge = gr.HTML(
                        '<div style="color:#94a3b8;font-size:0.9rem;padding:6px 0">'
                        'Awaiting evaluation…</div>'
                    )
                    result_md = gr.Markdown(
                        "*Fill in at least the ingredient names, then click Evaluate.*",
                        elem_classes=["recommendation-card"],
                    )
                    with gr.Row():
                        apply_btn  = gr.Button("✅ Apply & Save",     variant="primary",   interactive=False)
                        alt_btn    = gr.Button("🔄 Show Alternative", variant="secondary",  interactive=False)
                        reject_btn = gr.Button("❌ Reject All",        variant="stop",       interactive=False)
                    status_md = gr.Markdown("")

        # ══════════════════════════════════════════════════════════════════
        # TAB 2 — General Assessment
        # ══════════════════════════════════════════════════════════════════
        with gr.TabItem("📊  General Assessment"):
            gr.Markdown(
                "Run a full supply chain health check powered by live DB analytics and "
                "Gemini AI — no inputs required."
            )
            assess_btn = gr.Button("🚀 Run General Assessment", variant="primary", size="lg")

            kpi_html = gr.HTML(
                '<div style="color:#94a3b8;font-size:0.9rem;padding:12px 0">'
                'Click the button above to analyse the supply chain database.</div>'
            )

            with gr.Row():
                chart1 = gr.Plot(label="Ingredient Fragmentation")
                chart2 = gr.Plot(label="Supplier BOM Coverage")

            health_md = gr.Markdown("")

        # ══════════════════════════════════════════════════════════════════
        # TAB 3 — Decision History
        # ══════════════════════════════════════════════════════════════════
        with gr.TabItem("📋  Decision History"):
            history_stats = gr.HTML(_history_stats_html())
            history_table = gr.Dataframe(
                headers=["Ingredient A", "Ingredient B", "Supplier B", "Verdict", "Confidence"],
                value=_load_history(),
                interactive=False,
            )
            refresh_btn = gr.Button("🔄 Refresh", variant="secondary", size="sm")

        # ══════════════════════════════════════════════════════════════════
        # TAB 4 — Session Logs
        # ══════════════════════════════════════════════════════════════════
        with gr.TabItem("🔍  Session Logs"):
            gr.Markdown("View real-time session activity and system events for debugging.")
            
            session_info = gr.HTML(
                f'<div style="color:#64748b;font-size:0.85rem;padding:8px 0">'
                f'Session ID: {session_logger.session_id if session_logger else "N/A"}<br>'
                f'Log file: {session_logger.session_file_path if session_logger else "N/A"}'
                f'</div>'
            )
            
            log_filter = gr.Dropdown(
                choices=["All", "INFO", "WARNING", "ERROR", "DEBUG"],
                value="All",
                label="Filter by level",
            )
            
            session_logs = gr.Textbox(
                label="Session Activity Log",
                lines=20,
                max_lines=40,
                interactive=False,
                value="Click refresh to load session logs...",
            )
            
            with gr.Row():
                refresh_logs_btn = gr.Button("🔄 Refresh Logs", variant="secondary", size="sm")
                download_logs_btn = gr.Button("⬇️ Download Session Log", variant="secondary", size="sm")
            
            system_status = gr.HTML(
                '<div style="color:#94a3b8;font-size:0.85rem;padding:8px 0">'
                'System log: logs/system.log</div>'
            )

    # ── Wire up handlers ──────────────────────────────────────────────────
    
    # URL detection handlers
    detect_btn.click(
        fn=detect_urls,
        inputs=[notes],
        outputs=[url_status, detected_urls_state],
    ).then(
        fn=lambda urls: gr.update(interactive=bool(urls)),
        inputs=[detected_urls_state],
        outputs=[fetch_btn],
    )
    
    fetch_btn.click(
        fn=fetch_url_details,
        inputs=[detected_urls_state],
        outputs=[fetch_status, gr.State()],  # State stores results for later use
    )
    
    evaluate_btn.click(
        fn=submit_handler,
        inputs=[ing_a, sup_a, ing_b, sup_b, notes, coa_image,
                audio_file, video_file, pdf_file, eval_state],
        outputs=[result_md, verdict_badge, apply_btn, alt_btn, reject_btn, eval_state],
    )
    apply_btn.click(
        fn=apply_handler,
        inputs=[eval_state],
        outputs=[status_md, eval_state, history_table],
    )
    alt_btn.click(
        fn=alternative_handler,
        inputs=[eval_state],
        outputs=[result_md, verdict_badge, eval_state],
    )
    reject_btn.click(
        fn=reject_handler,
        inputs=[eval_state],
        outputs=[status_md, eval_state, history_table],
    )
    assess_btn.click(
        fn=assessment_handler,
        inputs=[],
        outputs=[kpi_html, chart1, chart2, health_md],
    )
    refresh_btn.click(
        fn=lambda: (_history_stats_html(), _load_history()),
        inputs=[],
        outputs=[history_stats, history_table],
    )
    
    # Session logs refresh handler
    refresh_logs_btn.click(
        fn=_load_session_logs,
        inputs=[log_filter],
        outputs=[session_logs],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Launch
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        show_error=True,
        theme=_THEME,
        css=_CSS,
    )
