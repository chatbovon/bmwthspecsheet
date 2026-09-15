import os
import sys
import json
import re
from datetime import datetime, timezone, timedelta

# Fix Windows console encoding for Thai characters
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

WORKTREE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_TH_PATH = os.path.join(WORKTREE_DIR, "bmw_master_specs.json")
DB_EN_PATH = os.path.join(WORKTREE_DIR, "bmw_master_specs_en.json")
DOSSIER_DIR = os.path.join(WORKTREE_DIR, "dossier")

def sanitize_filename(name: str) -> str:
    """Sanitize model name to valid filename."""
    name = re.sub(r'[/\\:*?"<>|]', '_', name)
    name = name.replace(' ', '_').replace('__', '_').strip('_')
    return name

def format_value(val: str, lang: str = "th") -> str:
    if not val:
        return "[ไม่มีการติดตั้ง / Not Available]" if lang == "th" else "[Not Available]"
    val_clean = str(val).strip()
    if val_clean == "■":
        return "[ติดตั้งเป็นมาตรฐาน / Standard]" if lang == "th" else "[Standard Equipment]"
    if val_clean in ("-", "no", "not available"):
        return "[ไม่มีการติดตั้ง / Not Available]" if lang == "th" else "[Not Available]"
    return val_clean

def get_powertrain_type(mname: str, spec_list: list, lang: str = "th") -> str:
    mname_lower = mname.lower()
    # Check for BEV
    if mname_lower.startswith('i') or ' edrive' in mname_lower or ' xdrive' in mname_lower and mname_lower.startswith('i'):
        return "รถยนต์ไฟฟ้า 100% (Battery Electric Vehicle - BEV)" if lang == "th" else "Pure Electric (Battery Electric Vehicle - BEV)"
    # Check for PHEV
    if 'e ' in mname_lower or mname_lower.endswith('e') or '530e' in mname_lower or '330e' in mname_lower or '750e' in mname_lower or 'm760e' in mname_lower or '50e' in mname_lower or 'xm' in mname_lower:
        return "ปลั๊กอินไฮบริด (Plug-in Hybrid - PHEV)" if lang == "th" else "Plug-in Hybrid Electric Vehicle (PHEV)"
    # Check Diesel
    if 'd ' in mname_lower or mname_lower.endswith('d') or '20d' in mname_lower or '30d' in mname_lower or '40d' in mname_lower:
        return "เครื่องยนต์ดีเซล (Diesel TwinPower Turbo)" if lang == "th" else "Diesel (TwinPower Turbo)"
    # Default Petrol
    return "เครื่องยนต์เบนซิน (Petrol TwinPower Turbo)" if lang == "th" else "Petrol (TwinPower Turbo)"

def generate_model_markdown(series_name: str, model_data: dict, pdf_source: str, lang: str = "th") -> str:
    mname = model_data.get("model_name", "").strip()
    is_archived = model_data.get("is_custom_archived", False)
    powertrain = get_powertrain_type(mname, model_data.get("specifications", []), lang=lang)
    
    lines = []
    
    # Header & Dossier Metadata
    lines.append(f"# {mname} - BMW Model Technical Dossier")
    if lang == "th":
        status_text = "โบรชัวร์รุ่นเดิม (Custom/Archived)" if is_archived else "รุ่นจำหน่ายปัจจุบัน (Active Catalog)"
        lines.append(f"> **ซีรีส์หลัก:** {series_name}")
        lines.append(f"> **ประเภทระบบขับเคลื่อน:** {powertrain}")
        lines.append(f"> **สถานะการทำตลาด:** {status_text}")
        if pdf_source:
            lines.append(f"> **เอกสารโบรชัวร์อ้างอิง:** `{pdf_source}`")
    else:
        status_text = "Archived / Custom Brochure" if is_archived else "Active Official Brochure"
        lines.append(f"> **Main Series:** {series_name}")
        lines.append(f"> **Powertrain Category:** {powertrain}")
        lines.append(f"> **Market Status:** {status_text}")
        if pdf_source:
            lines.append(f"> **Source Brochure PDF:** `{pdf_source}`")
    
    lines.append("\n---\n")

    # Specifications by category
    cat_idx = 1
    for spec in model_data.get("specifications", []):
        cat_name = spec.get("category", "").strip()
        if not cat_name or cat_name in ("หมายเหตุ", "Notes"):
            continue
            
        lines.append(f"## {cat_idx}. {cat_name}")
        cat_idx += 1
        
        details = spec.get("details", [])
        if not details:
            lines.append(f"- [{mname}] *(ไม่มีข้อมูลจำเพาะย่อย / No sub-details)*")
            lines.append("")
            continue
            
        for d in details:
            topic = d.get("topic", "").strip()
            val = format_value(d.get("value", ""), lang=lang)
            if not topic:
                continue
            # Self-contained format: [MODEL NAME] - Topic: Value
            lines.append(f"- **[{mname}]** - {topic}: {val}")
        lines.append("")

    # Paintwork & Upholstery section if exists
    paintwork_data = model_data.get("paintwork_and_upholstery", {}) or model_data.get("color_options", {})
    if paintwork_data:
        section_title = "สีตัวถังและวัสดุตกแต่งภายใน (Paintwork & Upholstery Combinations)" if lang == "th" else "Paintwork & Interior Upholstery Combinations"
        lines.append(f"## {cat_idx}. {section_title}")
        cat_idx += 1
        for color, interiors in paintwork_data.items():
            if isinstance(interiors, list):
                interiors_str = ", ".join(interiors)
            else:
                interiors_str = str(interiors)
            lines.append(f"- **[{mname}] - สีภายนอก {color}:** จับคู่กับภายใน `{interiors_str}`")
        lines.append("")

    # Legal Notes section if exists
    notes_spec = next((c for c in model_data.get("specifications", []) if (c.get("category") or "").strip() in ("หมายเหตุ", "Notes")), None)
    if notes_spec and notes_spec.get("details"):
        notes_title = "ข้อกำหนดและหมายเหตุทางการ (Official Notes & Terms)" if lang == "th" else "Official Notes & Terms"
        lines.append(f"## {notes_title}")
        for note in notes_spec.get("details", []):
            topic = note.get("topic", "").strip()
            if topic:
                lines.append(f"> * {topic}")
        lines.append("")

    return "\n".join(lines)

def build_dossiers(db_path: str, lang: str = "th"):
    if not os.path.exists(db_path):
        print(f"[ERROR] DB not found: {db_path}")
        return

    with open(db_path, "r", encoding="utf-8") as f:
        catalog = json.load(f)

    lang_dir = os.path.join(DOSSIER_DIR, lang)
    models_dir = os.path.join(lang_dir, "models")
    os.makedirs(models_dir, exist_ok=True)

    tz_ict = timezone(timedelta(hours=7))
    now_ict = datetime.now(tz_ict).strftime("%Y-%m-%d %H:%M:%S ICT (UTC+7)")

    # Group collections
    groups = {
        "BMW_Sedans_Dossier": [],
        "BMW_X_Family_Dossier": [],
        "BMW_i_Electric_Dossier": [],
        "BMW_M_High_Performance_Dossier": []
    }

    all_model_entries = []

    for entry in catalog:
        sname = entry.get("series", "").strip()
        pdf_source = entry.get("pdf_source") or entry.get("source_file", "")
        
        for model in entry.get("models", []):
            mname = model.get("model_name", "").strip()
            if not mname:
                continue
                
            model_md = generate_model_markdown(sname, model, pdf_source, lang=lang)
            
            # Save individual dossier file
            fname = sanitize_filename(mname) + ".md"
            fpath = os.path.join(models_dir, fname)
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(model_md)
                
            all_model_entries.append((sname, mname, model_md))

            # Classify into groups
            m_lower = mname.lower()
            s_lower = sname.lower()

            # 1. Sedans & Coupes
            if any(k in s_lower for k in ['2 series', '3 series', '4 series', '5 series', '7 series', 'z4']):
                groups["BMW_Sedans_Dossier"].append((mname, model_md))
            
            # 2. X Family
            if any(k in s_lower for k in ['x1', 'x2', 'x3', 'x4', 'x5', 'x6', 'x7', 'xm', 'ix', 'ix1', 'ix2', 'ix3']) or m_lower.startswith('x'):
                groups["BMW_X_Family_Dossier"].append((mname, model_md))

            # 3. i Electric
            if m_lower.startswith('i') or 'ix' in m_lower or 'edrive' in m_lower:
                groups["BMW_i_Electric_Dossier"].append((mname, model_md))

            # 4. M High Performance
            if any(k in s_lower for k in ['m2', 'm3', 'm4', 'm5', 'xm']) or 'competition' in m_lower or ' cs' in m_lower or m_lower.startswith('m'):
                groups["BMW_M_High_Performance_Dossier"].append((mname, model_md))

    # Write grouped dossiers
    for gname, model_list in groups.items():
        gpath = os.path.join(lang_dir, f"{gname}.md")
        glines = []
        
        # Group Header
        if lang == "th":
            glines.append(f"# {gname.replace('_', ' ')} - แฟ้มข้อมูลสเปกฉบับรวม")
            glines.append(f"> **อัปเดตล่าสุด:** {now_ict} | จำนวนรุ่นในเล่มนี้: {len(model_list)} รุ่น")
            glines.append("> **รูปแบบ:** Self-Contained Model Dossiers สำหรับ NotebookLM และ AI RAG\n")
            glines.append("## สารบัญรุ่นรถในเล่มนี้\n")
        else:
            glines.append(f"# {gname.replace('_', ' ')} - Comprehensive Technical Dossier")
            glines.append(f"> **Last Updated:** {now_ict} | Total Models Included: {len(model_list)}")
            glines.append("> **Format:** Self-Contained Model Dossiers for NotebookLM & AI RAG\n")
            glines.append("## Table of Contents\n")

        for mname, _ in model_list:
            glines.append(f"- [{mname}](#{sanitize_filename(mname).lower()})")
        glines.append("\n---\n")

        for _, model_md in model_list:
            glines.append(model_md)
            glines.append("\n\n================================================================================\n\n")

        with open(gpath, "w", encoding="utf-8") as f:
            f.write("\n".join(glines))

        gsize_kb = os.path.getsize(gpath) / 1024
        print(f"[GROUP] Generated {gpath} ({gsize_kb:.1f} KB, {len(model_list)} models)")

    print(f"[COMPLETE] Built {len(all_model_entries)} individual model dossiers in {models_dir}")

def main():
    print("=== STARTING MODEL DOSSIER GENERATION ===")
    print("\n--- Generating Thai Model Dossiers ---")
    build_dossiers(DB_TH_PATH, lang="th")
    
    print("\n--- Generating English Model Dossiers ---")
    build_dossiers(DB_EN_PATH, lang="en")
    print("\n=== MODEL DOSSIER GENERATION FINISHED ===")

if __name__ == "__main__":
    main()
