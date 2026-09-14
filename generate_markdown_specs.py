import os
import sys
import json
from datetime import datetime, timezone, timedelta

# Fix Windows console encoding for Thai characters
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_TH_PATH = os.path.join(BASE_DIR, "bmw_master_specs.json")
DB_EN_PATH = os.path.join(BASE_DIR, "bmw_master_specs_en.json")
OUT_TH_PATH = os.path.join(BASE_DIR, "specs_all.md")
OUT_EN_PATH = os.path.join(BASE_DIR, "specs_all_en.md")

def format_value(val: str, lang: str = "th") -> str:
    if not val:
        return "- (ไม่มีการติดตั้ง / Not Available)" if lang == "th" else "- (Not Available)"
    val_clean = str(val).strip()
    if val_clean == "■":
        return "■ (มีติดตั้งเป็นมาตรฐาน / Standard)" if lang == "th" else "■ (Standard Equipment)"
    if val_clean in ("-", "no", "not available"):
        return "- (ไม่มีการติดตั้ง / Not Available)" if lang == "th" else "- (Not Available)"
    return val_clean

def slugify(text: str) -> str:
    """Generate simple GitHub Markdown anchor slug."""
    text = text.lower().strip()
    for ch in ['/', '\\', '(', ')', '[', ']', ':', ';', ',', '.', "'", '"']:
        text = text.replace(ch, '')
    text = text.replace(' ', '-')
    while '--' in text:
        text = text.replace('--', '-')
    return text.strip('-')

def generate_markdown(db_path: str, out_path: str, lang: str = "th"):
    if not os.path.exists(db_path):
        print(f"[ERROR] Database file not found: {db_path}")
        return

    with open(db_path, "r", encoding="utf-8") as f:
        catalog = json.load(f)

    if not isinstance(catalog, list):
        print(f"[ERROR] Catalog format invalid in: {db_path}")
        return

    # Calculate timestamps (Bangkok ICT UTC+7)
    tz_ict = timezone(timedelta(hours=7))
    now_ict = datetime.now(tz_ict).strftime("%Y-%m-%d %H:%M:%S ICT (UTC+7)")

    total_series = len(catalog)
    total_models = sum(len(entry.get("models", [])) for entry in catalog)

    lines = []
    
    # Title & Metadata
    if lang == "th":
        lines.append("# ข้อมูลสเปกรถยนต์ BMW ประเทศไทย (Official Technical Specifications)")
        lines.append(f"> **อัปเดตล่าสุดเมื่อ:** {now_ict}")
        lines.append(f"> **ขอบเขตข้อมูล:** ครอบคลุม {total_series} ซีรีส์ รวมทั้งหมด {total_models} รุ่นย่อย")
        lines.append("> **แหล่งอ้างอิง:** โบรชัวร์ทางการจาก BMW Thailand สกัดและจัดระเบียบโครงสร้างด้วย BMW Dynamic Specsheet\n")
        lines.append("## สารบัญรุ่นรถทั้งหมด (Table of Contents)\n")
    else:
        lines.append("# BMW Thailand Official Technical Specifications & Features Catalog")
        lines.append(f"> **Last Updated:** {now_ict}")
        lines.append(f"> **Coverage:** {total_series} Series, {total_models} Models")
        lines.append("> **Source:** Official BMW Thailand Brochures, parsed and structured via BMW Dynamic Specsheet\n")
        lines.append("## Table of Contents\n")

    # Table of Contents
    for entry in catalog:
        series_name = entry.get("series", "").strip() or "BMW Series"
        series_slug = slugify(series_name)
        lines.append(f"- [{series_name}](#{series_slug})")
        for model in entry.get("models", []):
            mname = model.get("model_name", "").strip()
            if mname:
                model_slug = slugify(mname)
                lines.append(f"  - [{mname}](#{model_slug})")
    lines.append("\n---\n")

    # Content per Series & Model
    for entry in catalog:
        series_name = entry.get("series", "").strip() or "BMW Series"
        lines.append(f"# {series_name}\n")
        
        pdf_source = entry.get("pdf_source") or entry.get("source_file", "")

        for model in entry.get("models", []):
            mname = model.get("model_name", "").strip()
            is_archived = model.get("is_custom_archived", False)
            
            lines.append(f"## {mname}")
            
            if lang == "th":
                status_text = "โบรชัวร์รุ่นเดิม (Archived / Custom)" if is_archived else "รุ่นปัจจุบัน (Active)"
                lines.append(f"- **สถานะโมเดล:** {status_text}")
                if pdf_source:
                    lines.append(f"- **เอกสารโบรชัวร์อ้างอิง:** `{pdf_source}`")
            else:
                status_text = "Archived / Custom Brochure" if is_archived else "Active Brochure"
                lines.append(f"- **Model Status:** {status_text}")
                if pdf_source:
                    lines.append(f"- **Source Brochure:** `{pdf_source}`")
            lines.append("")

            # Categories and Details
            for spec in model.get("specifications", []):
                cat_name = spec.get("category", "").strip()
                if not cat_name:
                    continue
                
                lines.append(f"### {cat_name}")
                
                details = spec.get("details", [])
                if not details:
                    lines.append("- *(ไม่มีข้อมูลย่อย / No sub-details)*")
                    lines.append("")
                    continue

                for detail in details:
                    topic = detail.get("topic", "").strip()
                    raw_val = detail.get("value", "")
                    clean_val = format_value(raw_val, lang=lang)
                    
                    if not topic:
                        continue
                        
                    lines.append(f"- **{topic}:** {clean_val}")
                lines.append("")
            
            lines.append("---\n")

    content = "\n".join(lines)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)

    # Also save .txt version for AI web readers that only fetch text files
    txt_path = out_path.rsplit(".", 1)[0] + ".txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(content)

    file_size_kb = os.path.getsize(out_path) / 1024
    print(f"[COMPLETE] Generated {out_path} & {txt_path} ({file_size_kb:.1f} KB, {total_models} models)")

def main():
    print("=== STARTING MARKDOWN SPECIFICATION EXPORT ===")
    print(f"Exporting Thai specifications to: {OUT_TH_PATH}")
    generate_markdown(DB_TH_PATH, OUT_TH_PATH, lang="th")
    
    print(f"\nExporting English specifications to: {OUT_EN_PATH}")
    generate_markdown(DB_EN_PATH, OUT_EN_PATH, lang="en")
    print("\n=== MARKDOWN SPECIFICATION EXPORT COMPLETED ===")

if __name__ == "__main__":
    main()
