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

def sync_database(db_path, auto_prefixes, custom_prefixes, name_label="TH"):
    if not os.path.exists(db_path):
        print(f"[ERROR] Database file {db_path} not found.")
        return

    with open(db_path, "r", encoding="utf-8") as f:
        catalog = json.load(f)

    if not isinstance(catalog, list):
        print(f"[ERROR] Database {db_path} is not a JSON list.")
        return

    clean_catalog = []
    pruned_count = 0
    archived_count = 0
    active_count = 0

    for entry in catalog:
        pdf_source = entry.get("pdf_source") or entry.get("source_file", "")
        prefix = get_pdf_prefix(pdf_source)

        if not prefix:
            # Keep entries with no PDF source (just in case)
            clean_catalog.append(entry)
            continue

        if prefix in auto_prefixes:
            # Active brochure
            for model in entry.get("models", []):
                model["is_custom_archived"] = False
            clean_catalog.append(entry)
            active_count += len(entry.get("models", []))
        else:
            # Custom / Archived brochure (either in custom folder or completely missing from disk)
            for model in entry.get("models", []):
                model["is_custom_archived"] = True
            clean_catalog.append(entry)
            archived_count += len(entry.get("models", []))
            if prefix not in custom_prefixes:
                pruned_count += 1 # Track as archived from missing files

    # Save cleaned database
    with open(db_path, "w", encoding="utf-8") as f:
        json.dump(clean_catalog, f, ensure_ascii=False, indent=4)

    print(f"[COMPLETE] Database {db_path} synchronized:")
    print(f"  - Active models: {active_count}")
    print(f"  - Archived models (custom/missing): {archived_count} (of which {pruned_count} had missing PDF files)")

def main():
    print("=== STARTING DATABASE SYNCHRONIZATION AND PRUNING ===")
    
    # 1. Scan folders for prefixes
    auto_prefixes = scan_prefixes(DIR_AUTO).union(scan_prefixes(DIR_AUTO_EN))
    custom_prefixes = scan_prefixes(DIR_CUSTOM).union(scan_prefixes(DIR_CUSTOM_EN))
    
    print(f"Scanned disk prefixes:")
    print(f"  - Active folder prefixes: {len(auto_prefixes)}")
    print(f"  - Custom folder prefixes: {len(custom_prefixes)}")

    # 2. Sync TH database
    sync_database(DB_TH_PATH, auto_prefixes, custom_prefixes, "TH")
    
    # 3. Sync EN database
    sync_database(DB_EN_PATH, auto_prefixes, custom_prefixes, "EN")

if __name__ == "__main__":
    main()
