"""
BMW Dynamic Specsheet - Model-Agnostic PDF Update Classifier (Stages 1-3)
Module: pdf_update_classifier.py

Pure Python, 100% model-agnostic pipeline for classifying brochure PDF updates:
  Stage 1: Model-Agnostic Lineage Resolver (across master_specs and custom_specs)
  Stage 2: Pure Python Visual Fingerprint Extractor & Comparator (dimensions + wheels)
  Stage 3: 4-Case Decision Matrix + Dual-Language TH/EN Reconciliation Gate

Cases:
  1. IDENTICAL            -> smart_skipped
  2. MINOR_UPDATE         -> reused_same_gen
  3. LCI_OR_VISUAL_CHANGE -> lci_refresh_required
  4. BRAND_NEW            -> new_model_scrape

Dual-Language Gate statuses (enforcing 100% TH/EN alignment):
  - blocked_th_en_conflict
  - pending_paired_language
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))

CASE_IDENTICAL = "IDENTICAL"
CASE_MINOR_UPDATE = "MINOR_UPDATE"
CASE_LCI_OR_VISUAL_CHANGE = "LCI_OR_VISUAL_CHANGE"
CASE_BRAND_NEW = "BRAND_NEW"

STATUS_SMART_SKIPPED = "smart_skipped"
STATUS_REUSED_SAME_GEN = "reused_same_gen"
STATUS_LCI_REFRESH_REQUIRED = "lci_refresh_required"
STATUS_NEW_MODEL_SCRAPE = "new_model_scrape"
STATUS_BLOCKED_TH_EN_CONFLICT = "blocked_th_en_conflict"
STATUS_PENDING_PAIRED_LANGUAGE = "pending_paired_language"
STATUS_PENDING_CONFIGURATOR = "pending_configurator"
STATUS_SCRAPED = "scraped"


# ==============================================================================
# Stage 1: Model-Agnostic Lineage Resolver
# ==============================================================================

def _strip_accents(text: str) -> str:
    """Fold diacritics (e.g. Coupé -> Coupe) deterministically without altering Thai marks."""
    out_chars: List[str] = []
    for ch in unicodedata.normalize("NFKD", text):
        if unicodedata.combining(ch) and ord(ch) < 0x0E00:
            continue
        out_chars.append(ch)
    return "".join(out_chars)


def normalize_series_name(series_name: str) -> str:
    """Normalize series name (e.g. 'BMW 7 SERIES' == 'BMW 7 Series' -> 'bmw 7 series')."""
    text = _strip_accents((series_name or "").strip())
    text = re.sub(r"\s+", " ", text).lower()
    return text


def normalize_model_name(model_name: str) -> str:
    """Normalize model name case-insensitively with collapsed whitespace and accent folding."""
    text = _strip_accents((model_name or "").strip())
    text = re.sub(r"\s+", " ", text).lower()
    return text


def extract_doc_date_sort_key(pdf_source: str) -> Tuple[int, int, int, int, str]:
    """
    Extract sortable recency key from a brochure filename purely by structure.
    Returns (doc_yyyymmdd, edition_seq, revision_num, asset_timestamp, filename).
    """
    name = os.path.basename(pdf_source or "")
    date_match = re.search(r"(20\d{6})(?:-(\d+))?", name)
    doc_date = int(date_match.group(1)) if date_match else 0
    edition_seq = int(date_match.group(2)) if (date_match and date_match.group(2)) else 0

    rev_match = re.search(r"\bREV(\d*)\b", name, flags=re.IGNORECASE)
    if rev_match:
        rev_num = int(rev_match.group(1)) if rev_match.group(1) else 1
    else:
        rev_num = 0

    asset_match = re.search(r"\.asset\.(\d+)", name)
    asset_ts = int(asset_match.group(1)) if asset_match else 0

    return (doc_date, edition_seq, rev_num, asset_ts, name.lower())


def extract_paired_brochure_key(pdf_source: str) -> Tuple[str, int, int]:
    """
    Build a language-neutral brochure cycle key (series_prefix, doc_yyyymmdd, edition_seq)
    for checking whether TH and EN PDFs belong to the same update cycle.
    """
    name = os.path.basename(pdf_source or "")
    base = name.split(".asset.")[0]
    date_match = re.search(r"^(.*?)[-_.]?(20\d{6})(?:-(\d+))?", base)
    if date_match:
        prefix = re.sub(r"[^a-z0-9]+", "", date_match.group(1).lower())
        doc_date = int(date_match.group(2))
        edition_seq = int(date_match.group(3) or 0)
        return (prefix, doc_date, edition_seq)

    cleaned = re.sub(r"_(th|en)(_edit)?(\.pdf)?$", "", base, flags=re.IGNORECASE)
    cleaned = re.sub(r"[^a-z0-9]+", "", cleaned.lower())
    return (cleaned, 0, 0)


def _iter_catalog_models(
    specs_list: List[Dict[str, Any]],
    source_tier: str,
) -> List[Dict[str, Any]]:
    """Flatten catalog entries into comparable lineage records."""
    records: List[Dict[str, Any]] = []
    if not isinstance(specs_list, list):
        return records
    for entry in specs_list:
        if not isinstance(entry, dict):
            continue
        series_raw = entry.get("series", "")
        pdf_source = entry.get("pdf_source") or entry.get("source_file") or ""
        for model in entry.get("models", []) or []:
            if not isinstance(model, dict):
                continue
            model_raw = model.get("model_name", "")
            records.append(
                {
                    "source_tier": source_tier,
                    "entry": entry,
                    "model": model,
                    "series": series_raw,
                    "model_name": model_raw,
                    "norm_series": normalize_series_name(series_raw),
                    "norm_model": normalize_model_name(model_raw),
                    "pdf_source": pdf_source,
                    "sort_key": extract_doc_date_sort_key(pdf_source),
                    "has_images": bool(model.get("images")),
                }
            )
    return records


def find_predecessor_lineage(
    candidate_entry: Dict[str, Any],
    candidate_model: Dict[str, Any],
    master_specs: List[Dict[str, Any]],
    custom_specs: List[Dict[str, Any]],
    exclude_pdf_source: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Search master_specs and custom_specs for an exact (normalized_series, normalized_model_name)
    predecessor. Never borrows images from non-exact sub-models; collects closest_series_models
    only as diagnostic metadata.
    """
    cand_series = candidate_entry.get("series", "")
    cand_model_name = candidate_model.get("model_name", "")
    cand_pdf = candidate_entry.get("pdf_source") or candidate_entry.get("source_file") or ""

    norm_series = normalize_series_name(cand_series)
    norm_model = normalize_model_name(cand_model_name)

    all_records = _iter_catalog_models(master_specs, "master") + _iter_catalog_models(
        custom_specs, "custom"
    )

    exact_matches: List[Dict[str, Any]] = []
    series_siblings: Dict[str, Dict[str, Any]] = {}

    for rec in all_records:
        if exclude_pdf_source and rec["pdf_source"] == exclude_pdf_source:
            continue
        if cand_pdf and rec["pdf_source"] == cand_pdf and rec["norm_model"] == norm_model:
            continue
        if rec["norm_series"] != norm_series:
            continue

        if rec["norm_model"] == norm_model:
            exact_matches.append(rec)
        else:
            sib_key = f"{rec['norm_model']}::{rec['pdf_source']}"
            if sib_key not in series_siblings:
                series_siblings[sib_key] = rec

    # Prefer active master before custom archive, latest doc date, and entries with images
    exact_matches.sort(
        key=lambda r: (
            1 if r["source_tier"] == "master" else 0,
            r["sort_key"],
            1 if r["has_images"] else 0,
        ),
        reverse=True,
    )

    siblings_sorted = sorted(
        series_siblings.values(),
        key=lambda r: (1 if r["source_tier"] == "master" else 0, r["sort_key"]),
        reverse=True,
    )
    closest_series_models = [
        {
            "model_name": s["model_name"],
            "pdf_source": s["pdf_source"],
            "source_tier": s["source_tier"],
            "has_images": s["has_images"],
        }
        for s in siblings_sorted
    ]

    if exact_matches:
        chosen = exact_matches[0]
        return {
            "found": True,
            "predecessor_tier": chosen["source_tier"],
            "predecessor_entry": chosen["entry"],
            "predecessor_model": chosen["model"],
            "predecessor_pdf_source": chosen["pdf_source"],
            "alternate_matches_count": len(exact_matches) - 1,
            "closest_series_models": closest_series_models,
        }

    return {
        "found": False,
        "predecessor_tier": None,
        "predecessor_entry": None,
        "predecessor_model": None,
        "predecessor_pdf_source": None,
        "alternate_matches_count": 0,
        "closest_series_models": closest_series_models,
    }


# ==============================================================================
# Stage 2: Pure Python Visual Fingerprint Extractor & Comparator
# ==============================================================================

def normalize_dimensions_value(raw_value: str) -> str:
    """
    Extract numeric L / W / H values from raw dimensions string (handles commas, spaces,
    '/' or '×' separators) and return canonical 'L/W/H' e.g. '5391/1950/1544'.
    """
    if not raw_value:
        return ""
    cleaned = str(raw_value).replace(",", "").strip()
    nums = re.findall(r"\d+(?:\.\d+)?", cleaned)
    if len(nums) >= 3:
        return "/".join(nums[:3])
    return ""


def normalize_wheels_value(raw_value: str) -> str:
    """
    Deterministically normalize wheel specification strings:
    - Convert '' / curly quotes / prime marks to standard double quote '"'
    - Split camelCase OCR joins (e.g. 'wheelsBicolour' -> 'wheels Bicolour')
    - Strip standalone uppercase 'I' used in BMW PDFs as a vertical bar separator after wheels/alloy
    - Lowercase
    - Insert spaces at Latin/digit <-> Thai boundaries (e.g. 'aerodynamicขนาด' -> 'aerodynamic ขนาด')
    - Separate Thai inch unit 'นิ้ว' from following Thai words (e.g. 'นิ้วลาย' -> 'นิ้ว ลาย')
    - Normalize punctuation separators (, | /) and collapse whitespace
    """
    if not raw_value:
        return ""
    text = str(raw_value)
    text = text.replace("''", '"').replace("“", '"').replace("”", '"').replace("″", '"').replace("‟", '"')
    # Split OCR camelCase joins before lowercasing (e.g. wheelsDouble-spoke -> wheels Double-spoke)
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    # Handle PDF glyph where uppercase 'I' acts as a vertical divider '|' (e.g. 'wheels I Bicolour')
    text = re.sub(r"\b(wheels|alloy)\s+I\s+(?=[A-Z0-9])", r"\1 ", text)
    text = text.lower()
    # Separate Latin/digit/quote from Thai script boundaries
    text = re.sub(r'([a-z0-9"])([\u0E00-\u0E7F])', r"\1 \2", text)
    text = re.sub(r'([\u0E00-\u0E7F])([a-z0-9"])', r"\1 \2", text)
    # Separate Thai inch unit from adjacent Thai text (e.g. นิ้วลาย -> นิ้ว ลาย, นิ้วตกแต่งสี -> นิ้ว ตกแต่งสี)
    text = re.sub(r"(นิ้ว)([\u0E00-\u0E7F])", r"\1 \2", text)
    # Normalize punctuation separators (e.g. 'wheels | Bicolour', '19"/20"', 'Jet Black,')
    text = re.sub(r"\s*[,|]\s*", " ", text)
    text = re.sub(r"\s*/\s*", " / ", text)
    text = re.sub(r'"([a-z0-9])', r'" \1', text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_wheel_core_signature(raw_value: str) -> Dict[str, List[str]]:
    """
    Extract model-agnostic core wheel signature using Pure Python regex only:
      - inch_sizes: numeric wheel sizes (e.g. ['18'], ['19', '20'])
      - english_tokens: normalized Latin/alphanumeric style/code tokens
    Used by Dual-Language Gate to verify whether a TH-only text change is purely
    Thai phrasing/typo/spacing vs an actual wheel spec conflict.
    """
    norm = normalize_wheels_value(raw_value)
    if not norm:
        return {"inch_sizes": [], "english_tokens": []}

    inch_sizes = re.findall(r"\b(\d{2})\b", norm)
    # Capture alphanumeric codes/style words (e.g. double-spoke, 909, m, bicolour, 3d)
    raw_tokens = re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", norm)
    english_tokens = [tok for tok in raw_tokens if tok not in inch_sizes]
    return {
        "inch_sizes": inch_sizes,
        "english_tokens": english_tokens,
    }


def _is_dimension_category(cat_name: str) -> bool:
    low = re.sub(r"\s+", " ", (cat_name or "").strip().lower())
    return ("มิติ" in low) or ("dimension" in low)


def _is_dimension_topic(topic_name: str) -> bool:
    low = re.sub(r"\s+", " ", (topic_name or "").strip().lower())
    compact = low.replace(" ", "")
    return ("ยาว/กว้าง/สูง" in compact) or ("length/width/height" in compact)


def _is_wheels_category(cat_name: str) -> bool:
    low = re.sub(r"\s+", " ", (cat_name or "").strip().lower())
    return ("ล้อและยาง" in low) or ("wheels" in low)


def _is_wheels_topic(topic_name: str) -> bool:
    low = re.sub(r"\s+", " ", (topic_name or "").strip().lower())
    return low in ("ล้อ", "wheels", "light alloy wheels")


def _is_powertrain_category(cat_name: str) -> bool:
    low = re.sub(r"\s+", " ", (cat_name or "").strip().lower())
    return any(
        kw in low
        for kw in ("เครื่องยนต์", "สมรรถนะ", "engine", "performance", "มอเตอร์", "electric", "drive")
    )


def _is_powertrain_topic(topic_name: str) -> bool:
    norm = (topic_name or "").replace("\u0e4d\u0e32", "\u0e33").replace("\u0e32\u0e4d", "\u0e33")
    low = re.sub(r"\s+", " ", norm.strip().lower())
    return any(
        kw in low
        for kw in ("กำลังสูงสุด", "engine power", "system output", "maximum output", "max. output", "power output")
    )


def _parse_kw_hp_pair(raw_value: str) -> Optional[Dict[str, int]]:
    """Parse '<kw> / <hp>' numeric pair from normalized specification power strings."""
    cleaned = str(raw_value or "").replace(",", "").strip()
    if not cleaned or cleaned == "-":
        return None
    nums = re.findall(r"\d+(?:\.\d+)?", cleaned)
    if len(nums) >= 2:
        kw = int(round(float(nums[0])))
        hp = int(round(float(nums[1])))
        if kw > 0 and hp >= kw:
            return {"kw": kw, "hp": hp}
    return None


def extract_powertrain_metrics(model: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deterministically extract powertrain output metrics (kW / hp) from a model specsheet
    with priority: System Output -> Electric Motor Peak (BEV) / ICE Engine Power.
    Excludes battery capacity (kWh) and charging power (AC/DC kW).
    """
    system_pair: Optional[Dict[str, Any]] = None
    motor_pair: Optional[Dict[str, Any]] = None
    engine_pair: Optional[Dict[str, Any]] = None

    for cat in model.get("specifications", []) or []:
        cat_name = cat.get("category", "")
        if not _is_powertrain_category(cat_name):
            continue
        for detail in cat.get("details", []) or []:
            topic = (detail.get("topic") or "").strip()
            tlow = re.sub(
                r"\s+",
                " ",
                topic.replace("\u0e4d\u0e32", "\u0e33").replace("\u0e32\u0e4d", "\u0e33").lower(),
            )
            val = (detail.get("value") or "").strip()
            if not val or val == "-":
                continue

            # Exclude energy/battery capacity, consumption, and charging topics
            if any(
                excl in tlow
                for excl in (
                    "แบตเตอรี่",
                    "battery",
                    "ชาร์จ",
                    "charging",
                    "อัตราการใช้ไฟฟ้า",
                    "consumption",
                    "kwh",
                )
            ):
                continue

            if ("กำลังรวมสูงสุด" in tlow or "system output" in tlow) and system_pair is None:
                parsed = _parse_kw_hp_pair(val)
                if parsed:
                    system_pair = {**parsed, "kind": "system", "source_topic": topic}
            elif (
                "กำลังมอเตอร์ไฟฟ้า" in tlow or "electric motor power" in tlow or "motor output" in tlow
            ) and motor_pair is None:
                parsed = _parse_kw_hp_pair(val)
                if parsed:
                    motor_pair = {**parsed, "kind": "motor", "source_topic": topic}
            elif (
                "กำลังสูงสุด" in tlow
                or "engine power" in tlow
                or "maximum output" in tlow
                or "max. output" in tlow
                or "power output" in tlow
            ) and engine_pair is None:
                parsed = _parse_kw_hp_pair(val)
                if parsed:
                    engine_pair = {**parsed, "kind": "engine", "source_topic": topic}

    candidates: List[Dict[str, Any]] = []
    if system_pair:
        primary = system_pair
        candidates.append(system_pair)
        if engine_pair:
            candidates.append(engine_pair)
    elif engine_pair:
        primary = engine_pair
        candidates.append(engine_pair)
    elif motor_pair:
        primary = motor_pair
        candidates.append(motor_pair)
    else:
        primary = {"kw": None, "hp": None, "source_topic": ""}

    return {
        "kw": primary.get("kw"),
        "hp": primary.get("hp"),
        "source_topic": primary.get("source_topic", ""),
        "candidates": candidates,
    }


def extract_visual_fingerprint(model: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract deterministic visual fingerprint from a model dictionary.
    Strictly filters within Dimension and Wheels categories to avoid false matches
    such as Steering wheel in Interior.
    """
    dims_raw = ""
    wheels_raw = ""
    power_raw = ""

    for cat in model.get("specifications", []) or []:
        cat_name = cat.get("category", "")
        details = cat.get("details", []) or []

        if _is_dimension_category(cat_name) and not dims_raw:
            for detail in details:
                if _is_dimension_topic(detail.get("topic", "")):
                    val = (detail.get("value") or "").strip()
                    if val and val != "-":
                        dims_raw = val
                        break

        if _is_wheels_category(cat_name) and not wheels_raw:
            for detail in details:
                if _is_wheels_topic(detail.get("topic", "")):
                    val = (detail.get("value") or "").strip()
                    if val and val != "-":
                        wheels_raw = val
                        break

        if _is_powertrain_category(cat_name) and not power_raw:
            for detail in details:
                if _is_powertrain_topic(detail.get("topic", "")):
                    val = (detail.get("value") or "").strip()
                    if val and val != "-":
                        power_raw = val
                        break

    dims_norm = normalize_dimensions_value(dims_raw)
    wheels_norm = normalize_wheels_value(wheels_raw)
    wheels_core = extract_wheel_core_signature(wheels_raw)

    return {
        "dimensions": dims_norm,
        "dimensions_raw": dims_raw,
        "wheels": wheels_norm,
        "wheels_raw": wheels_raw,
        "wheels_core": wheels_core,
        "powertrain_output": re.sub(r"\s+", " ", power_raw).strip(),
    }


def compare_visual_fingerprints(old_fp: Dict[str, Any], new_fp: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compare old and new visual fingerprints deterministically.
    Fail-safe guard: if either dimensions or wheels is missing on either side,
    do NOT allow classification as MINOR_UPDATE (Case 2).
    """
    missing_fields: List[str] = []
    for side_label, fp in (("old", old_fp), ("new", new_fp)):
        if not fp.get("dimensions"):
            missing_fields.append(f"{side_label}.dimensions")
        if not fp.get("wheels"):
            missing_fields.append(f"{side_label}.wheels")

    dims_old = old_fp.get("dimensions", "")
    dims_new = new_fp.get("dimensions", "")
    wheels_old = old_fp.get("wheels", "")
    wheels_new = new_fp.get("wheels", "")

    dims_complete = bool(dims_old and dims_new)
    wheels_complete = bool(wheels_old and wheels_new)

    dimensions_match = dims_complete and (dims_old == dims_new)
    wheels_match = wheels_complete and (wheels_old == wheels_new)

    visual_diff: Dict[str, Any] = {}
    if not dimensions_match:
        visual_diff["dimensions"] = {"old": dims_old or None, "new": dims_new or None}
    if not wheels_match:
        visual_diff["wheels"] = {
            "old": wheels_old or None,
            "new": wheels_new or None,
            "old_raw": old_fp.get("wheels_raw") or None,
            "new_raw": new_fp.get("wheels_raw") or None,
        }
    if old_fp.get("powertrain_output") != new_fp.get("powertrain_output"):
        visual_diff["powertrain_output"] = {
            "old": old_fp.get("powertrain_output") or None,
            "new": new_fp.get("powertrain_output") or None,
        }

    return {
        "all_match": bool(not missing_fields and dimensions_match and wheels_match),
        "dimensions_match": dimensions_match,
        "wheels_match": wheels_match,
        "dimensions_complete": dims_complete,
        "wheels_complete": wheels_complete,
        "missing_fields": missing_fields,
        "visual_diff": visual_diff,
    }


# ==============================================================================
# Stage 3: 4-Case Decision Matrix & Dual-Language Reconciliation Gate
# ==============================================================================

def _normalize_color_key(name: str) -> str:
    """Normalize exterior paint name consistently with frontend/daily audit rules."""
    if not name:
        return ""
    n = _strip_accents(name).lower().strip()
    n = re.sub(r"\bmetalic\b", "metallic", n)
    n = n.replace("metallic", "").replace("solid", "").strip()
    n = re.sub(r"^m\s+", "", n)
    n = re.sub(r"[^a-z0-9]", "", n)
    return n


def _extract_model_paint_colors(model: Dict[str, Any]) -> List[str]:
    colors: List[str] = []
    for cat in model.get("specifications", []) or []:
        cat_name = (cat.get("category") or "").lower()
        if "paintwork" in cat_name or "สีตัวถัง" in cat_name:
            for detail in cat.get("details", []) or []:
                topic = (detail.get("topic") or "").strip()
                val = (detail.get("value") or "").strip()
                if topic and val != "-":
                    colors.append(topic)
    return colors


def match_carry_over_images(old_images: Dict[str, str], new_model: Dict[str, Any]) -> Dict[str, str]:
    """
    Carry over images from predecessor only for paint colors present in the new model
    using normalized color matching.
    """
    if not isinstance(old_images, dict) or not old_images:
        return {}

    new_colors = _extract_model_paint_colors(new_model)
    if not new_colors:
        return copy.deepcopy(old_images)

    old_norm_items = [(_normalize_color_key(k), k, v) for k, v in old_images.items() if v]
    carried: Dict[str, str] = {}

    for new_color in new_colors:
        c_norm = _normalize_color_key(new_color)
        if not c_norm:
            continue
        matched_item = next(
            (
                (orig_k, path)
                for old_norm, orig_k, path in old_norm_items
                if old_norm and (c_norm == old_norm or c_norm in old_norm or old_norm in c_norm)
            ),
            None,
        )
        if matched_item:
            orig_k, path = matched_item
            carried[orig_k] = path

    return carried


def classify_model_update(
    candidate_entry: Dict[str, Any],
    candidate_model: Dict[str, Any],
    master_specs: List[Dict[str, Any]],
    custom_specs: List[Dict[str, Any]],
    pdf_identical: bool = False,
    pdf_identical_reason: str = "",
    exclude_pdf_source: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Classify a single model update into one of 4 automated cases:
      Case 1: IDENTICAL (smart_skipped)
      Case 2: MINOR_UPDATE (reused_same_gen)
      Case 3: LCI_OR_VISUAL_CHANGE (lci_refresh_required)
      Case 4: BRAND_NEW (new_model_scrape)
    """
    series_name = candidate_entry.get("series", "")
    model_name = candidate_model.get("model_name", "")
    pdf_source = candidate_entry.get("pdf_source") or candidate_entry.get("source_file") or ""

    lineage = find_predecessor_lineage(
        candidate_entry=candidate_entry,
        candidate_model=candidate_model,
        master_specs=master_specs,
        custom_specs=custom_specs,
        exclude_pdf_source=exclude_pdf_source,
    )
    new_fp = extract_visual_fingerprint(candidate_model)

    if not lineage["found"]:
        return {
            "series": series_name,
            "model_name": model_name,
            "pdf_source": pdf_source,
            "case_id": 4,
            "case_name": CASE_BRAND_NEW,
            "image_status": STATUS_NEW_MODEL_SCRAPE,
            "images": {},
            "predecessor_found": False,
            "predecessor_tier": None,
            "predecessor_pdf_source": None,
            "previous_images_count": 0,
            "closest_series_models": lineage["closest_series_models"],
            "new_fingerprint": new_fp,
            "old_fingerprint": None,
            "comparison": None,
            "reason": "No exact (series, model_name) lineage found in master or custom archives.",
        }

    pred_model = lineage["predecessor_model"]
    pred_images = pred_model.get("images") if isinstance(pred_model.get("images"), dict) else {}
    old_fp = extract_visual_fingerprint(pred_model)
    comp = compare_visual_fingerprints(old_fp, new_fp)

    if pdf_identical:
        carried = match_carry_over_images(pred_images, candidate_model) if pred_images else {}
        return {
            "series": series_name,
            "model_name": model_name,
            "pdf_source": pdf_source,
            "case_id": 1,
            "case_name": CASE_IDENTICAL,
            "image_status": STATUS_SMART_SKIPPED,
            "images": carried if carried else copy.deepcopy(pred_images),
            "predecessor_found": True,
            "predecessor_tier": lineage["predecessor_tier"],
            "predecessor_pdf_source": lineage["predecessor_pdf_source"],
            "previous_images_count": len(pred_images),
            "closest_series_models": lineage["closest_series_models"],
            "new_fingerprint": new_fp,
            "old_fingerprint": old_fp,
            "comparison": comp,
            "reason": pdf_identical_reason or "PDF binary/text matches predecessor 100%.",
        }

    if comp["all_match"]:
        carried = match_carry_over_images(pred_images, candidate_model)
        return {
            "series": series_name,
            "model_name": model_name,
            "pdf_source": pdf_source,
            "case_id": 2,
            "case_name": CASE_MINOR_UPDATE,
            "image_status": STATUS_REUSED_SAME_GEN,
            "images": carried,
            "predecessor_found": True,
            "predecessor_tier": lineage["predecessor_tier"],
            "predecessor_pdf_source": lineage["predecessor_pdf_source"],
            "previous_images_count": len(pred_images),
            "closest_series_models": lineage["closest_series_models"],
            "new_fingerprint": new_fp,
            "old_fingerprint": old_fp,
            "comparison": comp,
            "reason": "Exact lineage found and visual fingerprint (dimensions + wheels) matches 100%.",
        }

    reason_parts: List[str] = []
    if comp["missing_fields"]:
        reason_parts.append(f"Missing fingerprint fields: {', '.join(comp['missing_fields'])}")
    if not comp["dimensions_match"]:
        reason_parts.append("Dimensions changed or incomplete")
    if not comp["wheels_match"]:
        reason_parts.append("Wheels changed or incomplete")

    return {
        "series": series_name,
        "model_name": model_name,
        "pdf_source": pdf_source,
        "case_id": 3,
        "case_name": CASE_LCI_OR_VISUAL_CHANGE,
        "image_status": STATUS_LCI_REFRESH_REQUIRED,
        "images": {},
        "predecessor_found": True,
        "predecessor_tier": lineage["predecessor_tier"],
        "predecessor_pdf_source": lineage["predecessor_pdf_source"],
        "previous_images_count": len(pred_images),
        "closest_series_models": lineage["closest_series_models"],
        "new_fingerprint": new_fp,
        "old_fingerprint": old_fp,
        "comparison": comp,
        "reason": "; ".join(reason_parts) or "Visual fingerprint changed.",
    }


def classify_brochure_update(
    candidate_entry: Dict[str, Any],
    master_specs: List[Dict[str, Any]],
    custom_specs: List[Dict[str, Any]],
    pdf_identical: bool = False,
    pdf_identical_reason: str = "",
    exclude_pdf_source: Optional[str] = None,
) -> Dict[str, Any]:
    """Classify all models inside a single brochure entry and summarize per-brochure status."""
    model_results: List[Dict[str, Any]] = []
    case_counts: Dict[str, int] = {
        CASE_IDENTICAL: 0,
        CASE_MINOR_UPDATE: 0,
        CASE_LCI_OR_VISUAL_CHANGE: 0,
        CASE_BRAND_NEW: 0,
    }

    for model in candidate_entry.get("models", []) or []:
        res = classify_model_update(
            candidate_entry=candidate_entry,
            candidate_model=model,
            master_specs=master_specs,
            custom_specs=custom_specs,
            pdf_identical=pdf_identical,
            pdf_identical_reason=pdf_identical_reason,
            exclude_pdf_source=exclude_pdf_source,
        )
        model_results.append(res)
        case_counts[res["case_name"]] = case_counts.get(res["case_name"], 0) + 1

    return {
        "series": candidate_entry.get("series", ""),
        "pdf_source": candidate_entry.get("pdf_source") or candidate_entry.get("source_file") or "",
        "models_count": len(model_results),
        "case_counts": case_counts,
        "models": model_results,
    }


def reconcile_th_en_updates(
    th_classification: Dict[str, Any],
    en_classification: Dict[str, Any],
    th_paired_cycle: bool = True,
    en_paired_cycle: bool = True,
) -> Dict[str, Any]:
    """
    Dual-Language Reconciliation Gate ensuring TH and EN agree 100% on images & image_status:
      1. Paired-cycle guard: if only one language updated cycle, flag pending_paired_language.
      2. Dimensions (symmetric): if EN_unchanged != TH_unchanged -> blocked_th_en_conflict.
      3. Wheels:
         - EN_unchanged & not TH_unchanged: check TH core wheel signature (inch sizes + English tokens).
           If core signature matches -> EN is authoritative (eligible for reused_same_gen).
           If core signature differs -> blocked_th_en_conflict.
         - TH_unchanged & not EN_unchanged -> blocked_th_en_conflict.
      4. Sync identical images & image_status across both TH and EN outputs.
    """
    model_name = th_classification.get("model_name") or en_classification.get("model_name") or ""
    series_name = th_classification.get("series") or en_classification.get("series") or ""

    if not (th_paired_cycle and en_paired_cycle):
        missing_lang = "EN" if not en_paired_cycle else "TH"
        return {
            "series": series_name,
            "model_name": model_name,
            "final_case": th_classification.get("case_name"),
            "image_status": STATUS_PENDING_PAIRED_LANGUAGE,
            "images": {},
            "conflict": True,
            "conflict_type": "Unpaired Update Cycle",
            "reason": f"Waiting for paired {missing_lang} brochure from the same update cycle.",
            "audit_notes": [],
        }

    th_case = th_classification.get("case_name")
    en_case = en_classification.get("case_name")

    if th_case == CASE_BRAND_NEW and en_case == CASE_BRAND_NEW:
        return {
            "series": series_name,
            "model_name": model_name,
            "final_case": CASE_BRAND_NEW,
            "image_status": STATUS_NEW_MODEL_SCRAPE,
            "images": {},
            "conflict": False,
            "conflict_type": None,
            "reason": "Both TH and EN classified as BRAND_NEW.",
            "audit_notes": [],
        }

    if th_case != en_case and CASE_BRAND_NEW in (th_case, en_case):
        return {
            "series": series_name,
            "model_name": model_name,
            "final_case": CASE_LCI_OR_VISUAL_CHANGE,
            "image_status": STATUS_BLOCKED_TH_EN_CONFLICT,
            "images": {},
            "conflict": True,
            "conflict_type": "Lineage Mismatch (TH vs EN)",
            "reason": f"TH classified as {th_case} while EN classified as {en_case}.",
            "audit_notes": [],
        }

    if th_case == CASE_IDENTICAL and en_case == CASE_IDENTICAL:
        synced_images = copy.deepcopy(th_classification.get("images") or en_classification.get("images") or {})
        return {
            "series": series_name,
            "model_name": model_name,
            "final_case": CASE_IDENTICAL,
            "image_status": STATUS_SMART_SKIPPED,
            "images": synced_images,
            "conflict": False,
            "conflict_type": None,
            "reason": "Both TH and EN PDFs are identical to predecessors.",
            "audit_notes": [],
        }

    th_comp = th_classification.get("comparison") or {}
    en_comp = en_classification.get("comparison") or {}
    audit_notes: List[str] = []

    if not th_comp.get("dimensions_complete") or not en_comp.get("dimensions_complete"):
        return {
            "series": series_name,
            "model_name": model_name,
            "final_case": CASE_LCI_OR_VISUAL_CHANGE,
            "image_status": STATUS_BLOCKED_TH_EN_CONFLICT,
            "images": {},
            "conflict": True,
            "conflict_type": "Missing Dimensions Field",
            "reason": "Dimensions missing in TH or EN predecessor/candidate fingerprint.",
            "audit_notes": [],
        }

    if not th_comp.get("wheels_complete") or not en_comp.get("wheels_complete"):
        return {
            "series": series_name,
            "model_name": model_name,
            "final_case": CASE_LCI_OR_VISUAL_CHANGE,
            "image_status": STATUS_BLOCKED_TH_EN_CONFLICT,
            "images": {},
            "conflict": True,
            "conflict_type": "Missing Wheels Field",
            "reason": "Wheels missing in TH or EN predecessor/candidate fingerprint.",
            "audit_notes": [],
        }

    th_dim_same = bool(th_comp.get("dimensions_match"))
    en_dim_same = bool(en_comp.get("dimensions_match"))

    # 1. Dimensions must agree symmetrically across TH and EN
    if th_dim_same != en_dim_same:
        return {
            "series": series_name,
            "model_name": model_name,
            "final_case": CASE_LCI_OR_VISUAL_CHANGE,
            "image_status": STATUS_BLOCKED_TH_EN_CONFLICT,
            "images": {},
            "conflict": True,
            "conflict_type": "Dimensions TH/EN Conflict",
            "reason": (
                f"Dimensions agreement mismatch: TH_match={th_dim_same} vs EN_match={en_dim_same}. "
                f"TH_diff={th_comp.get('visual_diff', {}).get('dimensions')} | "
                f"EN_diff={en_comp.get('visual_diff', {}).get('dimensions')}"
            ),
            "audit_notes": [],
        }

    # Check exact normalized dimensions values agree between TH and EN too
    th_new_dim = (th_classification.get("new_fingerprint") or {}).get("dimensions")
    en_new_dim = (en_classification.get("new_fingerprint") or {}).get("dimensions")
    if th_new_dim and en_new_dim and th_new_dim != en_new_dim:
        return {
            "series": series_name,
            "model_name": model_name,
            "final_case": CASE_LCI_OR_VISUAL_CHANGE,
            "image_status": STATUS_BLOCKED_TH_EN_CONFLICT,
            "images": {},
            "conflict": True,
            "conflict_type": "Dimensions Value Mismatch (TH vs EN)",
            "reason": f"Candidate dimensions differ between TH ({th_new_dim}) and EN ({en_new_dim}).",
            "audit_notes": [],
        }

    # 2. Wheels check with authoritative EN + TH Core-Spec Guard
    th_wh_same = bool(th_comp.get("wheels_match"))
    en_wh_same = bool(en_comp.get("wheels_match"))

    if th_wh_same and not en_wh_same:
        return {
            "series": series_name,
            "model_name": model_name,
            "final_case": CASE_LCI_OR_VISUAL_CHANGE,
            "image_status": STATUS_BLOCKED_TH_EN_CONFLICT,
            "images": {},
            "conflict": True,
            "conflict_type": "Wheels TH/EN Conflict (TH unchanged, EN changed)",
            "reason": (
                f"Abnormal wheels mismatch: TH unchanged while EN changed. "
                f"EN_diff={en_comp.get('visual_diff', {}).get('wheels')}"
            ),
            "audit_notes": [],
        }

    effective_wheels_same = th_wh_same and en_wh_same
    if en_wh_same and not th_wh_same:
        th_old_core = (th_classification.get("old_fingerprint") or {}).get("wheels_core") or {}
        th_new_core = (th_classification.get("new_fingerprint") or {}).get("wheels_core") or {}
        if th_old_core == th_new_core:
            effective_wheels_same = True
            audit_notes.append(
                "TH wheel text wording/spacing changed while EN and TH core specs (inch sizes + English tokens) match; treated EN as authoritative."
            )
        else:
            return {
                "series": series_name,
                "model_name": model_name,
                "final_case": CASE_LCI_OR_VISUAL_CHANGE,
                "image_status": STATUS_BLOCKED_TH_EN_CONFLICT,
                "images": {},
                "conflict": True,
                "conflict_type": "Wheels Core-Spec TH/EN Conflict",
                "reason": (
                    f"EN wheels unchanged, but TH core wheel specs changed: "
                    f"old_core={th_old_core} vs new_core={th_new_core}."
                ),
                "audit_notes": [],
            }

    # Final unified decision (100% synced across TH & EN)
    if th_dim_same and en_dim_same and effective_wheels_same:
        synced_images = copy.deepcopy(th_classification.get("images") or en_classification.get("images") or {})
        return {
            "series": series_name,
            "model_name": model_name,
            "final_case": CASE_MINOR_UPDATE,
            "image_status": STATUS_REUSED_SAME_GEN,
            "images": synced_images,
            "conflict": False,
            "conflict_type": None,
            "reason": "Dimensions and wheels confirmed unchanged across TH & EN; reusing existing images.",
            "audit_notes": audit_notes,
        }

    return {
        "series": series_name,
        "model_name": model_name,
        "final_case": CASE_LCI_OR_VISUAL_CHANGE,
        "image_status": STATUS_LCI_REFRESH_REQUIRED,
        "images": {},
        "conflict": False,
        "conflict_type": None,
        "reason": "Visual fingerprint (dimensions and/or wheels) changed consistently across TH & EN.",
        "audit_notes": audit_notes,
    }


def _load_json_list(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def reconcile_databases_th_en(
    master_th_path: Optional[str] = None,
    master_en_path: Optional[str] = None,
    custom_th_path: Optional[str] = None,
    custom_en_path: Optional[str] = None,
    dry_run: bool = True,
    report_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Reconcile TH and EN master databases against their archives as pairs, checking
    dimensions, wheels, and image alignment across all models.
    When dry_run=False, writes aligned images/image_status to both TH and EN master JSONs
    and outputs scratch/th_en_reconciliation_report.json.
    """
    master_th_path = master_th_path or os.path.join(WORKSPACE_DIR, "bmw_master_specs.json")
    master_en_path = master_en_path or os.path.join(WORKSPACE_DIR, "bmw_master_specs_en.json")
    custom_th_path = custom_th_path or os.path.join(WORKSPACE_DIR, "bmw_custom_specs.json")
    custom_en_path = custom_en_path or os.path.join(WORKSPACE_DIR, "bmw_custom_specs_en.json")
    report_path = report_path or os.path.join(WORKSPACE_DIR, "scratch", "th_en_reconciliation_report.json")

    m_th = _load_json_list(master_th_path)
    m_en = _load_json_list(master_en_path)
    c_th = _load_json_list(custom_th_path)
    c_en = _load_json_list(custom_en_path)

    en_lookup: Dict[Tuple[str, str], Tuple[Dict[str, Any], Dict[str, Any]]] = {}
    for entry in m_en:
        ns = normalize_series_name(entry.get("series", ""))
        for model in entry.get("models", []) or []:
            nm = normalize_model_name(model.get("model_name", ""))
            en_lookup[(ns, nm)] = (entry, model)

    results: List[Dict[str, Any]] = []
    conflicts: List[Dict[str, Any]] = []
    modified = False

    for th_entry in m_th:
        th_pdf = th_entry.get("pdf_source") or th_entry.get("source_file") or ""
        ns = normalize_series_name(th_entry.get("series", ""))
        for th_model in th_entry.get("models", []) or []:
            nm = normalize_model_name(th_model.get("model_name", ""))
            en_pair = en_lookup.get((ns, nm))
            if not en_pair:
                conflict_item = {
                    "series": th_entry.get("series", ""),
                    "model_name": th_model.get("model_name", ""),
                    "image_status": STATUS_PENDING_PAIRED_LANGUAGE,
                    "conflict": True,
                    "conflict_type": "Missing EN Pair",
                    "reason": "Model present in TH master database but missing in EN master database.",
                }
                conflicts.append(conflict_item)
                results.append(conflict_item)
                continue

            en_entry, en_model = en_pair
            en_pdf = en_entry.get("pdf_source") or en_entry.get("source_file") or ""
            th_key = extract_paired_brochure_key(th_pdf)
            en_key = extract_paired_brochure_key(en_pdf)
            paired_ok = (th_key == en_key) or (th_key[1] == en_key[1] and th_key[1] != 0)

            th_cls = classify_model_update(
                candidate_entry=th_entry,
                candidate_model=th_model,
                master_specs=m_th,
                custom_specs=c_th,
                exclude_pdf_source=th_pdf,
            )
            en_cls = classify_model_update(
                candidate_entry=en_entry,
                candidate_model=en_model,
                master_specs=m_en,
                custom_specs=c_en,
                exclude_pdf_source=en_pdf,
            )

            rec = reconcile_th_en_updates(
                th_classification=th_cls,
                en_classification=en_cls,
                th_paired_cycle=True if paired_ok else (th_key[1] >= en_key[1]),
                en_paired_cycle=True if paired_ok else (en_key[1] >= th_key[1]),
            )
            rec["th_pdf_source"] = th_pdf
            rec["en_pdf_source"] = en_pdf
            results.append(rec)

            if rec.get("conflict"):
                conflicts.append(rec)

            if not dry_run:
                # Preserve existing verified images unless this model was flagged as conflict or newly awaiting images
                if rec["image_status"] in (STATUS_BLOCKED_TH_EN_CONFLICT, STATUS_PENDING_PAIRED_LANGUAGE):
                    th_model["image_status"] = rec["image_status"]
                    en_model["image_status"] = rec["image_status"]
                    th_model["images"] = {}
                    en_model["images"] = {}
                    modified = True
                else:
                    # Ensure TH/EN images stay identical; fill missing side from existing verified side if needed
                    existing_imgs = th_model.get("images") or en_model.get("images") or rec.get("images") or {}
                    if th_model.get("images") != existing_imgs or en_model.get("images") != existing_imgs:
                        th_model["images"] = copy.deepcopy(existing_imgs)
                        en_model["images"] = copy.deepcopy(existing_imgs)
                        modified = True
                    if not existing_imgs:
                        th_st = th_model.get("image_status")
                        en_st = en_model.get("image_status")
                        target_st = (
                            STATUS_PENDING_CONFIGURATOR
                            if STATUS_PENDING_CONFIGURATOR in (th_st, en_st)
                            else rec["image_status"]
                        )
                        if th_st != target_st or en_st != target_st:
                            th_model["image_status"] = target_st
                            en_model["image_status"] = target_st
                            modified = True
                    else:
                        th_st = th_model.get("image_status")
                        en_st = en_model.get("image_status")
                        sync_st = th_st or en_st
                        if sync_st and (th_st != sync_st or en_st != sync_st):
                            th_model["image_status"] = sync_st
                            en_model["image_status"] = sync_st
                            modified = True

    summary = {
        "total_models": len(results),
        "conflicts_count": len(conflicts),
        "conflicts": conflicts,
        "results": results,
    }

    if not dry_run:
        if modified:
            with open(master_th_path, "w", encoding="utf-8") as f:
                json.dump(m_th, f, ensure_ascii=False, indent=4)
            with open(master_en_path, "w", encoding="utf-8") as f:
                json.dump(m_en, f, ensure_ascii=False, indent=4)
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

    return summary


# ==============================================================================
# Stage 4 CLI Dry-Run Analyzer
# ==============================================================================

def run_catalog_dry_run(lang: str = "all") -> Dict[str, Any]:
    """
    Simulate update classification across current master_specs vs custom_specs (excluding exact
    same pdf_source) without modifying any database files.
    """
    langs = ["th", "en"] if lang == "all" else [lang]
    output: Dict[str, Any] = {}

    for l in langs:
        is_th = l == "th"
        master_path = os.path.join(WORKSPACE_DIR, "bmw_master_specs.json" if is_th else "bmw_master_specs_en.json")
        custom_path = os.path.join(WORKSPACE_DIR, "bmw_custom_specs.json" if is_th else "bmw_custom_specs_en.json")

        master_specs = _load_json_list(master_path)
        custom_specs = _load_json_list(custom_path)

        brochure_reports: List[Dict[str, Any]] = []
        totals = {
            CASE_IDENTICAL: 0,
            CASE_MINOR_UPDATE: 0,
            CASE_LCI_OR_VISUAL_CHANGE: 0,
            CASE_BRAND_NEW: 0,
        }

        for entry in master_specs:
            ps = entry.get("pdf_source") or entry.get("source_file") or ""
            rep = classify_brochure_update(
                candidate_entry=entry,
                master_specs=master_specs,
                custom_specs=custom_specs,
                exclude_pdf_source=ps,
            )
            brochure_reports.append(rep)
            for k, v in rep["case_counts"].items():
                totals[k] = totals.get(k, 0) + v

        output[l] = {
            "totals": totals,
            "brochures": brochure_reports,
        }

    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Model-Agnostic BMW PDF Update Classifier")
    parser.add_argument("--dry-run", action="store_true", help="Simulate classification without file writes")
    parser.add_argument("--lang", choices=["th", "en", "all"], default="all", help="Language to analyze")
    parser.add_argument(
        "--reconcile-th-en",
        action="store_true",
        help="Run Dual-Language TH/EN reconciliation gate (writes only when --dry-run is not set)",
    )
    args = parser.parse_args()

    if args.reconcile_th_en:
        summary = reconcile_databases_th_en(dry_run=args.dry_run)
        print(
            f"[RECONCILE] dry_run={args.dry_run} | models={summary['total_models']} | conflicts={summary['conflicts_count']}"
        )
        for c in summary["conflicts"]:
            print(
                f"  [CONFLICT] {c.get('series')} | {c.get('model_name')} -> {c.get('image_status')} ({c.get('conflict_type')}): {c.get('reason')}"
            )
        return

    if args.dry_run:
        res = run_catalog_dry_run(lang=args.lang)
        for l, payload in res.items():
            print(f"\n=== DRY-RUN [{l.upper()}] Summary: {payload['totals']} ===")
            for b in payload["brochures"]:
                for m in b["models"]:
                    if m["predecessor_found"] or m["case_name"] == CASE_BRAND_NEW:
                        print(
                            f"  [{m['case_name']}] {m['series']} | {m['model_name']} ({m['pdf_source']}) "
                            f"-> {m['image_status']} | pred={m['predecessor_pdf_source']} ({m['predecessor_tier']})"
                        )
        if args.lang == "all":
            rec_summary = reconcile_databases_th_en(dry_run=True)
            print(
                f"\n=== DUAL-LANGUAGE RECONCILIATION DRY-RUN === models={rec_summary['total_models']} | conflicts={rec_summary['conflicts_count']}"
            )
            for c in rec_summary["conflicts"]:
                print(
                    f"  [CONFLICT] {c.get('series')} | {c.get('model_name')} -> {c.get('image_status')} ({c.get('conflict_type')}): {c.get('reason')}"
                )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
