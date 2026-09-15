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
DB_MASTER_TH_PATH = os.path.join(WORKTREE_DIR, "bmw_master_specs.json")
DB_MASTER_EN_PATH = os.path.join(WORKTREE_DIR, "bmw_master_specs_en.json")
DB_CUSTOM_TH_PATH = os.path.join(WORKTREE_DIR, "bmw_custom_specs.json")
DB_CUSTOM_EN_PATH = os.path.join(WORKTREE_DIR, "bmw_custom_specs_en.json")
DOSSIER_DIR = os.path.join(WORKTREE_DIR, "dossier")

def sanitize_anchor(name: str) -> str:
    """Sanitize model name to valid HTML anchor ID."""
    name = re.sub(r'[/\\:*?"<>|]', '_', name)
    name = name.replace(' ', '_').replace('__', '_').strip('_').lower()
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

def generate_model_section_html(series_name: str, model_data: dict, pdf_source: str, lang: str = "th", is_custom: bool = False) -> str:
    mname = model_data.get("model_name", "").strip()
    powertrain = get_powertrain_type(mname, model_data.get("specifications", []), lang=lang)
    anchor_id = sanitize_anchor(mname)
    
    html_lines = []
    html_lines.append(f'<section class="model-dossier" id="{anchor_id}">')
    html_lines.append(f'    <div class="model-header">')
    html_lines.append(f'        <h2>{mname}</h2>')
    html_lines.append(f'        <span class="badge badge-powertrain">{powertrain}</span>')
    if is_custom:
        badge_text = "โบรชัวร์รุ่นเดิม (Custom/Archived)" if lang == "th" else "Archived / Custom Brochure"
        html_lines.append(f'        <span class="badge badge-archived">{badge_text}</span>')
    else:
        badge_text = "รุ่นจำหน่ายปัจจุบัน (Active Catalog)" if lang == "th" else "Active Official Catalog"
        html_lines.append(f'        <span class="badge badge-active">{badge_text}</span>')
    html_lines.append(f'    </div>')
    
    html_lines.append('    <div class="meta-box">')
    if lang == "th":
        html_lines.append(f'        <p><strong>ซีรีส์หลัก:</strong> {series_name}</p>')
        if pdf_source:
            html_lines.append(f'        <p><strong>เอกสารโบรชัวร์อ้างอิง:</strong> <code>{pdf_source}</code></p>')
    else:
        html_lines.append(f'        <p><strong>Main Series:</strong> {series_name}</p>')
        if pdf_source:
            html_lines.append(f'        <p><strong>Source Brochure PDF:</strong> <code>{pdf_source}</code></p>')
    html_lines.append('    </div>')
    
    # Specifications
    cat_idx = 1
    for spec in model_data.get("specifications", []):
        cat_name = spec.get("category", "").strip()
        if not cat_name or cat_name in ("หมายเหตุ", "Notes"):
            continue
            
        html_lines.append(f'    <div class="spec-category">')
        html_lines.append(f'        <h3>{cat_idx}. {cat_name}</h3>')
        cat_idx += 1
        
        details = spec.get("details", [])
        if not details:
            no_det = "(ไม่มีข้อมูลจำเพาะย่อย / No sub-details)" if lang == "th" else "(No sub-details available)"
            html_lines.append(f'        <p class="text-muted">{no_det}</p>')
        else:
            html_lines.append('        <ul class="spec-list">')
            for d in details:
                topic = d.get("topic", "").strip()
                val = format_value(d.get("value", ""), lang=lang)
                if not topic:
                    continue
                html_lines.append(f'            <li><strong>{topic}:</strong> <span class="spec-value">{val}</span></li>')
            html_lines.append('        </ul>')
        html_lines.append('    </div>')
        
    # Paintwork & Upholstery
    paintwork_data = model_data.get("paintwork_and_upholstery", {}) or model_data.get("color_options", {})
    if paintwork_data:
        section_title = "สีตัวถังและวัสดุตกแต่งภายใน (Paintwork & Upholstery Combinations)" if lang == "th" else "Paintwork & Interior Upholstery Combinations"
        html_lines.append(f'    <div class="spec-category">')
        html_lines.append(f'        <h3>{cat_idx}. {section_title}</h3>')
        cat_idx += 1
        html_lines.append('        <ul class="spec-list">')
        for color, interiors in paintwork_data.items():
            interiors_str = ", ".join(interiors) if isinstance(interiors, list) else str(interiors)
            label_text = f"สีภายนอก {color}" if lang == "th" else f"Exterior Paint {color}"
            html_lines.append(f'            <li><strong>{label_text}:</strong> <code>{interiors_str}</code></li>')
        html_lines.append('        </ul>')
        html_lines.append('    </div>')
        
    # Notes
    notes_spec = next((c for c in model_data.get("specifications", []) if (c.get("category") or "").strip() in ("หมายเหตุ", "Notes")), None)
    if notes_spec and notes_spec.get("details"):
        notes_title = "ข้อกำหนดและหมายเหตุทางการ (Official Notes & Terms)" if lang == "th" else "Official Notes & Terms"
        html_lines.append(f'    <div class="notes-box">')
        html_lines.append(f'        <h4>{notes_title}</h4>')
        for note in notes_spec.get("details", []):
            topic = note.get("topic", "").strip()
            if topic:
                html_lines.append(f'        <p>• {topic}</p>')
        html_lines.append('    </div>')
        
    html_lines.append('</section>')
    html_lines.append('<hr class="model-divider">')
    return "\n".join(html_lines)

def generate_full_html_page(title: str, subtitle: str, now_ict: str, models_catalog: list, lang: str = "th", is_custom: bool = False) -> str:
    toc_items = []
    model_sections = []
    
    total_models = 0
    for entry in models_catalog:
        sname = entry.get("series", "").strip()
        pdf_source = entry.get("pdf_source") or entry.get("source_file", "")
        
        for model in entry.get("models", []):
            mname = model.get("model_name", "").strip()
            if not mname:
                continue
            total_models += 1
            anchor_id = sanitize_anchor(mname)
            toc_items.append((mname, anchor_id, sname))
            
            section_html = generate_model_section_html(sname, model, pdf_source, lang=lang, is_custom=is_custom)
            model_sections.append(section_html)
            
    html = []
    html.append("<!DOCTYPE html>")
    html.append(f'<html lang="{lang}">')
    html.append("<head>")
    html.append('    <meta charset="UTF-8">')
    html.append('    <meta name="viewport" content="width=device-width, initial-scale=1.0">')
    html.append(f'    <title>{title}</title>')
    html.append("    <style>")
    html.append("        :root { --primary: #0284c7; --primary-dark: #0369a1; --bg: #f8fafc; --card-bg: #ffffff; --text: #1e293b; --text-muted: #64748b; --border: #e2e8f0; }")
    html.append("        body { font-family: -apple-system, BlinkMacSystemFont, 'Prompt', 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: var(--text); background: var(--bg); margin: 0; padding: 24px; }")
    html.append("        .container { max-width: 1000px; margin: 0 auto; }")
    html.append("        .main-card { background: var(--card-bg); padding: 40px; border-radius: 16px; box-shadow: 0 4px 20px -2px rgba(0,0,0,0.06); margin-bottom: 32px; }")
    html.append("        h1 { color: var(--primary); font-size: 2.2em; margin-top: 0; margin-bottom: 8px; border-bottom: 3px solid var(--primary); padding-bottom: 12px; }")
    html.append("        .subtitle { color: var(--text-muted); font-size: 1.1em; margin-bottom: 20px; }")
    html.append("        .meta-header { background: #f0f9ff; border-left: 4px solid var(--primary); padding: 12px 18px; border-radius: 0 8px 8px 0; margin-bottom: 28px; font-size: 0.95em; color: var(--primary-dark); }")
    html.append("        .toc-card { background: #f8fafc; border: 1px solid var(--border); border-radius: 12px; padding: 24px; margin-bottom: 36px; }")
    html.append("        .toc-card h3 { margin-top: 0; color: #0f172a; margin-bottom: 16px; }")
    html.append("        .toc-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 10px; list-style: none; padding: 0; margin: 0; }")
    html.append("        .toc-grid li a { display: block; padding: 8px 12px; background: #ffffff; border: 1px solid var(--border); border-radius: 6px; color: var(--primary-dark); text-decoration: none; font-size: 0.9em; transition: all 0.2s ease; }")
    html.append("        .toc-grid li a:hover { background: var(--primary); color: #ffffff; border-color: var(--primary); transform: translateY(-1px); }")
    html.append("        .model-dossier { margin-top: 40px; padding-top: 20px; scroll-margin-top: 20px; }")
    html.append("        .model-header { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; margin-bottom: 16px; }")
    html.append("        .model-header h2 { color: #0f172a; margin: 0; font-size: 1.6em; }")
    html.append("        .badge { display: inline-block; padding: 4px 10px; border-radius: 9999px; font-size: 0.8em; font-weight: 600; }")
    html.append("        .badge-powertrain { background: #e0f2fe; color: #0369a1; }")
    html.append("        .badge-active { background: #dcfce7; color: #15803d; }")
    html.append("        .badge-archived { background: #fef3c7; color: #b45309; }")
    html.append("        .meta-box { background: #f8fafc; border: 1px solid var(--border); padding: 12px 16px; border-radius: 8px; margin-bottom: 20px; font-size: 0.9em; }")
    html.append("        .meta-box p { margin: 4px 0; }")
    html.append("        .spec-category { margin-bottom: 24px; }")
    html.append("        .spec-category h3 { color: #334155; font-size: 1.15em; border-bottom: 1px solid var(--border); padding-bottom: 6px; margin-bottom: 12px; }")
    html.append("        .spec-list { list-style-type: none; padding-left: 0; margin: 0; }")
    html.append("        .spec-list li { padding: 6px 10px; border-bottom: 1px solid #f1f5f9; display: flex; justify-content: space-between; align-items: baseline; font-size: 0.92em; }")
    html.append("        .spec-list li:nth-child(even) { background: #fafafa; }")
    html.append("        .spec-value { font-weight: 500; color: #0f172a; text-align: right; max-width: 60%; }")
    html.append("        .notes-box { background: #fffbeb; border-left: 4px solid #f59e0b; padding: 12px 18px; border-radius: 0 8px 8px 0; margin-top: 20px; font-size: 0.88em; color: #78350f; }")
    html.append("        .notes-box h4 { margin-top: 0; margin-bottom: 6px; }")
    html.append("        .notes-box p { margin: 4px 0; }")
    html.append("        .model-divider { border: 0; height: 2px; background: linear-gradient(to right, #0284c7, #e2e8f0, transparent); margin: 48px 0; }")
    html.append("        code { background: #e2e8f0; padding: 2px 6px; border-radius: 4px; font-size: 0.88em; color: #0f172a; }")
    html.append("        .back-to-top { display: inline-block; margin-top: 16px; font-size: 0.85em; color: var(--primary); text-decoration: none; }")
    html.append("        .back-to-top:hover { text-decoration: underline; }")
    html.append("    </style>")
    html.append("</head>")
    html.append("<body>")
    html.append('    <div class="container">')
    html.append('        <div class="main-card">')
    html.append(f'            <h1>{title}</h1>')
    html.append(f'            <div class="subtitle">{subtitle}</div>')
    html.append('            <div class="meta-header">')
    if lang == "th":
        html.append(f'                <span>📅 <strong>อัปเดตล่าสุด:</strong> {now_ict}</span> | ')
        html.append(f'                <span>🏎️ <strong>จำนวนรุ่นในเล่มนี้:</strong> {total_models} รุ่น</span> | ')
        html.append('                <span>💡 <strong>สำหรับ:</strong> NotebookLM & AI RAG Ingestion</span>')
    else:
        html.append(f'                <span>📅 <strong>Last Updated:</strong> {now_ict}</span> | ')
        html.append(f'                <span>🏎️ <strong>Total Models:</strong> {total_models} models</span> | ')
        html.append('                <span>💡 <strong>Optimized for:</strong> NotebookLM & AI RAG Ingestion</span>')
    html.append('            </div>')
    
    # TOC
    html.append('            <div class="toc-card">')
    toc_heading = "📋 สารบัญรุ่นรถยนต์ทั้งหมดในเล่มนี้ (คลิกเพื่อข้ามไปยังรุ่น)" if lang == "th" else "📋 Table of Contents (Click to Jump to Model)"
    html.append(f'                <h3>{toc_heading}</h3>')
    html.append('                <ul class="toc-grid">')
    for mname, aid, sname in toc_items:
        html.append(f'                    <li><a href="#{aid}">{mname} <small style="color:#64748b;">({sname})</small></a></li>')
    html.append('                </ul>')
    html.append('            </div>')
    
    # Model Sections
    for sec in model_sections:
        html.append(sec)
        
    html.append('        </div>')
    html.append('    </div>')
    html.append("</body>")
    html.append("</html>")
    return "\n".join(html)

def build_dossier_html(db_path: str, output_html_filename: str, title: str, subtitle: str, lang: str = "th", is_custom: bool = False):
    if not os.path.exists(db_path):
        print(f"[ERROR] Database file not found: {db_path}")
        return
        
    with open(db_path, "r", encoding="utf-8") as f:
        catalog = json.load(f)
        
    lang_dir = os.path.join(DOSSIER_DIR, lang)
    os.makedirs(lang_dir, exist_ok=True)
    
    tz_ict = timezone(timedelta(hours=7))
    now_ict = datetime.now(tz_ict).strftime("%Y-%m-%d %H:%M:%S ICT (UTC+7)")
    
    html_content = generate_full_html_page(
        title=title,
        subtitle=subtitle,
        now_ict=now_ict,
        models_catalog=catalog,
        lang=lang,
        is_custom=is_custom
    )
    
    out_path = os.path.join(lang_dir, output_html_filename)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_content)
        
    size_kb = os.path.getsize(out_path) / 1024
    print(f"[HTML DOSSIER] Generated: {out_path} ({size_kb:.1f} KB)")

def main():
    print("=== STARTING HTML MODEL DOSSIER GENERATION ===")
    
    # 1. Active Models (Master) - TH & EN
    print("\n--- 1. Generating Active Models HTML Dossier (TH) ---")
    build_dossier_html(
        db_path=DB_MASTER_TH_PATH,
        output_html_filename="BMW_All_Models_Master_Dossier.html",
        title="BMW All Models Master Dossier (ไทย)",
        subtitle="แฟ้มข้อมูลสเปกเทคนิคและอุปกรณ์มาตรฐานรถยนต์ BMW ทุกรุ่นย่อย (โบรชัวร์จำหน่ายปัจจุบัน)",
        lang="th",
        is_custom=False
    )
    
    print("\n--- 2. Generating Active Models HTML Dossier (EN) ---")
    build_dossier_html(
        db_path=DB_MASTER_EN_PATH,
        output_html_filename="BMW_All_Models_Master_Dossier.html",
        title="BMW All Models Master Dossier (English)",
        subtitle="Comprehensive Technical Specification and Equipment Dossier for all active BMW models",
        lang="en",
        is_custom=False
    )
    
    # 2. Custom & Archived Models - TH & EN
    print("\n--- 3. Generating Custom & Archived Models HTML Dossier (TH) ---")
    build_dossier_html(
        db_path=DB_CUSTOM_TH_PATH,
        output_html_filename="BMW_Custom_Models_Master_Dossier.html",
        title="BMW Custom & Archived Models Master Dossier (ไทย)",
        subtitle="แฟ้มข้อมูลสเปกเทคนิคและอุปกรณ์มาตรฐานรถยนต์ BMW รุ่นคัสตอมและรุ่นปลดประจำการ",
        lang="th",
        is_custom=True
    )
    
    print("\n--- 4. Generating Custom & Archived Models HTML Dossier (EN) ---")
    build_dossier_html(
        db_path=DB_CUSTOM_EN_PATH,
        output_html_filename="BMW_Custom_Models_Master_Dossier.html",
        title="BMW Custom & Archived Models Master Dossier (English)",
        subtitle="Technical Specification and Equipment Dossier for custom and archived BMW models",
        lang="en",
        is_custom=True
    )
    
    print("\n=== HTML MODEL DOSSIER GENERATION COMPLETE ===")

if __name__ == "__main__":
    main()
