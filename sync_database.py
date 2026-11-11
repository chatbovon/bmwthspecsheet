import os
import json
import sys

# Reconfigure stdout/stderr to utf-8 for Windows console
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# Folders to scan
DIR_AUTO = "bmw_brochures_auto"
DIR_AUTO_EN = "bmw_brochures_auto_en"
DIR_CUSTOM = "bmw_brochures_custom"
DIR_CUSTOM_EN = "bmw_brochures_custom_en"

# Database paths
DB_TH_PATH = "bmw_master_specs.json"
DB_EN_PATH = "bmw_master_specs_en.json"
MIN_HEALTHY_WEB_PER_LANG = 5

def get_pdf_prefix(filename):
    """
    Extracts the base prefix of a PDF filename to check for existence on disk.
    Example: 'i5-20260714-01_TH.pdf.asset.1784613825396.pdf' -> 'i5-20260714-01'
    """
    if not filename:
        return ""
    name = filename.lower().strip()
    name = name.split(".pdf")[0]
    name = name.split(".asset")[0]
    # Remove language markers
    if "_th_" in name:
        name = name.split("_th_")[0]
    elif "_th" in name:
        name = name.split("_th")[0]
    if "_en_" in name:
        name = name.split("_en_")[0]
    elif "_en" in name:
        name = name.split("_en")[0]
    return name.strip()

def scan_prefixes(folder_path):
    if not os.path.exists(folder_path):
        return set()
    return set(get_pdf_prefix(f) for f in os.listdir(folder_path) if f.lower().endswith(".pdf"))

def load_live_web_prefixes(live_list_path, min_per_lang=MIN_HEALTHY_WEB_PER_LANG):
    """
    Loads active prefixes from scratch/live_web_pdfs.txt only when both
    TH and EN targets meet the minimum healthy threshold.
    """
    if not os.path.exists(live_list_path):
        return set(), False
    try:
        with open(live_list_path, "r", encoding="utf-8") as f:
            filenames = [line.strip() for line in f if line.strip().lower().endswith(".pdf")]
    except Exception as e:
        print(f"[WARNING] Failed to read {live_list_path}: {e}")
        return set(), False

    th_count = sum(1 for name in filenames if "_th" in name.lower())
    en_count = sum(1 for name in filenames if "_en" in name.lower())
    if th_count < min_per_lang or en_count < min_per_lang:
        print(f"[CIRCUIT BREAKER] Incomplete live_web_pdfs.txt (TH={th_count}, EN={en_count}). Ignoring live web list.")
        return set(), False

    prefixes = {get_pdf_prefix(name) for name in filenames if get_pdf_prefix(name)}
    return prefixes, True

def sync_database(db_path, active_prefixes, custom_prefixes, name_label="TH"):
    if not os.path.exists(db_path):
        print(f"[ERROR] Database file {db_path} not found.")
        return

    with open(db_path, "r", encoding="utf-8") as f:
        catalog = json.load(f)

    if not isinstance(catalog, list):
        print(f"[ERROR] Database {db_path} is not a JSON list.")
        return

    clean_catalog = []
    preserved_count = 0
    archived_count = 0
    active_count = 0

    for entry in catalog:
        pdf_source = entry.get("pdf_source") or entry.get("source_file", "")
        prefix = get_pdf_prefix(pdf_source)

        if not prefix:
            # Keep entries with no PDF source (just in case)
            clean_catalog.append(entry)
            continue

        if prefix in active_prefixes:
            # Active brochure (on local auto folder or confirmed live on BMW website)
            for model in entry.get("models", []):
                model["is_custom_archived"] = False
            clean_catalog.append(entry)
            active_count += len(entry.get("models", []))
        elif prefix in custom_prefixes:
            # Custom / Archived brochure explicitly stored in DIR_CUSTOM* on disk
            for model in entry.get("models", []):
                model["is_custom_archived"] = True
            clean_catalog.append(entry)
            archived_count += len(entry.get("models", []))
        else:
            # PDF not present on disk (e.g. .gitignored GDrive brochure or incomplete scrape);
            # preserve existing is_custom_archived status instead of falsely archiving active models.
            clean_catalog.append(entry)
            preserved_count += len(entry.get("models", []))

    # Save cleaned database
    with open(db_path, "w", encoding="utf-8") as f:
        json.dump(clean_catalog, f, ensure_ascii=False, indent=4)

    print(f"[COMPLETE] Database {db_path} synchronized:")
    print(f"  - Active models: {active_count}")
    print(f"  - Archived models (custom folder): {archived_count}")
    print(f"  - Preserved models (missing local PDF): {preserved_count}")

def main():
    print("=== STARTING DATABASE SYNCHRONIZATION AND PRUNING ===")

    # 1. Scan folders and verified live web list for prefixes
    auto_prefixes = scan_prefixes(DIR_AUTO).union(scan_prefixes(DIR_AUTO_EN))
    custom_prefixes = scan_prefixes(DIR_CUSTOM).union(scan_prefixes(DIR_CUSTOM_EN))
    live_list_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scratch", "live_web_pdfs.txt")
    live_prefixes, live_healthy = load_live_web_prefixes(live_list_path)
    active_prefixes = auto_prefixes.union(live_prefixes)

    print("Scanned prefixes:")
    print(f"  - Active folder prefixes: {len(auto_prefixes)}")
    print(f"  - Live web prefixes (healthy={live_healthy}): {len(live_prefixes)}")
    print(f"  - Active combined prefixes: {len(active_prefixes)}")
    print(f"  - Custom folder prefixes: {len(custom_prefixes)}")

    if len(active_prefixes) < MIN_HEALTHY_WEB_PER_LANG:
        print(f"[CIRCUIT BREAKER] Active prefixes count ({len(active_prefixes)}) is too low (< {MIN_HEALTHY_WEB_PER_LANG}). Aborting database sync.")
        return

    # 2. Sync TH database
    sync_database(DB_TH_PATH, active_prefixes, custom_prefixes, "TH")

    # 3. Sync EN database
    sync_database(DB_EN_PATH, active_prefixes, custom_prefixes, "EN")

if __name__ == "__main__":
    main()
