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
    if mname_lower.startswith('i') or ' edrive' in mname_lower or ' xdrive' in mname_lower and mname_lower.startswith('i'):
        return "รถยนต์ไฟฟ้า 100% (Battery Electric Vehicle - BEV)" if lang == "th" else "Pure Electric (Battery Electric Vehicle - BEV)"
    if 'e ' in mname_lower or mname_lower.endswith('e') or '530e' in mname_lower or '330e' in mname_lower or '750e' in mname_lower or 'm760e' in mname_lower or '50e' in mname_lower or 'xm' in mname_lower:
        return "ปลั๊กอินไฮบริด (Plug-in Hybrid - PHEV)" if lang == "th" else "Plug-in Hybrid Electric Vehicle (PHEV)"
    if 'd ' in mname_lower or mname_lower.endswith('d') or '20d' in mname_lower or '30d' in mname_lower or '40d' in mname_lower:
        return "เครื่องยนต์ดีเซล (Diesel TwinPower Turbo)" if lang == "th" else "Diesel (TwinPower Turbo)"
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

def convert_markdown_to_html(md_text: str, title: str, lang: str = "th") -> str:
    html_lines = []
    html_lines.append("<!DOCTYPE html>")
    html_lines.append(f'<html lang="{lang}">')
    html_lines.append("<head>")
    html_lines.append('    <meta charset="UTF-8">')
    html_lines.append('    <meta name="viewport" content="width=device-width, initial-scale=1.0">')
    html_lines.append(f'    <title>{title}</title>')
    html_lines.append("    <style>")
    html_lines.append("        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; line-height: 1.6; color: #1e293b; max-width: 900px; margin: 0 auto; padding: 24px; background: #f8fafc; }")
    html_lines.append("        .card { background: #ffffff; padding: 36px; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); margin-bottom: 24px; }")
    html_lines.append("        h1 { color: #0284c7; border-bottom: 2px solid #e2e8f0; padding-bottom: 8px; margin-top: 24px; font-size: 1.8em; }")
    html_lines.append("        h2 { color: #0f172a; margin-top: 24px; border-bottom: 1px solid #f1f5f9; padding-bottom: 6px; font-size: 1.4em; }")
    html_lines.append("        h3 { color: #334155; margin-top: 16px; font-size: 1.15em; }")
    html_lines.append("        blockquote { background: #f1f5f9; border-left: 4px solid #0284c7; margin: 12px 0; padding: 8px 16px; color: #475569; }")
    html_lines.append("        ul { list-style-type: square; padding-left: 24px; margin: 8px 0; }")
    html_lines.append("        li { margin-bottom: 6px; }")
    html_lines.append("        strong { color: #0f172a; }")
    html_lines.append("        hr { border: 0; height: 1px; background: #e2e8f0; margin: 28px 0; }")
    html_lines.append("        code { background: #f1f5f9; padding: 2px 6px; border-radius: 4px; font-size: 0.9em; }")
    html_lines.append("        a { color: #0284c7; text-decoration: none; }")
    html_lines.append("        a:hover { text-decoration: underline; }")
    html_lines.append("    </style>")
    html_lines.append("</head>")
    html_lines.append("<body>")
    html_lines.append('    <div class="card">')
    
    in_ul = False
    for line in md_text.splitlines():
        line_str = line.strip()
        if not line_str:
            if in_ul:
                html_lines.append("        </ul>")
                in_ul = False
            continue

        formatted_line = line_str
        formatted_line = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', formatted_line)
        formatted_line = re.sub(r'`(.+?)`', r'<code>\1</code>', formatted_line)
        formatted_line = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2">\1</a>', formatted_line)

        if line_str.startswith("# "):
            if in_ul:
                html_lines.append("        </ul>")
                in_ul = False
            html_lines.append(f"        <h1>{formatted_line[2:].strip()}</h1>")
        elif line_str.startswith("## "):
            if in_ul:
                html_lines.append("        </ul>")
                in_ul = False
            html_lines.append(f"        <h2>{formatted_line[3:].strip()}</h2>")
        elif line_str.startswith("### "):
            if in_ul:
                html_lines.append("        </ul>")
                in_ul = False
            html_lines.append(f"        <h3>{formatted_line[4:].strip()}</h3>")
        elif line_str.startswith("> "):
            if in_ul:
                html_lines.append("        </ul>")
                in_ul = False
            html_lines.append(f"        <blockquote>{formatted_line[2:].strip()}</blockquote>")
        elif line_str.startswith("- "):
            if not in_ul:
                html_lines.append("        <ul>")
                in_ul = True
            html_lines.append(f"            <li>{formatted_line[2:].strip()}</li>")
        elif line_str == "---" or "====" in line_str:
            if in_ul:
                html_lines.append("        </ul>")
                in_ul = False
            html_lines.append("        <hr>")
        else:
            if in_ul:
                html_lines.append("        </ul>")
                in_ul = False
            html_lines.append(f"        <p>{formatted_line}</p>")

    if in_ul:
        html_lines.append("        </ul>")
    html_lines.append("    </div>")
    html_lines.append("</body>")
    html_lines.append("</html>")
    return "\n".join(html_lines)

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
            
            # 2. X Family (Exclude XM models - kept exclusively in M High Performance)
            is_xm = 'xm' in s_lower or m_lower.startswith('xm')
            if not is_xm:
                if any(k in s_lower for k in ['x1', 'x2', 'x3', 'x4', 'x5', 'x6', 'x7', 'ix', 'ix1', 'ix2', 'ix3']) or m_lower.startswith('x'):
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

        full_md_content = "\n".join(glines)
        with open(gpath, "w", encoding="utf-8") as f:
            f.write(full_md_content)

        # Generate HTML copy for NotebookLM Web URL Ingestion
        html_path = os.path.join(lang_dir, f"{gname}.html")
        html_content = convert_markdown_to_html(full_md_content, title=gname.replace('_', ' '), lang=lang)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        gsize_kb = os.path.getsize(gpath) / 1024
        hsize_kb = os.path.getsize(html_path) / 1024
        print(f"[GROUP] Generated MD: {gpath} ({gsize_kb:.1f} KB) & HTML: {html_path} ({hsize_kb:.1f} KB)")

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
