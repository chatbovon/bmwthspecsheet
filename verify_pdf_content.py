"""
BMW Dynamic Specsheet - Smart PDF Content Verification
Module: verify_pdf_content.py

Checks if a newly downloaded PDF brochure from BMW Thailand has identical content
to an existing brochure in the catalog (e.g. BMW TH re-uploaded with a new CDN timestamp).

If identical:
  - Updates master specs reference to the new filename and URL.
  - Skips MinerU and Gemini AI extraction (saves 100% quota and avoids false archiving).
  - Deletes the obsolete physical PDF from disk to prevent repo bloat.
  - Allows upload_to_gdrive.py to archive the new PDF to Google Drive.

If genuine changes detected:
  - Leaves the PDF for batch_extractor.py to perform full AI extraction.
"""

import os
import sys
import json
import hashlib
import re

from pdf_update_classifier import (
    STATUS_SMART_SKIPPED,
    extract_doc_date_sort_key,
    extract_paired_brochure_key,
)

# Fix Windows console encoding
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))

def compute_sha256(file_path):
    """Calculates SHA-256 binary hash of a file."""
    if not os.path.exists(file_path):
        return None
    h = hashlib.sha256()
    with open(file_path, 'rb') as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def extract_normalized_text(pdf_path):
    """
    Extracts text from all pages of a PDF and normalizes whitespace.
    Uses pypdfium2 (preferred) or pypdf as fallback.
    """
    if not os.path.exists(pdf_path):
        return ""
    
    text_content = []
    # Try pypdfium2 first
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(pdf_path)
        for page in pdf:
            textpage = page.get_textpage()
            text = textpage.get_text_range()
            if text:
                text_content.append(text)
    except Exception:
        # Fallback to pypdf
        try:
            import pypdf
            reader = pypdf.PdfReader(pdf_path)
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    text_content.append(text)
        except Exception as e:
            print(f"[VERIFY] [WARNING] Could not extract text from {pdf_path}: {e}")
            return ""

    full_text = "\n".join(text_content)
    # Normalize: collapse all consecutive whitespace to single space, strip
    normalized = re.sub(r'\s+', ' ', full_text).strip()
    return normalized

def get_base_pdf_name(filename):
    """
    Extracts the base brochure filename before CDN asset timestamp.
    Example: 'X1-20260417-01_TH.pdf.asset.1778763269988.pdf' -> 'X1-20260417-01_TH.pdf'
    """
    if '.asset.' in filename:
        return filename.split('.asset.')[0]
    return filename

def _is_entry_identical_to_pdf(lang, new_file, new_path, new_sha, old_item, auto_folder, new_text_cache):
    """Compare a candidate PDF against one master catalog item (Tier 1 SHA-256 -> Tier 2 Normalized Text)."""
    old_file = old_item.get("pdf_source")
    if not old_file:
        return False, ""
    old_path = os.path.join(auto_folder, old_file)

    # Tier 1 Check: Binary Hash (SHA-256)
    if os.path.exists(old_path):
        old_sha = compute_sha256(old_path)
        if new_sha and old_sha and new_sha == old_sha:
            return True, "100% Binary Match (Identical SHA-256 Checksum)"
    elif old_item.get("pdf_sha256") and new_sha and new_sha == old_item.get("pdf_sha256"):
        return True, "100% Binary Match with Recorded Master Hash"

    # Tier 2 Check: Normalized Text Content
    if os.path.exists(old_path):
        print(f"[VERIFY] [{lang.upper()}] SHA-256 differs for '{new_file}' vs '{old_file}'. Running Tier 2 Text Verification...")
        if new_text_cache[0] is None:
            new_text_cache[0] = extract_normalized_text(new_path)
        old_text = extract_normalized_text(old_path)
        if new_text_cache[0] and old_text and new_text_cache[0] == old_text:
            return True, "100% Normalized Text Match (Identical Specifications & Tables)"

    return False, ""


def find_identical_master_entry(lang, new_file, new_path, new_sha, master_specs, auto_folder, live_pdfs=None):
    """
    Case 1 (smart_skipped) lookup:
    1. Direct base-filename match (ignores .asset.<ts> suffixes).
    2. Lineage fallback when brochure filename/date changes:
       - Binary SHA-256 match against any non-live master entry.
       - Normalized text match against non-live master entries sharing the same series prefix.
    Returns (matched_item_or_None, is_identical, match_reason).
    """
    new_base = get_base_pdf_name(new_file)
    new_text_cache = [None]

    # Step 1: Exact base-name match
    for item in master_specs:
        old_source = item.get("pdf_source", "")
        if not old_source:
            continue
        if get_base_pdf_name(old_source) == new_base:
            is_identical, match_reason = _is_entry_identical_to_pdf(
                lang, new_file, new_path, new_sha, item, auto_folder, new_text_cache
            )
            return item, is_identical, match_reason

    # Step 2: Lineage fallback for renamed / newly dated identical brochures
    new_prefix = extract_paired_brochure_key(new_file)[0]
    prefix_candidates = []

    for item in master_specs:
        old_source = item.get("pdf_source", "")
        if not old_source:
            continue
        if live_pdfs and old_source in live_pdfs:
            # Do not treat a still-live brochure as replaced by a sibling file
            continue
        old_path = os.path.join(auto_folder, old_source)

        # Tier 1 SHA-256 match across any non-live catalog item
        if os.path.exists(old_path):
            old_sha = compute_sha256(old_path)
            if new_sha and old_sha and new_sha == old_sha:
                return item, True, "100% Binary Match via Lineage SHA-256 (Filename/Date Changed)"
        elif item.get("pdf_sha256") and new_sha and new_sha == item.get("pdf_sha256"):
            return item, True, "100% Binary Match via Lineage Master Hash (Filename/Date Changed)"

        if new_prefix and extract_paired_brochure_key(old_source)[0] == new_prefix and os.path.exists(old_path):
            prefix_candidates.append(item)

    if prefix_candidates:
        prefix_candidates.sort(
            key=lambda x: extract_doc_date_sort_key(x.get("pdf_source", "")),
            reverse=True,
        )
        for item in prefix_candidates:
            old_source = item.get("pdf_source", "")
            old_path = os.path.join(auto_folder, old_source)
            print(f"[VERIFY] [{lang.upper()}] Lineage check '{new_file}' vs '{old_source}'...")
            if new_text_cache[0] is None:
                new_text_cache[0] = extract_normalized_text(new_path)
            old_text = extract_normalized_text(old_path)
            if new_text_cache[0] and old_text and new_text_cache[0] == old_text:
                return item, True, "100% Normalized Text Match via Series Lineage (Filename/Date Changed)"

    return None, False, ""


def verify_and_update(lang='th', dry_run=False):
    is_th = (lang.lower() == 'th')
    auto_folder = os.path.join(WORKSPACE_DIR, "bmw_brochures_auto" if is_th else "bmw_brochures_auto_en")
    master_file = os.path.join(WORKSPACE_DIR, "bmw_master_specs.json" if is_th else "bmw_master_specs_en.json")
    live_list_path = os.path.join(WORKSPACE_DIR, "scratch", "live_web_pdfs.txt")

    if not os.path.exists(master_file):
        print(f"[VERIFY] [{lang.upper()}] Master database not found: {master_file}")
        return 0

    if not os.path.exists(auto_folder):
        print(f"[VERIFY] [{lang.upper()}] Brochures folder not found: {auto_folder}")
        return 0

    with open(master_file, 'r', encoding='utf-8') as f:
        master_specs = json.load(f)

    if not isinstance(master_specs, list) or len(master_specs) == 0:
        print(f"[VERIFY] [{lang.upper()}] Master specs is empty.")
        return 0

    # Load live web PDFs list if available
    live_pdfs = set()
    if os.path.exists(live_list_path):
        try:
            with open(live_list_path, 'r', encoding='utf-8') as lf:
                live_pdfs = {line.strip() for line in lf if line.strip()}
        except Exception as e:
            print(f"[VERIFY] [WARNING] Could not read live_web_pdfs.txt: {e}")

    # Set of currently registered PDFs in master specs
    registered_pdfs = {item.get("pdf_source") for item in master_specs if item.get("pdf_source")}
    
    # PDFs physically present in folder
    local_files = set(os.listdir(auto_folder))
    
    # Candidates to verify: live PDFs (or local files) that are NOT registered in master specs
    candidates = []
    if live_pdfs:
        for f in live_pdfs:
            # Check if this live PDF belongs to this language folder
            if is_th and '_TH' in f and f not in registered_pdfs and f in local_files:
                candidates.append(f)
            elif (not is_th) and '_EN' in f and f not in registered_pdfs and f in local_files:
                candidates.append(f)
    else:
        for f in local_files:
            if f.lower().endswith('.pdf') and f not in registered_pdfs:
                candidates.append(f)

    if not candidates:
        print(f"[VERIFY] [{lang.upper()}] No unlinked live brochures found. Everything is up to date.")
        return 0

    print(f"\n[VERIFY] [{lang.upper()}] Checking {len(candidates)} unlinked candidate brochure(s)...")

    smart_skipped_count = 0
    modified = False

    for new_file in sorted(candidates):
        new_path = os.path.join(auto_folder, new_file)
        new_sha = compute_sha256(new_path)

        # Find matching series in master_specs (base-name first, then lineage SHA-256 / series-prefix text)
        matched_item, is_identical, match_reason = find_identical_master_entry(
            lang, new_file, new_path, new_sha, master_specs, auto_folder, live_pdfs=live_pdfs
        )

        if not matched_item:
            # No base name match and no identical lineage match -> genuine new brochure/model family
            print(f"[VERIFY] [{lang.upper()}] [NEW-MODEL] '{new_file}' has no prior brochure match. Will extract.")
            continue

        old_file = matched_item.get("pdf_source")
        old_path = os.path.join(auto_folder, old_file)
        series_name = matched_item.get("series", "Unknown Series")

        if is_identical:
            print(f"\n[SMART-SKIP] [{lang.upper()}] Case={STATUS_SMART_SKIPPED} | Series: {series_name}")
            print(f"  Old Brochure: {old_file}")
            print(f"  New Brochure: {new_file}")
            print(f"  Result: {match_reason}")
            print(f"  Action: Skipping AI extraction. Updating master specs reference.")

            if not dry_run:
                # Update master specs reference
                matched_item["pdf_source"] = new_file
                matched_item["source_file"] = new_file
                matched_item["pdf_sha256"] = new_sha
                
                # Delete obsolete old PDF to prevent repository bloat
                if os.path.exists(old_path) and old_file != new_file:
                    try:
                        os.remove(old_path)
                        print(f"  Cleaned up obsolete local PDF: {old_file}")
                    except Exception as e:
                        print(f"  [WARNING] Could not delete obsolete {old_file}: {e}")

                modified = True
            smart_skipped_count += 1
        else:
            print(f"\n[GENUINE-UPDATE] [{lang.upper()}] Series: {series_name}")
            print(f"  New Brochure '{new_file}' has genuine specification changes. Queuing for AI extraction.")

    if modified and not dry_run:
        with open(master_file, 'w', encoding='utf-8') as f:
            json.dump(master_specs, f, ensure_ascii=False, indent=2)
        print(f"\n[VERIFY] [{lang.upper()}] Successfully updated master specs file: {os.path.basename(master_file)}")

    print(f"[VERIFY] [{lang.upper()}] Complete. Smart-skipped {smart_skipped_count} identical brochure(s).")
    return smart_skipped_count

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Verify BMW PDF brochure content changes before extraction")
    parser.add_argument("--lang", choices=["th", "en", "all"], default="all", help="Language to verify")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without writing files")
    args = parser.parse_args()

    total_skipped = 0
    if args.lang in ["th", "all"]:
        total_skipped += verify_and_update(lang="th", dry_run=args.dry_run)
    if args.lang in ["en", "all"]:
        total_skipped += verify_and_update(lang="en", dry_run=args.dry_run)

    print(f"\n[VERIFY] Total identical brochures smart-skipped: {total_skipped}")

if __name__ == "__main__":
    main()
