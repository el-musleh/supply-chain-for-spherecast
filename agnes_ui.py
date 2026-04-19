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
import atexit
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
KB_PATH = Path("KB/regulatory_docs.json")

# Check if KB file exists before attempting to load
if not KB_PATH.exists():
    rag_index = None
    print(f"  ⚠ KB file not found: {KB_PATH}")
    print(f"  Run: python scrape_kb.py")
    print(f"  Evaluation will proceed without RAG context")
else:
    try:
        rag_index = build_index(str(KB_PATH))
        print(f"  RAG index ready — {len(rag_index.docs)} documents")
    except Exception as _e:
        rag_index = None
        print(f"  ⚠ RAG index load failed: {_e}")
        print(f"  Evaluation will proceed without RAG context")

_MODEL = "gemini-flash-latest"
_MAX_INLINE_BYTES = 15 * 1024 * 1024   # 15 MB inline limit (safe margin)
_URL_PATTERN = re.compile(r"https?://[^\s]+")

AGNES_SYSTEM_PROMPT = """\
You are Agnes, an AI supply chain reasoning agent for the CPG (Consumer Packaged Goods) industry.
Your role is to evaluate whether two raw-material ingredient variants are functionally substitutable
for sourcing consolidation purposes, AND — when supply/cost/logistics data is provided — to make
a smart sourcing decision between an external Purchase Order (PO) and an internal Transfer Order (TO).

You reason carefully from:
1. Chemical and functional identity of the ingredients
2. Regulatory grade requirements (pharmaceutical vs. food vs. technical)
3. Certifications required by the end products (USP, NSF, GMP, Halal, Kosher, Non-GMO, Organic)
4. Lead time feasibility and urgency
5. Known industry standards (USP monographs, FDA 21 CFR, EU regulations)
6. Total Landed Cost: PO (material + external shipping) vs. TO (internal freight only — material is already owned)
7. Safety stock constraints: a TO is only valid if the branch has stock ABOVE its safety limit

PO vs TO DECISION RULES (apply when supply scenario data is provided):
- Scenario A — No-brainer TO: TO cost < PO cost AND TO lead_time < PO lead_time → recommend TRANSFER_ORDER
- Scenario B — Cost saver TO: TO cheaper AND factory has buffer days remaining → recommend TRANSFER_ORDER
- Scenario C — Emergency PO: factory has 0 buffer days AND PO lead_time < TO lead_time → recommend PO even if costlier
- Scenario D — Bulk PO: internal freight cost > PO total cost → recommend FULL_REPLACE (external PO)
- SPLIT_TO_PO: branch has some but not enough excess → transfer available excess, PO the remainder
- SPLIT_PO: supplier delivers partial quantity, source remainder from alternative external supplier

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
  "recommendation": "<APPROVE | APPROVE_WITH_CONDITIONS | SPLIT_PO | FULL_REPLACE | TRANSFER_ORDER | SPLIT_TO_PO | REJECT | HUMAN_REVIEW_REQUIRED>",
  "decision_options": [
    {
      "type": "<TRANSFER_ORDER | SPLIT_TO_PO | SPLIT_PO | FULL_REPLACE | APPROVE>",
      "label": "<short human-readable label>",
      "detail": "<specific quantities and supplier names>",
      "risk": "<key risk of this option>",
      "confidence": <float 0.0-1.0>
    }
  ]
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

import time

def _gemini_generate(contents, config, retries: int = 3) -> str:
    """
    Call Gemini with automatic retry on 429 rate-limit errors.
    Respects the retryDelay hint from the API response when available.
    """
    for attempt in range(retries):
        try:
            response = client.models.generate_content(
                model=_MODEL, contents=contents, config=config,
            )
            return response.text.strip()
        except Exception as exc:
            msg = str(exc)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                # Parse suggested retry delay from error if present
                delay = 15.0
                import re as _re
                m = _re.search(r"retryDelay.*?(\d+)s", msg)
                if m:
                    delay = float(m.group(1)) + 2
                if attempt < retries - 1:
                    logger.warning(f"Rate limit hit — retrying in {delay:.0f}s (attempt {attempt+1}/{retries})")
                    time.sleep(delay)
                    continue
            raise
    raise RuntimeError("Gemini call failed after retries")


def _extract_compliance(parts: list, supplier: str, ingredient: str) -> dict:
    """Extract structured compliance data from uploaded documents."""
    if not parts:
        return {
            "organic_certified": False, "fda_registered": True,
            "non_gmo": False, "grade": "food", "lead_time_days": 14,
            "certifications": [], "notes": "No documents provided — using defaults.",
        }
    try:
        text = _gemini_generate(
            contents=parts + [types.Part.from_text(_EXTRACTION_PROMPT)],
            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.1),
        )
        extracted = json.loads(text)
        extracted.setdefault("notes", f"Extracted from {len(parts)} input(s).")
        return extracted
    except Exception as exc:
        return {
            "organic_certified": False, "fda_registered": True,
            "non_gmo": False, "grade": "food", "lead_time_days": 14,
            "certifications": [], "notes": f"Extraction error: {exc}",
        }


_IDENTITY_AND_COMPLIANCE_PROMPT = """\
From the attached document(s), extract ALL of the following in one pass and return ONLY valid JSON:
{
  "ingredient": "<ingredient name found in the document>",
  "supplier": "<supplier or company name>",
  "context": "<one-line summary of any shortage, supply issue, or compliance note>",
  "organic_certified": <bool>,
  "fda_registered": <bool>,
  "non_gmo": <bool>,
  "grade": "<pharmaceutical | food | technical>",
  "lead_time_days": <int, default 14 if unknown>,
  "certifications": ["<cert name>"],
  "notes": "<one sentence compliance summary>"
}
Return empty strings for text fields that cannot be determined; use false/14/[] for others.\
"""


def _extract_identity_and_compliance(parts: list) -> tuple[dict, dict]:
    """
    Single LLM call that extracts both the ingredient identity AND compliance data from documents.
    Returns (identity_dict, compliance_dict) — saves one API call vs calling them separately.
    """
    try:
        text = _gemini_generate(
            contents=parts + [types.Part.from_text(_IDENTITY_AND_COMPLIANCE_PROMPT)],
            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.1),
        )
        data = json.loads(text)
        identity = {
            "ingredient": data.get("ingredient", ""),
            "supplier":   data.get("supplier", ""),
            "context":    data.get("context", ""),
        }
        compliance = {
            "organic_certified": data.get("organic_certified", False),
            "fda_registered":    data.get("fda_registered", True),
            "non_gmo":           data.get("non_gmo", False),
            "grade":             data.get("grade", "food"),
            "lead_time_days":    data.get("lead_time_days", 14),
            "certifications":    data.get("certifications", []),
            "notes":             data.get("notes", f"Extracted from {len(parts)} input(s)."),
        }
        return identity, compliance
    except Exception as exc:
        identity = {"ingredient": "", "supplier": "", "context": ""}
        compliance = {
            "organic_certified": False, "fda_registered": True,
            "non_gmo": False, "grade": "food", "lead_time_days": 14,
            "certifications": [], "notes": f"Extraction error: {exc}",
        }
        return identity, compliance


def _extract_identity(parts: list) -> dict:
    """Kept for compatibility — uses the combined call and returns only identity."""
    identity, _ = _extract_identity_and_compliance(parts)
    return identity


# ─────────────────────────────────────────────────────────────────────────────
# RAG Evaluation (does NOT auto-store — confirmation required)
# ─────────────────────────────────────────────────────────────────────────────

def _evaluate(
    ing_a: str, sup_a: str, comp_a: dict,
    ing_b: str, sup_b: str, comp_b: dict,
    temperature: float = 0.2,
    exclude_verdict: str | None = None,
    supply_scenario_block: str | None = None,
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

    if supply_scenario_block:
        user_msg += supply_scenario_block

    try:
        text = _gemini_generate(
            contents=user_msg,
            config=types.GenerateContentConfig(
                system_instruction=sys_prompt,
                response_mime_type="application/json",
                temperature=temperature,
            ),
        )
        result = json.loads(text)
    except Exception as exc:
        err_msg = str(exc)
        if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
            friendly = (
                "⚠️ API rate limit reached. The free tier allows ~20 requests/day. "
                "Please wait a few minutes and try again, or upgrade your Gemini API plan."
            )
        else:
            friendly = f"Evaluation failed: {err_msg[:200]}"
        result = {
            "substitutable": False, "confidence": 0.0,
            "recommendation": "HUMAN_REVIEW_REQUIRED",
            "reasoning": friendly,
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
    "APPROVE":                  "✅",
    "APPROVE_WITH_CONDITIONS":  "⚠️",
    "SPLIT_PO":                 "⚡",
    "FULL_REPLACE":             "🔁",
    "TRANSFER_ORDER":           "🔄",
    "SPLIT_TO_PO":              "↔️",
    "REJECT":                   "❌",
    "HUMAN_REVIEW_REQUIRED":    "🔍",
}
_VERDICT_COLORS = {
    "APPROVE":                 ("#dcfce7", "#15803d", "#86efac"),
    "APPROVE_WITH_CONDITIONS": ("#fef9c3", "#854d0e", "#fde047"),
    "SPLIT_PO":                ("#fef3c7", "#92400e", "#fcd34d"),
    "FULL_REPLACE":            ("#fee2e2", "#991b1b", "#fca5a5"),
    "TRANSFER_ORDER":          ("#dbeafe", "#1d4ed8", "#93c5fd"),
    "SPLIT_TO_PO":             ("#ede9fe", "#5b21b6", "#c4b5fd"),
    "REJECT":                  ("#fee2e2", "#991b1b", "#fca5a5"),
    "HUMAN_REVIEW_REQUIRED":   ("#f1f5f9", "#334155", "#cbd5e1"),
}


def _verdict_badge(verdict: str) -> str:
    bg, fg, border = _VERDICT_COLORS.get(verdict, ("#f1f5f9", "#334155", "#cbd5e1"))
    emoji = _VERDICT_EMOJI.get(verdict, "❓")
    label = verdict.replace("_", " ").title()
    return (
        f'<div style="'
        f'display:inline-flex;align-items:center;gap:8px;'
        f'background:{bg};color:{fg};'
        f'border:1.5px solid {border};'
        f'border-radius:10px;padding:10px 20px;'
        f'font-weight:700;font-size:0.92rem;'
        f'letter-spacing:0.01em;'
        f'box-shadow:0 2px 6px {border}66;'
        f'margin:4px 0">'
        f'<span style="font-size:1.1rem">{emoji}</span>'
        f'<span>{label}</span>'
        f'</div>'
    )


def _make_card(
    result: dict,
    source_labels: list,
    comp_b: dict,
    alt_num: int = 0,
    auto_extracted: bool = False,
    ing_a: str = "",
    sup_a: str = "",
) -> str:
    verdict = result.get("recommendation", "HUMAN_REVIEW_REQUIRED")
    emoji   = _VERDICT_EMOJI.get(verdict, "❓")
    conf    = result.get("confidence", 0.0)
    alt_tag = f"  *(Alternative #{alt_num})*" if alt_num > 0 else ""

    lines = []
    if auto_extracted:
        lines += [
            f"> 📄 **Ingredient identity auto-extracted from documents:** "
            f"`{ing_a}` / `{sup_a}`  \n"
            f"> *Review the fields above and re-evaluate if the extraction is incorrect.*",
            "",
        ]

    lines += [
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

    options = result.get("decision_options", [])
    if options:
        lines += ["", "---", "### 🗂 Decision Options"]
        option_emojis = {
            "TRANSFER_ORDER": "🔄", "SPLIT_TO_PO": "↔️",
            "SPLIT_PO": "⚡", "FULL_REPLACE": "🔁", "APPROVE": "✅",
        }
        for opt in options:
            otype = opt.get("type", "")
            oemoji = option_emojis.get(otype, "•")
            oconf = opt.get("confidence", 0)
            lines += [
                "",
                f"**{oemoji} {opt.get('label', otype)}** — confidence {oconf:.0%}",
                f"  {opt.get('detail', '')}",
            ]
            if opt.get("risk"):
                lines.append(f"  ⚠ Risk: {opt['risk']}")

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


def download_session_log():
    """Download the current session log file."""
    if not session_logger:
        return None
    
    log_path = session_logger.session_file_path
    if not log_path.exists():
        return None
    
    return str(log_path)


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
        from requests.exceptions import Timeout, ConnectionError, HTTPError, RequestException
        start = perf_counter()
        
        # Retry logic for transient failures
        max_retries = 2
        last_error = None
        
        for attempt in range(max_retries + 1):
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
                    break
                    
                elif any(url_lower.endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.webp', '.gif']):
                    # Image - download for Vision API
                    status_html += f'<li>🖼️ Image detected: {url[:50]}... (downloading)</li>'
                    resp = requests.get(url, timeout=15, headers={"User-Agent": "Agnes/2.0"})
                    resp.raise_for_status()
                    duration = (perf_counter() - start) * 1000
                    status_html += f'<li style="color:#16a34a">✓ Downloaded image ({len(resp.content)//1024}KB, {duration:.0f}ms)</li>'
                    results.append({"url": url, "type": "image", "data": resp.content, "success": True})
                    session_logger.log_scraper(url, True, "image_download", duration, size_kb=len(resp.content)//1024)
                    break
                    
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
                    break
                    
            except Timeout as e:
                last_error = f"Timeout after 15s"
                if attempt < max_retries:
                    status_html += f'<li style="color:#f59e0b">⚠ Timeout, retrying ({attempt + 1}/{max_retries})...</li>'
                    continue
                    
            except ConnectionError as e:
                last_error = "Connection failed"
                if attempt < max_retries:
                    status_html += f'<li style="color:#f59e0b">⚠ Connection error, retrying ({attempt + 1}/{max_retries})...</li>'
                    continue
                    
            except HTTPError as e:
                last_error = f"HTTP {e.response.status_code}"
                if e.response.status_code in (429, 502, 503, 504) and attempt < max_retries:
                    status_html += f'<li style="color:#f59e0b">⚠ HTTP {e.response.status_code}, retrying ({attempt + 1}/{max_retries})...</li>'
                    continue
                    
            except RequestException as e:
                last_error = str(e)[:60]
                if attempt < max_retries:
                    status_html += f'<li style="color:#f59e0b">⚠ Network error, retrying ({attempt + 1}/{max_retries})...</li>'
                    continue
                    
            except Exception as e:
                last_error = str(e)[:60]
                break
        
        # If all retries failed
        if last_error:
            duration = (perf_counter() - start) * 1000
            status_html += f'<li style="color:#dc2626">✗ Failed: {last_error}</li>'
            results.append({"url": url, "type": "error", "error": last_error, "success": False})
            session_logger.log_scraper(url, False, "fetch", duration, error=last_error)
    
    status_html += '</ul></div>'
    
    return status_html, results


_DB_PATH = Path(__file__).parent / "DB" / "db.sqlite"


def _get_companies() -> list[tuple[int, str]]:
    """Fetch all companies as (Id, Name) tuples for dropdown."""
    conn = sqlite3.connect(_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT Id, Name FROM Company ORDER BY Name")
    companies = [(row[0], row[1]) for row in cursor.fetchall()]
    conn.close()
    return companies


def _get_first_company_id() -> int:
    """Get the ID of the first company in alphabetical order."""
    conn = sqlite3.connect(_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT Id FROM Company ORDER BY Name LIMIT 1")
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else 0


def _parse_ingredient_from_sku(sku: str) -> str:
    """Extract ingredient name from raw material SKU.
    Format: RM-{CompanyId}-{ingredient-name}-{8hexhash}
    Returns: ingredient-name (e.g., 'cellulose' from 'RM-C1-cellulose-594d4ce6')
    """
    if not sku or not sku.startswith("RM-"):
        return sku
    parts = sku.split("-")
    # RM-{CompanyId}-{ingredient...}-{hash}
    if len(parts) >= 4:
        # Join middle parts (ingredient name may contain hyphens)
        return "-".join(parts[2:-1])
    return sku


def _load_company_products(company_id: int, product_type: str, filter_text: str = "") -> "pd.DataFrame":
    """Load products for a specific company and type.
    
    For finished-good: returns SKU and Raw_Materials (comma-separated list of raw material SKUs)
    For raw-material: returns Stripped_SKU and In_Stock (count of SKUs with same ingredient name)
    """
    import pandas as pd
    conn = sqlite3.connect(_DB_PATH)
    
    if product_type == "finished-good":
        # List all raw materials for each finished good
        query = """
            SELECT p.SKU, GROUP_CONCAT(DISTINCT rm.SKU) AS Raw_Materials
            FROM Product p
            LEFT JOIN BOM b ON b.ProducedProductId = p.Id
            LEFT JOIN BOM_Component bc ON bc.BOMId = b.Id
            LEFT JOIN Product rm ON rm.Id = bc.ConsumedProductId
            WHERE p.CompanyId = ? AND p.Type = 'finished-good'
            GROUP BY p.Id
            ORDER BY p.SKU
        """
        df = pd.read_sql_query(query, conn, params=[company_id])
    else:  # raw-material
        # Get raw materials and their usage in finished products
        # In_Stock = count of raw materials with the same ingredient name for this company
        # Used_In_Products = list of finished products + "Direct sold"
        query = """
            SELECT
                p.SKU AS Raw_Material_SKU,
                0 AS In_Stock, -- Will be calculated in pandas
                COALESCE(GROUP_CONCAT(DISTINCT fg.SKU), '') ||
                    CASE WHEN COUNT(DISTINCT fg.Id) > 0 THEN ', Direct sold' ELSE 'Direct sold' END
                    AS Used_In_Products
            FROM Product p
            LEFT JOIN (
                SELECT DISTINCT bc2.ConsumedProductId, fg2.Id, fg2.SKU
                FROM BOM_Component bc2
                JOIN BOM b2 ON b2.Id = bc2.BOMId
                JOIN Product fg2 ON fg2.Id = b2.ProducedProductId AND fg2.Type = 'finished-good'
            ) fg ON fg.ConsumedProductId = p.Id
            WHERE p.CompanyId = ? AND p.Type = 'raw-material'
            GROUP BY p.Id
            ORDER BY p.SKU
        """
        df = pd.read_sql_query(query, conn, params=[company_id])

        # Calculate In_Stock based on matching ingredient names
        base_names = df['Raw_Material_SKU'].apply(_parse_ingredient_from_sku)
        df['In_Stock'] = base_names.map(base_names.value_counts())

    conn.close()    
    if filter_text and filter_text.strip():
        q = filter_text.strip().lower()
        if product_type == "finished-good":
            mask = df["SKU"].str.lower().str.contains(q, na=False)
        else:
            mask = df["Raw_Material_SKU"].str.lower().str.contains(q, na=False)
        df = df[mask]
    
    return df


def _load_supplier_catalog(filter_text: str = "") -> "pd.DataFrame":
    import pandas as pd
    conn = sqlite3.connect(_DB_PATH)
    df = pd.read_sql_query(
        """
        SELECT s.Name AS Supplier, p.SKU AS Product, p.Type
        FROM Supplier_Product sp
        JOIN Supplier s ON sp.SupplierId = s.Id
        JOIN Product p ON sp.ProductId = p.Id
        ORDER BY s.Name, p.SKU
        """,
        conn,
    )
    conn.close()
    if filter_text and filter_text.strip():
        q = filter_text.strip().lower()
        mask = df["Supplier"].str.lower().str.contains(q, na=False) | df["Product"].str.lower().str.contains(q, na=False)
        df = df[mask]
    return df


def _parse_email(text: str) -> tuple[str, str, str]:
    """Extract ingredient name, supplier, and notes from a pasted email/alert using Gemini."""
    if not text or not text.strip():
        return "", "", '<div style="color:#f59e0b;font-size:0.85rem;padding:4px 0">⚠ Paste email text first.</div>'
    prompt = (
        "You are a supply chain analyst. Extract the ingredient name and supplier "
        "experiencing a shortage or supply issue from the following email or alert. "
        "Return ONLY valid JSON with keys: 'ingredient' (ingredient name), "
        "'supplier' (supplier/company name), 'notes' (one-line summary of the issue). "
        "If a field cannot be determined, return an empty string for that field.\n\n"
        f"Email:\n{text[:3000]}"
    )
    try:
        response = client.models.generate_content(
            model=_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,
            ),
        )
        data = json.loads(response.text.strip())
        ingredient = data.get("ingredient", "")
        supplier = data.get("supplier", "")
        notes_text = data.get("notes", "")
        if ingredient:
            badge = (
                f'<div style="color:#16a34a;font-size:0.85rem;padding:4px 0;border-left:3px solid #16a34a;padding-left:8px">'
                f'✓ Parsed — <strong>{ingredient}</strong> from <strong>{supplier or "unknown supplier"}</strong>'
                f'{(" · " + notes_text) if notes_text else ""}</div>'
            )
        else:
            badge = '<div style="color:#f59e0b;font-size:0.85rem;padding:4px 0">⚠ Could not extract ingredient — try more specific text.</div>'
        return ingredient, supplier, badge
    except Exception as exc:
        return "", "", f'<div style="color:#dc2626;font-size:0.85rem;padding:4px 0">✗ Parse error: {exc}</div>'


def decide_po_vs_to(
    material_name: str,
    needed_qty: float,
    po_data: dict,   # {cost, lead_time_days}
    to_data: dict,   # {branch_name, current_stock, safety_limit, freight_cost, lead_time_days}
    factory_buffer_days: float = 0,
    unit: str = "units",
) -> dict:
    """
    Step 1 — Feasibility gate (Python, no LLM cost):
      available_to_transfer = current_stock - safety_limit
      if available < needed → TO is impossible, must PO.

    Step 2 — Build structured scenario dict for the LLM prompt.
    Step 3 — Decision hint (applied as LLM guidance, not hard override):
      A) TO cost < PO cost AND TO lead_time ≤ PO lead_time  → hint TRANSFER_ORDER
      B) TO cheaper + factory has buffer                     → hint TRANSFER_ORDER
      C) Emergency (buffer=0) + PO faster                   → hint FULL_REPLACE (PO)
      D) Freight > PO cost                                  → hint FULL_REPLACE

    Returns a dict with:
      - feasible_to (bool)
      - available_to_transfer (float)
      - scenario_block (str)  — appended verbatim to the LLM user_msg
      - hint (str)            — recommended verdict hint fed to Agnes
    """
    available = to_data.get("current_stock", 0) - to_data.get("safety_limit", 0)
    feasible_to = available >= needed_qty

    po_cost = po_data.get("cost", 0)
    po_lt   = po_data.get("lead_time_days", 999)
    to_freight = to_data.get("freight_cost", 0)
    to_lt   = to_data.get("lead_time_days", 999)
    branch  = to_data.get("branch_name", "Internal Branch")

    # Determine hint
    if not feasible_to:
        hint = "FULL_REPLACE"
        reason = f"TO is impossible: {branch} has only {available:.1f} {unit} above safety limit, but {needed_qty} {unit} needed."
    elif to_freight > po_cost:
        # Scenario D
        hint = "FULL_REPLACE"
        reason = f"Internal freight (${to_freight:,.0f}) exceeds full PO cost (${po_cost:,.0f}) — external supplier is cheaper."
    elif factory_buffer_days == 0 and po_lt < to_lt:
        # Scenario C — emergency
        hint = "FULL_REPLACE"
        reason = f"Emergency: factory has 0 buffer days and PO delivers in {po_lt}d vs TO in {to_lt}d — speed wins."
    elif to_freight < po_cost and to_lt <= po_lt:
        # Scenario A — no-brainer TO
        hint = "TRANSFER_ORDER"
        reason = f"TO is cheaper (${to_freight:,.0f} vs ${po_cost:,.0f}) AND faster ({to_lt}d vs {po_lt}d) — clear winner."
    elif to_freight < po_cost:
        # Scenario B — cheaper but slower, factory has buffer
        hint = "TRANSFER_ORDER"
        reason = f"TO saves ${po_cost - to_freight:,.0f} and factory has {factory_buffer_days:.0f} buffer days to absorb the extra {to_lt - po_lt}d."
    elif available >= needed_qty:
        hint = "TRANSFER_ORDER"
        reason = f"{branch} has sufficient excess stock ({available:.1f} {unit}) — TO avoids external spend."
    else:
        hint = "SPLIT_TO_PO"
        reason = f"Branch covers {available:.1f} {unit}; PO the remaining {needed_qty - available:.1f} {unit}."

    scenario_block = f"""
## Supply Scenario — PO vs Transfer Order Analysis
- Material needed        : {needed_qty} {unit} of {material_name}
- Factory buffer stock   : {factory_buffer_days} days remaining

### Option 1 — Purchase Order (PO) from external supplier
- Total landed cost      : ${po_cost:,.2f}
- Lead time              : {po_lt} days

### Option 2 — Transfer Order (TO) from {branch}
- Branch current stock   : {to_data.get('current_stock', 0)} {unit}
- Safety stock limit     : {to_data.get('safety_limit', 0)} {unit}
- Available to transfer  : {available:.1f} {unit}  {"✓ feasible" if feasible_to else "✗ INSUFFICIENT — TO not viable"}
- Internal freight cost  : ${to_freight:,.2f}  (material already owned — no purchase cost)
- Lead time              : {to_lt} days

### Decision Hint from Algorithm
Recommended: {hint}
Reason: {reason}

Evaluate the above scenarios. Apply the PO vs TO decision rules from your system prompt.
Populate decision_options[] with ranked choices. Set recommendation to the best option.
"""
    return {
        "feasible_to": feasible_to,
        "available_to_transfer": available,
        "scenario_block": scenario_block,
        "hint": hint,
    }


def _find_alternative(ing_a: str, sup_a: str) -> tuple[str, str]:
    """Ask the LLM to suggest the best alternative supplier for ing_a."""
    prompt = (
        f"You are a dietary supplement supply chain expert. "
        f"Given ingredient '{ing_a}' currently sourced from '{sup_a}', "
        f"suggest the single best alternative supplier available in the market. "
        f"Return ONLY valid JSON with keys 'ingredient_b' and 'supplier_b'. "
        f"Example: {{\"ingredient_b\": \"vitamin-d3-cholecalciferol\", \"supplier_b\": \"PureBulk\"}}"
    )
    try:
        response = client.models.generate_content(
            model=_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.3,
            ),
        )
        data = json.loads(response.text.strip())
        return data.get("ingredient_b", ing_a), data.get("supplier_b", "Alternative Supplier")
    except Exception:
        return ing_a, "Alternative Supplier"


def _safe_float(val, default=None):
    try:
        return float(str(val).replace(",", "").strip()) if val and str(val).strip() else default
    except (ValueError, TypeError):
        return default


def submit_handler(
    ing_a, sup_a, ing_b, sup_b,
    needed_qty_str, supplier_qty_str, unit_str,
    po_cost_str, po_lead_str,
    branch_name, branch_stock_str, branch_safety_str, to_freight_str, to_lead_str,
    factory_buffer_str,
    notes, coa_image, audio_file, video_file, pdf_file,
    state, progress=gr.Progress(),
):
    # Log evaluation start
    session_logger.info("Evaluation started", extra={
        "ingredient_a": ing_a,
        "supplier_a": sup_a,
        "has_notes": bool(notes and notes.strip()),
        "has_coa_image": coa_image is not None,
        "has_audio": audio_file is not None,
        "has_video": video_file is not None,
        "has_pdf": pdf_file is not None,
    })

    # Progress: Document ingestion — happens BEFORE validation so docs can fill missing fields
    progress(0.05, desc="Processing uploaded documents...")
    with log_operation(session_logger, "build_parts", "ui"):
        parts, labels = _build_parts(notes, coa_image, audio_file, video_file, pdf_file)
    session_logger.info("Parts assembled", extra={"part_count": len(parts), "labels": labels})

    auto_extracted = False
    comp_b_from_docs = None  # will hold compliance if already extracted during identity pass

    if not ing_a or not ing_a.strip():
        if not parts:
            session_logger.warning("Evaluation rejected - no ingredient name and no documents")
            return (
                "**Please enter an Ingredient A name or upload a supporting document "
                "(image, PDF, audio, video, or paste notes/URLs).**  \n"
                "*Agnes can extract the ingredient automatically from a Certificate of Analysis or supplier email.*",
                "<div style='color:#64748b;font-size:0.9rem;padding:8px 0'>Awaiting evaluation…</div>",
                gr.update(interactive=False), gr.update(interactive=False),
                gr.update(interactive=False), state,
            )
        # Combined call: extract identity AND compliance in one shot (saves an API call)
        progress(0.15, desc="Reading document — extracting ingredient & compliance data…")
        identity, comp_b_from_docs = _extract_identity_and_compliance(parts)
        ing_a = identity.get("ingredient", "").strip() or "Unknown Ingredient"
        if not (sup_a and sup_a.strip()):
            sup_a = identity.get("supplier", "").strip() or "Unknown Supplier"
        auto_extracted = True
        session_logger.info("Identity + compliance auto-extracted from documents", extra={
            "ingredient_a": ing_a, "supplier_a": sup_a,
        })

    progress(0.25, desc="Finding alternative supplier…")

    # Auto-discover alternative if user left Ingredient B blank
    if not (ing_b and ing_b.strip()):
        ing_b, sup_b = _find_alternative(ing_a, sup_a or "Current Supplier")
        session_logger.info("Alternative auto-discovered", extra={"ingredient_b": ing_b, "supplier_b": sup_b})
    else:
        session_logger.info("Using user-provided Ingredient B", extra={"ingredient_b": ing_b, "supplier_b": sup_b})

    # Compliance for Ingredient B — reuse the combined extraction if already done
    progress(0.45, desc="Extracting compliance data…")
    if comp_b_from_docs is not None:
        comp_b = comp_b_from_docs  # already extracted above — skip the extra API call
    else:
        comp_b = _extract_compliance(parts, sup_b, ing_b)
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

    # Build supply scenario block if quantities provided
    supply_scenario_block = None
    needed_qty    = _safe_float(needed_qty_str)
    supplier_qty  = _safe_float(supplier_qty_str)
    po_cost       = _safe_float(po_cost_str)
    po_lead       = _safe_float(po_lead_str)
    branch_stock  = _safe_float(branch_stock_str)
    branch_safety = _safe_float(branch_safety_str, 0)
    to_freight    = _safe_float(to_freight_str)
    to_lead       = _safe_float(to_lead_str)
    factory_buf   = _safe_float(factory_buffer_str, 0)
    unit          = unit_str.strip() if unit_str and unit_str.strip() else "units"

    has_qty_data   = needed_qty is not None and supplier_qty is not None
    has_po_data    = po_cost is not None and po_lead is not None
    has_to_data    = branch_stock is not None and to_freight is not None and to_lead is not None

    if has_qty_data:
        shortfall = needed_qty - (supplier_qty or 0)
        supply_scenario_block = (
            f"\n## Supply Scenario — Partial Supply\n"
            f"- Required quantity    : {needed_qty} {unit}\n"
            f"- Supplier can provide : {supplier_qty} {unit}"
            + (f"  ← PARTIAL — shortfall of {shortfall:.1f} {unit} ({shortfall/needed_qty:.0%})\n" if shortfall > 0 else "\n")
        )
        if shortfall > 0:
            supply_scenario_block += (
                "\nEvaluate BOTH options and populate decision_options[]:\n"
                f"Option A (SPLIT_PO): accept {supplier_qty} {unit} from current supplier + source {shortfall:.1f} {unit} from an alternative external supplier\n"
                f"Option B (FULL_REPLACE): replace entirely with a supplier who can deliver the full {needed_qty} {unit}\n"
            )

    if has_po_data and has_to_data and needed_qty is not None:
        scenario = decide_po_vs_to(
            material_name=ing_a,
            needed_qty=needed_qty,
            po_data={"cost": po_cost, "lead_time_days": po_lead},
            to_data={
                "branch_name": branch_name or "Internal Branch",
                "current_stock": branch_stock,
                "safety_limit": branch_safety,
                "freight_cost": to_freight,
                "lead_time_days": to_lead,
            },
            factory_buffer_days=factory_buf,
            unit=unit,
        )
        supply_scenario_block = (supply_scenario_block or "") + scenario["scenario_block"]
        session_logger.info("PO vs TO analysis", extra={
            "hint": scenario["hint"],
            "feasible_to": scenario["feasible_to"],
            "available_to_transfer": scenario["available_to_transfer"],
        })

    # Evaluate (no auto-store)
    with log_operation(session_logger, "rag_evaluate", "rag"):
        result, docs = _evaluate(
            ing_a, sup_a or "Current Supplier", comp_a,
            ing_b, sup_b or "Proposed Supplier", comp_b,
            supply_scenario_block=supply_scenario_block,
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
    
    card  = _make_card(result, labels, comp_b, auto_extracted=auto_extracted, ing_a=ing_a, sup_a=sup_a)
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

_THEME = gr.themes.Soft(
    primary_hue=gr.themes.colors.blue,
    neutral_hue=gr.themes.colors.slate,
    font=[gr.themes.GoogleFont("Inter"), "ui-sans-serif", "sans-serif"],
).set(
    button_primary_background_fill="#2563eb",
    button_primary_background_fill_hover="#1d4ed8",
    button_primary_text_color="#ffffff",
    body_background_fill="#f8fafc",
    block_background_fill="#ffffff",
    block_border_color="#e2e8f0",
    input_background_fill="#ffffff",
    input_border_color="#e2e8f0",
    input_border_color_focus="#2563eb",
)

_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

:root {
  --c-accent:  #2563eb;
  --c-text:    #1e293b;
  --c-muted:   #64748b;
  --c-border:  #e2e8f0;
  --c-bg:      #f8fafc;
  --c-surface: #ffffff;
  --c-shadow:  0 1px 4px rgba(0,0,0,.06);
}

footer { display: none !important; }
.gradio-container { background: var(--c-bg) !important; }

/* ── Tabs ── */
.tab-nav button { font-weight: 600; font-size: 0.875rem; color: var(--c-muted) !important; }
.tab-nav button.selected { color: var(--c-accent) !important; }

/* ── Section labels ── */
.section-label {
  font-size: 0.7rem !important; font-weight: 700 !important;
  letter-spacing: 0.07em !important; text-transform: uppercase !important;
  color: var(--c-muted) !important; margin: 14px 0 6px !important;
}

/* ── Inner sub-tab pills ── */
.inner-tabs .tabs > .tab-nav {
  background: var(--c-bg) !important; border-radius: 8px !important;
  border: 1px solid var(--c-border) !important; padding: 3px !important; gap: 2px !important;
}
.inner-tabs button {
  border-radius: 6px !important; padding: 5px 14px !important;
  font-size: 0.8rem !important; font-weight: 600 !important;
  color: var(--c-muted) !important; border: none !important; background: transparent !important;
}
.inner-tabs button.selected {
  background: var(--c-surface) !important; color: var(--c-accent) !important;
  box-shadow: var(--c-shadow) !important;
}

/* ── Evaluate button ── */
.eval-btn button {
  background: #2563eb !important; border-radius: 8px !important;
  font-weight: 700 !important; font-size: 0.95rem !important;
  height: 48px !important; transition: background .15s, transform .1s !important;
}
.eval-btn button:hover { background: #1d4ed8 !important; transform: translateY(-1px) !important; }
.eval-btn button:active { transform: translateY(0) !important; }

/* ── Recommendation card ── */
.recommendation-card {
  background: var(--c-surface) !important; border: 1px solid var(--c-border) !important;
  border-radius: 10px !important; padding: 18px !important;
  box-shadow: var(--c-shadow) !important; min-height: 100px !important;
}

/* ── Action buttons ── */
.action-row button { border-radius: 7px !important; font-weight: 600 !important; font-size: 0.85rem !important; }

/* ── Dataframe tables ── */
.gradio-dataframe table { font-size: 0.82rem !important; }
.gradio-dataframe th {
  background: var(--c-bg) !important; color: var(--c-text) !important;
  font-weight: 700 !important; font-size: 0.75rem !important;
  letter-spacing: 0.04em !important; text-transform: uppercase !important;
  border-bottom: 2px solid var(--c-border) !important; padding: 10px 12px !important;
}
.gradio-dataframe td { padding: 8px 12px !important; color: var(--c-muted) !important; }
.gradio-dataframe tr:hover td { background: #f1f5f9 !important; }

/* ── Parse badge ── */
.parse-status { display: flex; align-items: center; min-height: 34px; }
"""

with gr.Blocks(title="Agnes 2.0 — Supply Chain Intelligence") as demo:

    gr.HTML(
        '<div style="display:flex;align-items:center;gap:12px;'
        'padding:16px 4px 14px;border-bottom:1px solid #e2e8f0;margin-bottom:8px">'
        '<div style="width:36px;height:36px;background:#eff6ff;border-radius:9px;'
        'display:flex;align-items:center;justify-content:center;font-size:1.2rem;flex-shrink:0">🧬</div>'
        '<div>'
        '<h1 style="margin:0;font-size:1.25rem;font-weight:700;color:#1e293b">Agnes 2.0</h1>'
        '<p style="margin:1px 0 0;color:#64748b;font-size:0.8rem">'
        'Supply Chain Intelligence &nbsp;·&nbsp; RAG-augmented &nbsp;·&nbsp; Gemini Flash</p>'
        '</div>'
        '<div style="margin-left:auto;display:flex;gap:6px">'
        '<span style="background:#eff6ff;color:#2563eb;border:1px solid #bfdbfe;'
        'font-size:0.7rem;font-weight:600;padding:3px 10px;border-radius:20px;'
        'letter-spacing:0.05em">MULTIMODAL</span>'
        '<span style="background:#f0fdf4;color:#16a34a;border:1px solid #bbf7d0;'
        'font-size:0.7rem;font-weight:600;padding:3px 10px;border-radius:20px;'
        'letter-spacing:0.05em">ENTERPRISE</span>'
        '</div>'
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

                    # ── Task 1: Email paste / parse ───────────────────────
                    gr.HTML('<p class="section-label">Shortage Alert or Email</p>')
                    email_text = gr.Textbox(
                        label="Paste email / shortage alert",
                        placeholder=(
                            "Paste the full email, shortage alert, or supplier notice here…\n\n"
                            "Agnes will extract the ingredient and supplier automatically."
                        ),
                        lines=4,
                    )
                    with gr.Row():
                        parse_btn = gr.Button("Parse Email", variant="primary", size="sm")
                        parse_badge = gr.HTML(
                            '<div class="parse-status" style="color:#94a3b8;font-size:0.82rem">'
                            'Paste email text and click Parse.</div>'
                        )

                    # ── Task 2: Ingredient A (auto-filled or manual) ──────
                    with gr.Accordion("Ingredient Details — review or enter manually", open=True):
                        gr.HTML('<p class="section-label">Ingredient A — Current baseline</p>')
                        with gr.Row():
                            ing_a = gr.Textbox(label="Ingredient name",
                                               placeholder="vitamin-d3-cholecalciferol")
                            sup_a = gr.Textbox(label="Current supplier",
                                               placeholder="Prinova USA")

                        gr.HTML(
                            '<p class="section-label" style="margin-top:16px">Ingredient B — Proposed substitute'
                            '<span style="font-weight:400;text-transform:none;letter-spacing:0;'
                            'font-size:0.75rem;color:#94a3b8;margin-left:6px">'
                            '(optional — Agnes finds one automatically if left blank)</span></p>'
                        )
                        with gr.Row():
                            ing_b = gr.Textbox(label="Ingredient B name (optional)",
                                               placeholder="Leave blank for auto-discovery")
                            sup_b = gr.Textbox(label="Proposed supplier (optional)",
                                               placeholder="Leave blank for auto-discovery")

                    # ── Partial Supply + PO vs TO inputs ─────────────────
                    with gr.Accordion("Supply Scenario — PO vs Transfer Order (optional)", open=False):
                        gr.HTML(
                            '<p style="font-size:0.8rem;color:#64748b;margin:0 0 12px">'
                            'Provide quantity and cost data for Agnes to recommend '
                            '<strong>Split PO</strong>, <strong>Full Replace</strong>, '
                            '<strong>Transfer Order</strong>, or <strong>Split TO+PO</strong>.</p>'
                        )
                        gr.HTML('<p class="section-label">Quantity</p>')
                        with gr.Row():
                            needed_qty_input    = gr.Textbox(label="Required quantity", placeholder="500")
                            supplier_qty_input  = gr.Textbox(label="Supplier can provide", placeholder="250")
                            unit_input          = gr.Textbox(label="Unit", placeholder="kg", value="kg")

                        gr.HTML('<p class="section-label" style="margin-top:14px">External Purchase Order (PO)</p>')
                        with gr.Row():
                            po_cost_input  = gr.Textbox(label="PO total landed cost ($)", placeholder="5000")
                            po_lead_input  = gr.Textbox(label="PO lead time (days)", placeholder="14")

                        gr.HTML('<p class="section-label" style="margin-top:14px">Internal Transfer Order (TO) — optional</p>')
                        with gr.Row():
                            branch_name_input   = gr.Textbox(label="Branch / warehouse name", placeholder="East Coast DC")
                            branch_stock_input  = gr.Textbox(label="Branch current stock", placeholder="1000")
                            branch_safety_input = gr.Textbox(label="Safety stock limit", placeholder="200")
                        with gr.Row():
                            to_freight_input    = gr.Textbox(label="Internal freight cost ($)", placeholder="800")
                            to_lead_input       = gr.Textbox(label="TO lead time (days)", placeholder="3")
                            factory_buffer_input = gr.Textbox(label="Factory buffer (days)", placeholder="0")

                    # ── Task 3: Sleek supporting evidence accordion ────────
                    with gr.Accordion("Supporting Evidence (all optional)", open=False):
                        with gr.Tabs(elem_classes=["inner-tabs"]):
                            with gr.TabItem("📝 Notes & URLs"):
                                notes = gr.Textbox(
                                    label="Notes / URLs",
                                    placeholder=(
                                        "Free-form notes, or paste URLs:\n"
                                        "https://supplier.com/product-page\n"
                                        "https://example.com/coa.pdf"
                                    ),
                                    lines=3,
                                )
                                url_status = gr.HTML(
                                    '<div style="color:#94a3b8;font-size:0.85rem;padding:4px 0">'
                                    'URLs detected: 0</div>',
                                )
                                with gr.Row():
                                    detect_btn = gr.Button("🔍 Detect URLs", size="sm", variant="secondary")
                                    fetch_btn  = gr.Button("📥 Fetch Details", size="sm", variant="primary", interactive=False)
                                fetch_status = gr.HTML(visible=False)

                            with gr.TabItem("📄 Documents"):
                                with gr.Row():
                                    coa_image = gr.Image(label="CoA Image (PNG/JPG)", type="filepath")
                                    pdf_file  = gr.File(label="PDF Document", file_types=[".pdf"])

                            with gr.TabItem("🎙 Media"):
                                with gr.Row():
                                    audio_file = gr.Audio(label="Audio Note (MP3/WAV)", type="filepath")
                                    video_file = gr.Video(label="Video (facility/demo)")

                        detected_urls_state = gr.State([])

                    evaluate_btn = gr.Button("Evaluate", variant="primary", size="lg", elem_classes=["eval-btn"])

                # ── Right: outputs ────────────────────────────────────────
                with gr.Column(scale=1):
                    gr.HTML('<p class="section-label">Agnes Recommendation</p>')
                    verdict_badge = gr.HTML(
                        '<div style="color:#94a3b8;font-size:0.85rem;padding:8px 0;'
                        'font-weight:500">Awaiting evaluation…</div>'
                    )
                    result_md = gr.Markdown(
                        "*Enter an ingredient name or upload a document, then click Evaluate.*",
                        elem_classes=["recommendation-card"],
                    )
                    with gr.Row(elem_classes=["action-row"]):
                        apply_btn  = gr.Button("Apply & Save",     variant="primary",   interactive=False)
                        alt_btn    = gr.Button("Show Alternative", variant="secondary",  interactive=False)
                        reject_btn = gr.Button("Reject All",       variant="stop",       interactive=False)
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

        # ══════════════════════════════════════════════════════════════════
        # TAB 5 — Database Explorer
        # ══════════════════════════════════════════════════════════════════
        with gr.TabItem("🗄️  Database Explorer"):
            gr.Markdown(
                "Live read-only view of the supply chain database.  \n"
                "Select a company and product type, then click **Refresh** to load."
            )

            with gr.Tabs():
                # ── Sub-tab 1: Company Catalog ─────────────────────────────
                with gr.TabItem("🏭 Company Catalog"):
                    gr.Markdown(
                        "View products by company. Select finished goods to see material counts, or raw materials to see where they're used."
                    )
                    # Company dropdown: [(Id, Name), ...] - first company as default
                    _company_list = _get_companies()  # [(1, "Company A"), (2, "Company B"), ...]
                    _first_company_id = _company_list[0][0] if _company_list else 0
                    _company_names = [c[1] for c in _company_list]
                    _company_name_to_id = {c[1]: c[0] for c in _company_list}
                    _company_id_to_name = {c[0]: c[1] for c in _company_list}

                    with gr.Row():
                        company_dropdown = gr.Dropdown(
                            choices=_company_names,
                            value=_company_names[0] if _company_names else None,
                            label="Select Company",
                            scale=2,
                        )
                        type_dropdown = gr.Dropdown(
                            choices=["raw-material", "finished-good"],
                            value="raw-material",
                            label="Product Type",
                            scale=1,
                        )
                        company_filter = gr.Textbox(
                            label="Filter by SKU (optional)",
                            placeholder="e.g. vitamin-d3",
                            scale=2,
                        )
                        company_refresh_btn = gr.Button("🔄 Refresh", variant="secondary", size="sm", scale=1)
                    
                    company_table = gr.Dataframe(
                        headers=["SKU", "Materials_Count"],  # Default headers, will be updated dynamically
                        value=_load_company_products(company_id=_first_company_id, product_type="raw-material"),
                        interactive=False,
                        wrap=True,
                        label="Products",
                    )
                    
                    company_legend = gr.HTML(
                        '<div style="margin-top:12px;padding:12px;background:#f8fafc;border-radius:6px;font-size:0.8rem;color:#475569;">'
                        '<strong>Abbreviations:</strong> '
                        '<span title="Stock Keeping Unit - unique product identifier">SKU</span> = Stock Keeping Unit; '
                        '<span title="Comma-separated list of raw material SKUs used in this finished good (only shown for finished goods)">Raw_Materials</span> = List of raw materials used; '
                        '<span title="Full raw material SKU (e.g., RM-C1-cellulose-594d4ce6)">Raw_Material_SKU</span> = Raw material identifier; '
                        '<span title="Number of finished products that use this raw material">In_Stock</span> = Usage count; '
                        '<span title="List of finished product SKUs that use this raw material">Used_In_Products</span> = Products using this material'
                        '</div>'
                    )

                # ── Sub-tab 2: Supplier Catalog ────────────────────────────
                with gr.TabItem("🤝 Supplier Catalog"):
                    gr.Markdown(
                        "Suppliers and the raw-material products they can supply."
                    )
                    with gr.Row():
                        supplier_filter = gr.Textbox(
                            label="Filter by supplier or product",
                            placeholder="e.g. ADM or soy-lecithin",
                            scale=4,
                        )
                        supplier_refresh_btn = gr.Button("🔄 Refresh", variant="secondary", size="sm", scale=1)
                    supplier_table = gr.Dataframe(
                        value=_load_supplier_catalog(),
                        interactive=False,
                        wrap=True,
                        label="Supplier → Products",
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
    
    # Email parse handler
    parse_btn.click(
        fn=_parse_email,
        inputs=[email_text],
        outputs=[ing_a, sup_a, parse_badge],
    )

    evaluate_btn.click(
        fn=submit_handler,
        inputs=[
            ing_a, sup_a, ing_b, sup_b,
            needed_qty_input, supplier_qty_input, unit_input,
            po_cost_input, po_lead_input,
            branch_name_input, branch_stock_input, branch_safety_input,
            to_freight_input, to_lead_input, factory_buffer_input,
            notes, coa_image, audio_file, video_file, pdf_file, eval_state,
        ],
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
    
    # Session logs download handler
    download_logs_btn.click(
        fn=download_session_log,
        inputs=[],
        outputs=[gr.File(), gr.Textbox(visible=False)],
    )

    # Database Explorer handlers
    def _on_company_refresh(company_name: str, product_type: str, filter_text: str):
        company_id = _company_name_to_id.get(company_name, _first_company_id)
        df = _load_company_products(company_id=company_id, product_type=product_type, filter_text=filter_text)
        # Update column headers based on product type
        if product_type == "finished-good":
            headers = ["SKU", "Raw_Materials"]
        else:
            headers = ["Raw_Material_SKU", "In_Stock", "Used_In_Products"]
        return gr.Dataframe(value=df, headers=headers)

    company_dropdown.change(fn=_on_company_refresh, inputs=[company_dropdown, type_dropdown, company_filter], outputs=[company_table])
    type_dropdown.change(fn=_on_company_refresh, inputs=[company_dropdown, type_dropdown, company_filter], outputs=[company_table])
    company_filter.change(fn=_on_company_refresh, inputs=[company_dropdown, type_dropdown, company_filter], outputs=[company_table])
    company_refresh_btn.click(fn=_on_company_refresh, inputs=[company_dropdown, type_dropdown, company_filter], outputs=[company_table])
    supplier_filter.change(fn=_load_supplier_catalog, inputs=[supplier_filter], outputs=[supplier_table])
    supplier_refresh_btn.click(fn=_load_supplier_catalog, inputs=[supplier_filter], outputs=[supplier_table])


# ─────────────────────────────────────────────────────────────────────────────
# Launch
# ─────────────────────────────────────────────────────────────────────────────

def _cleanup_on_exit():
    """Cleanup session logger when app shuts down."""
    if session_logger:
        session_logger.close()
        print("Session logger closed")

if __name__ == "__main__":
    atexit.register(_cleanup_on_exit)
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        show_error=True,
        theme=_THEME,
        css=_CSS,
    )
