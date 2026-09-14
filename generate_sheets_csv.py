import os
import sys
import json
import csv
import hashlib
import argparse
from datetime import datetime, timezone, timedelta

# Fix Windows console encoding for Thai characters
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_BASE_DIR = os.path.join(BASE_DIR, "csv")
HASH_FILE = os.path.join(BASE_DIR, ".csv_build_hash")
GUIDE_FILE = os.path.join(BASE_DIR, "google_sheets_formulas.md")
BASE_URL = "https://chatbovon.github.io/bmwthspecsheet/csv"

DATASETS = [
    {
        "id": "master_th",
        "title": "รุ่นปัจจุบัน (Active Models) - ภาษาไทย",
        "json_path": os.path.join(BASE_DIR, "bmw_master_specs.json"),
        "csv_subfolder": "master/th",
        "lang": "th",
        "type": "master"
    },
    {
        "id": "master_en",
        "title": "Active Models - English",
        "json_path": os.path.join(BASE_DIR, "bmw_master_specs_en.json"),
        "csv_subfolder": "master/en",
        "lang": "en",
        "type": "master"
    },
    {
        "id": "custom_th",
        "title": "รุ่นคัสตอม / ยกเลิกจำหน่าย (Custom & Archived) - ภาษาไทย",
        "json_path": os.path.join(BASE_DIR, "bmw_custom_specs.json"),
        "csv_subfolder": "custom/th",
        "lang": "th",
        "type": "custom"
    },
    {
        "id": "custom_en",
        "title": "Custom & Archived Models - English",
        "json_path": os.path.join(BASE_DIR, "bmw_custom_specs_en.json"),
        "csv_subfolder": "custom/en",
        "lang": "en",
        "type": "custom"
    }
]

def compute_datasets_hash() -> str:
    """Computes combined MD5 hash of all specification JSON files."""
    hasher = hashlib.md5()
    for ds in DATASETS:
        path = ds["json_path"]
        if os.path.exists(path):
            with open(path, "rb") as f:
                while chunk := f.read(65536):
                    hasher.update(chunk)
        else:
            hasher.update(b"NOT_FOUND")
    return hasher.hexdigest()

def clean_pdf_slug(filename: str) -> str:
    """Creates a URL-safe, clean filename for the CSV file."""
    name = filename.strip()
    if name.lower().endswith(".pdf"):
        name = name[:-4]
    for ch in [" ", "-", "(", ")", "[", "]", "@", "+"]:
        name = name.replace(ch, "_")
    while "__" in name:
        name = name.replace("__", "_")
    return name.strip("_").lower()

def generate_matrix_csv_for_brochure(brochure_entry: dict, out_csv_path: str):
    """Converts a brochure JSON entry into a Matrix View CSV file."""
    models = brochure_entry.get("models", [])
    if not models:
        return 0

    model_names = [m.get("model_name", f"Model {i+1}") for i, m in enumerate(models)]
    header = ["Category", "Topic"] + model_names

    # Collect ordered categories and topics preserving brochure visual order
    categories_order = []
    category_topics_map = {}
    model_values_map = [{} for _ in models]

    for model_idx, model in enumerate(models):
        for cat_item in model.get("specifications", []):
            cat_name = cat_item.get("category", "General Specifications").strip()
            if cat_name not in categories_order:
                categories_order.append(cat_name)
                category_topics_map[cat_name] = []

            for detail in cat_item.get("details", []):
                topic = detail.get("topic", "").strip()
                val = detail.get("value", "")
                if topic not in category_topics_map[cat_name]:
                    category_topics_map[cat_name].append(topic)
                model_values_map[model_idx][(cat_name, topic)] = val

    rows = [header]
    for cat_name in categories_order:
        topics = category_topics_map.get(cat_name, [])
        for topic in topics:
            row = [cat_name, topic]
            for model_idx in range(len(models)):
                val = model_values_map[model_idx].get((cat_name, topic), "-")
                if val is None or str(val).strip() == "":
                    val = "-"
                row.append(str(val))
            rows.append(row)

    os.makedirs(os.path.dirname(out_csv_path), exist_ok=True)
    with open(out_csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        writer.writerows(rows)

    return len(rows) - 1  # Return topic rows count

def build_all_sheets_csv(force: bool = False):
    current_hash = compute_datasets_hash()
    
    if not force and os.path.exists(HASH_FILE):
        with open(HASH_FILE, "r", encoding="utf-8") as f:
            saved_hash = f.read().strip()
        if saved_hash == current_hash and os.path.exists(CSV_BASE_DIR):
            print("[SKIP] No changes detected in JSON spec databases. CSV generation skipped.")
            return

    print("=== STARTING GOOGLE SHEETS CSV GENERATOR ===")
    
    guide_sections = []
    total_csv_files = 0

    tz_ict = timezone(timedelta(hours=7))
    now_ict = datetime.now(tz_ict).strftime("%Y-%m-%d %H:%M:%S ICT (UTC+7)")

    for ds in DATASETS:
        json_path = ds["json_path"]
        if not os.path.exists(json_path):
            print(f"[WARNING] Skipping missing dataset: {json_path}")
            continue

        with open(json_path, "r", encoding="utf-8") as f:
            catalog = json.load(f)

        if not isinstance(catalog, list):
            print(f"[ERROR] Invalid format in {json_path}")
            continue

        target_folder = os.path.join(CSV_BASE_DIR, ds["csv_subfolder"])
        os.makedirs(target_folder, exist_ok=True)

        section_entries = []
        dataset_csv_count = 0

        for entry in catalog:
            series_name = entry.get("series", "Unknown Series")
            pdf_source = entry.get("pdf_source", entry.get("source_file", "unknown"))
            models = entry.get("models", [])
            if not models:
                continue

            slug = clean_pdf_slug(pdf_source)
            csv_filename = f"{slug}.csv"
            csv_path = os.path.join(target_folder, csv_filename)

            topics_count = generate_matrix_csv_for_brochure(entry, csv_path)
            dataset_csv_count += 1
            total_csv_files += 1

            # Generate clean short tab name
            if len(models) == 1:
                tname = models[0].get("model_name", series_name)
            else:
                clean_m = [m.get("model_name", "").replace("BMW ", "").strip() for m in models]
                tname = f"{series_name} ({', '.join(clean_m)})"

            tname = tname.replace("BMW ", "").strip()
            if len(tname) > 35:
                tname = tname[:32] + "..."

            if ds["type"] == "custom":
                tab_prefix = "[Archived EN] " if ds["lang"] == "en" else "[Archived TH] "
            else:
                tab_prefix = "[EN] " if ds["lang"] == "en" else ""
            full_tab_name = f"{tab_prefix}{tname}"

            relative_url = f"{BASE_URL}/{ds['csv_subfolder']}/{csv_filename}"
            formula = f'=IMPORTDATA("{relative_url}")'
            models_display = ", ".join(m.get("model_name", "") for m in models)

            section_entries.append({
                "tab_name": full_tab_name,
                "series": series_name,
                "pdf_source": pdf_source,
                "models": models_display,
                "models_count": len(models),
                "topics_count": topics_count,
                "formula": formula,
                "csv_url": relative_url
            })

        guide_sections.append({
            "id": ds["id"],
            "title": ds["title"],
            "entries": section_entries,
            "count": dataset_csv_count
        })
        print(f"[SUCCESS] Generated {dataset_csv_count} CSV files in '{ds['csv_subfolder']}'")

    # Generate csv/manifest.json for 100% automated dynamic syncing in Google Sheets
    manifest_path = os.path.join(CSV_BASE_DIR, "manifest.json")
    manifest_data = {
        "generated_at": now_ict,
        "base_url": BASE_URL,
        "total_brochures": total_csv_files,
        "datasets": {sec["id"]: sec["entries"] for sec in guide_sections}
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, ensure_ascii=False, indent=2)
    print(f"[MANIFEST] Generated live catalog index at '{manifest_path}'")

    # Generate google_sheets_formulas.md
    with open(GUIDE_FILE, "w", encoding="utf-8") as f:
        f.write("# 📊 BMW Specsheet - Google Sheets Live Sync Guide (`=IMPORTDATA`)\n\n")
        f.write(f"> 🕒 **Last Generated:** `{now_ict}`  \n")
        f.write("> 💡 **วิธีใช้งาน:** ใน Google Sheets ของคุณ ให้สร้างแท็บใหม่ (Sheet Tab) แล้วคัดลอกสูตร `=IMPORTDATA(...)` ในตารางด้านล่างไปวางใน **ช่อง A1** ข้อมูลสเปกแบบ Matrix View จะถูกโหลดและอัปเดตแบบ Real-time ตามฐานข้อมูลล่าสุดโดยอัตโนมัติ!\n\n")
        f.write("---\n\n")

        for sec in guide_sections:
            f.write(f"## {sec['title']} ({sec['count']} เล่ม/แท็บ)\n\n")
            f.write("| ซีรีส์ / โบรชัวร์ (Series) | รุ่นรถยนต์ (Models) | จำนวนหัวข้อ | สูตรสำหรับ Google Sheets (วางช่อง A1) |\n")
            f.write("| :--- | :--- | :---: | :--- |\n")
            for item in sec["entries"]:
                f.write(f"| **{item['series']}**<br><sub>`{item['pdf_source']}`</sub> | {item['models']} | {item['topics_count']} | `{item['formula']}` |\n")
            f.write("\n---\n\n")

    # Save hash
    with open(HASH_FILE, "w", encoding="utf-8") as f:
        f.write(current_hash)

    print(f"\n[COMPLETE] Successfully generated {total_csv_files} CSV matrix files!")
    print(f"[GUIDE] Quick-copy formulas guide saved to: '{GUIDE_FILE}'")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Google Sheets matrix-view CSV files from BMW JSON specs.")
    parser.add_argument("--force", action="store_true", help="Force regenerate CSV files regardless of hash.")
    args = parser.parse_args()
    build_all_sheets_csv(force=args.force)

