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


def submit_handler(
    ing_a, sup_a, ing_b, sup_b,
    notes, coa_image, audio_file, video_file, pdf_file,
    state,
):
    if not ing_a.strip() or not ing_b.strip():
        return (
            "**Please enter at least Ingredient A and Ingredient B names.**",
            gr.update(interactive=False), gr.update(interactive=False),
            gr.update(interactive=False), state,
        )

    # Assemble multimodal parts
    parts, labels = _build_parts(notes, coa_image, audio_file, video_file, pdf_file)

    # Extract compliance data for ingredient B from all uploaded documents
    comp_b = _extract_compliance(parts, sup_b or "Unknown Supplier", ing_b)
    comp_b.setdefault("organic_certified", False)

    # Ingredient A: use a reasonable pharmaceutical baseline
    comp_a = {
        "organic_certified": False, "fda_registered": True, "non_gmo": True,
        "grade": "pharmaceutical", "lead_time_days": 14,
        "certifications": ["USP", "GMP", "Halal", "Kosher"],
        "notes": "Baseline — standard pharmaceutical-grade reference.",
    }

    # Evaluate (no auto-store)
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

    card = _make_card(result, labels, comp_b)
    return (
        card,
        gr.update(interactive=True),
        gr.update(interactive=True),
        gr.update(interactive=True),
        new_state,
    )


def apply_handler(state):
    if not state:
        return "No evaluation to apply.", state, _load_history()
    r = state["result"]
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
    verdict = r.get("recommendation", "")
    return (
        f"**Decision saved** — `{verdict}` stored in KB/decisions.json.",
        None,
        _load_history(),
    )


def alternative_handler(state):
    if not state:
        return "Submit an evaluation first.", state
    if state["alt_count"] >= 3:
        return "**No more alternatives** — maximum 3 alternatives reached. Please apply or reject.", state

    alt_num = state["alt_count"] + 1
    last_verdict = state.get("last_verdict")

    result, docs = _evaluate(
        state["ing_a"], state["sup_a"], state["comp_a"],
        state["ing_b"], state["sup_b"], state["comp_b"],
        temperature=0.4 + alt_num * 0.1,
        exclude_verdict=last_verdict,
    )

    new_state = {**state, "result": result, "docs": docs,
                 "alt_count": alt_num, "last_verdict": result.get("recommendation")}
    card = _make_card(result, state["labels"], state["comp_b"], alt_num=alt_num)
    return card, new_state


def reject_handler(state):
    if not state:
        return "No evaluation to reject.", state, _load_history()
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
# Gradio UI
# ─────────────────────────────────────────────────────────────────────────────

_CSS = """
.recommendation-card { font-size: 0.95rem; line-height: 1.6; }
.status-ok  { color: #16a34a; font-weight: bold; }
.status-err { color: #dc2626; font-weight: bold; }
"""

with gr.Blocks(
    title="Agnes — Multimodal Compliance Evaluator",
) as demo:

    gr.Markdown(
        "# Agnes 2.0 — Multimodal Compliance Evaluator\n"
        "Enter ingredient details, attach any combination of **image · audio · video · PDF · URL**, "
        "then click **Evaluate**. Agnes extracts compliance data from all inputs and "
        "recommends whether the substitution is safe. Confirm or request alternatives before saving."
    )

    eval_state = gr.State(None)

    with gr.Row():
        # ── Left column: inputs ───────────────────────────────────────────
        with gr.Column(scale=1):
            gr.Markdown("### Ingredient A — Current (baseline)")
            ing_a = gr.Textbox(label="Ingredient A name", placeholder="vitamin-d3-cholecalciferol")
            sup_a = gr.Textbox(label="Current supplier",  placeholder="Prinova USA")

            gr.Markdown("### Ingredient B — Proposed substitute")
            ing_b = gr.Textbox(label="Ingredient B name", placeholder="vitamin-d3-cholecalciferol")
            sup_b = gr.Textbox(label="Proposed supplier", placeholder="PureBulk")

            gr.Markdown("### Supporting Evidence *(all optional)*")
            notes = gr.Textbox(
                label="Notes / URLs",
                placeholder=(
                    "Free-form notes, or paste one or more URLs:\n"
                    "https://supplier.com/product-page\n"
                    "https://cdn.example.com/coa.pdf\n"
                    "https://cdn.example.com/coa-image.png"
                ),
                lines=4,
            )
            coa_image  = gr.Image(label="CoA Image (PNG/JPG)",     type="filepath")
            audio_file = gr.Audio(label="Audio Note (MP3/WAV)",    type="filepath")
            video_file = gr.Video(label="Video (facility / demo)")
            pdf_file   = gr.File(label="PDF Document",             file_types=[".pdf"])

            evaluate_btn = gr.Button("Evaluate", variant="primary", size="lg")

        # ── Right column: outputs ─────────────────────────────────────────
        with gr.Column(scale=1):
            gr.Markdown("### Agnes Recommendation")
            result_md = gr.Markdown(
                "*Submit an evaluation to see the recommendation here.*",
                elem_classes=["recommendation-card"],
            )

            with gr.Row():
                apply_btn = gr.Button("Apply & Save",     variant="primary",   interactive=False)
                alt_btn   = gr.Button("Show Alternative", variant="secondary",  interactive=False)
                reject_btn= gr.Button("Reject All",       variant="stop",       interactive=False)

            status_md = gr.Markdown("")

    with gr.Accordion("Decision History (last 10)", open=False):
        history_table = gr.Dataframe(
            headers=["Ingredient A", "Ingredient B", "Supplier B", "Verdict", "Confidence"],
            value=_load_history(),
            interactive=False,
        )

    # ── Wire up handlers ──────────────────────────────────────────────────
    evaluate_btn.click(
        fn=submit_handler,
        inputs=[ing_a, sup_a, ing_b, sup_b, notes, coa_image, audio_file, video_file, pdf_file, eval_state],
        outputs=[result_md, apply_btn, alt_btn, reject_btn, eval_state],
    )

    apply_btn.click(
        fn=apply_handler,
        inputs=[eval_state],
        outputs=[status_md, eval_state, history_table],
    )

    alt_btn.click(
        fn=alternative_handler,
        inputs=[eval_state],
        outputs=[result_md, eval_state],
    )

    reject_btn.click(
        fn=reject_handler,
        inputs=[eval_state],
        outputs=[status_md, eval_state, history_table],
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
        theme=gr.themes.Soft(primary_hue="blue"),
        css=_CSS,
    )
