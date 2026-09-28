"""Vision extraction — read a scanned invoice into structured JSON.

Uses the per-vendor rules in prompts/extraction_prompt.md as the source of truth,
but asks the model for JSON (not the final PDI text) so the pipeline can VALIDATE
before anything is written — the architecture's "extract -> model -> validate ->
writer" order. On a validation failure the caller retries once with the stronger
"escalate" model before routing to review (see pipeline.py).

The vision SDK (anthropic or google-genai) is imported lazily so this module (and
the offline core) import fine on a machine without the SDK or an API key. The real
API call runs on the server, which supplies the provider's key. The provider is
selected in settings.yaml (``provider: gemini`` -> GEMINI_API_KEY free tier);
the prompt, JSON contract, and downstream gates/review are provider-independent.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image

from . import pdf_prep

log = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"

# JSON output contract appended to the vendor rules. Numbers stay STRINGS so the
# pipeline can parse them as exact Decimals (no float rounding).
_JSON_CONTRACT = """
========================================================================
OUTPUT CONTRACT (override the "output only text" instruction above)
========================================================================
Do NOT output the 0000/1200/1202 text. Instead output ONLY a single JSON object
(no markdown, no commentary) with EXACTLY these keys. Use the per-vendor rules
above to decide which columns are item#, qty, price, and which figure is the net
total. Every numeric value MUST be a JSON string (e.g. "451.61", "-6", "2.41")
to preserve exact digits and leading zeros.

{
  "vendor_name": "<seller / letterhead company name, as printed>",
  "store_name": "<the 'sold to'/'ship to' STORE name, or null if only an address>",
  "store_address": "<delivery/ship-to address, or null>",
  "invoice_date": "<YYYYMMDD>",
  "invoice_ref": "<invoice number exactly as printed>",
  "net_total": "<the Net Total figure, 2 decimals as a string>",
  "tax": "<tax amount as a string, or null if the invoice shows no tax field>",
  "stated_qty_count": "<the invoice's own net qty total, or null>",
  "stated_totes": "<stated totes count, or null>",
  "gross": "<gross sale, or null>",
  "discounts": "<total discount magnitude (positive), or null>",
  "fees": "<extra fees total, or null>",
  "line_items": [
    {
      "item_no": "<item#/UPC exactly as printed>",
      "qty": "<shipped qty; NEGATIVE for returns>",
      "price": "<per-unit price; net price where discounted>",
      "extended": "<printed line total if shown, else null>",
      "is_tote": false,
      "counts_qty": true
    }
  ]
}

Rules for the JSON:
- counts_qty = true for product/return lines; false for discount lines, extra
  charges (fuel/shipping), and the tote lines counted separately.
- is_tote = true only for tote lines.
- Put invoice-wide discounts and non-item charges in line_items too (counts_qty
  false), exactly as the rules above describe, so the lines sum to the net total.
- If the vendor or store cannot be identified from the invoice, still return your
  best-read values; ID resolution and any ambiguity handling happen downstream.
"""


@dataclass
class ExtractionOutput:
    data: dict
    model_used: str
    raw_text: str


def load_rules() -> str:
    """The authoritative per-vendor extraction rules, with any chat-added DRAFT
    vendor blocks stripped out — a DRAFT rule must never affect a real batch until
    an owner flips it LIVE (see rules_mgmt.strip_draft_blocks)."""
    from . import rules_mgmt  # import-light; no chat dependency
    raw = (_PROMPTS_DIR / "extraction_prompt.md").read_text(encoding="utf-8")
    return rules_mgmt.strip_draft_blocks(raw)


def build_system_prompt() -> str:
    return load_rules() + _JSON_CONTRACT


def _parse_json(text: str) -> dict:
    """Parse the model's reply, tolerating a stray ```json fence."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1]
        if t.lstrip().lower().startswith("json"):
            t = t.lstrip()[4:]
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object found in model reply: {text[:200]!r}")
    return json.loads(t[start:end + 1])


_USER_TEXT = "Convert this invoice to the JSON object per the contract."


def _client(api_key: Optional[str] = None):
    """Create an Anthropic client (lazy import; key from arg or env)."""
    import anthropic  # noqa: PLC0415 — lazy so offline core imports without the SDK

    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Extraction runs on the server where the "
            "key is configured; the offline core (Phase 1) does not need it."
        )
    return anthropic.Anthropic(api_key=key)


def _gemini_client(api_key: Optional[str] = None):
    """Create a Gemini (google-genai) client (lazy import; key from arg or env)."""
    from google import genai  # noqa: PLC0415 — lazy so offline core imports without the SDK

    key = api_key or os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Extraction runs on the server where the "
            "key is configured; the offline core (Phase 1) does not need it."
        )
    return genai.Client(api_key=key)


def _extract_anthropic(
    images: list[Image.Image], model: str, system: str,
    api_key: Optional[str], max_tokens: int,
) -> ExtractionOutput:
    client = _client(api_key)
    content: list[dict] = []
    for img in images:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": pdf_prep.to_base64_png(img),
            },
        })
    content.append({"type": "text", "text": _USER_TEXT})

    msg = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": content}],
    )
    raw = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
    return ExtractionOutput(data=_parse_json(raw), model_used=model, raw_text=raw)


def _extract_gemini(
    images: list[Image.Image], model: str, system: str,
    api_key: Optional[str], max_tokens: int,
) -> ExtractionOutput:
    from google.genai import types  # noqa: PLC0415 — lazy

    client = _gemini_client(api_key)
    parts = [
        types.Part.from_bytes(
            data=base64.b64decode(pdf_prep.to_base64_png(img)),
            mime_type="image/png",
        )
        for img in images
    ]
    parts.append(types.Part.from_text(text=_USER_TEXT))

    # Gemini 2.5 "thinking" tokens count against max_output_tokens. Too small a
    # thinking budget (e.g. 128) makes flash degenerate into a line-item repetition
    # loop on multi-page invoices; a fixed 1024 lets it reason and stop cleanly.
    # Give the JSON body ample headroom on top of that.
    resp = client.models.generate_content(
        model=model,
        contents=[types.Content(role="user", parts=parts)],
        config=types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max(max_tokens, 24000),
            temperature=0,
            response_mime_type="application/json",
            thinking_config=types.ThinkingConfig(thinking_budget=1024),
        ),
    )
    # A truncated reply (dense invoices can push flash into a line-item repetition
    # loop that hits the token cap) yields half a JSON object. Fail cleanly here so
    # the caller escalates / routes to review instead of choking on a parse error.
    cand = resp.candidates[0] if resp.candidates else None
    if cand is not None and str(getattr(cand, "finish_reason", "")).endswith("MAX_TOKENS"):
        raise RuntimeError(f"{model} response truncated at the token limit "
                           "(likely a repetition loop); routing to review")
    raw = resp.text or ""
    return ExtractionOutput(data=_parse_json(raw), model_used=model, raw_text=raw)


_PROVIDERS = {"anthropic": _extract_anthropic, "gemini": _extract_gemini}


def extract_images(
    images: list[Image.Image],
    model: str,
    api_key: Optional[str] = None,
    max_tokens: int = 8000,
    provider: str = "anthropic",
) -> ExtractionOutput:
    """Send page images to the vision model and return parsed JSON. The system
    prompt and JSON contract are identical across providers."""
    try:
        fn = _PROVIDERS[provider]
    except KeyError:
        raise ValueError(f"unknown extraction provider: {provider!r} "
                         f"(expected one of {sorted(_PROVIDERS)})")
    return fn(images, model, build_system_prompt(), api_key, max_tokens)


def extract_file(
    path: str | Path,
    model: str,
    dpi: int = 220,
    do_deskew: bool = True,
    api_key: Optional[str] = None,
    provider: str = "anthropic",
) -> ExtractionOutput:
    """Prepare a file (rasterise/deskew) and extract it with the vision model."""
    images = pdf_prep.prepare(path, dpi=dpi, do_deskew=do_deskew)
    log.info("extracting %s (%d page(s)) with %s/%s",
             Path(path).name, len(images), provider, model)
    return extract_images(images, model=model, api_key=api_key, provider=provider)
