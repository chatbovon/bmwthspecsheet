import json
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

REPORT_PATH = r"C:\Users\admin\.gemini\antigravity\brain\cb056dc3-e996-4677-abf1-e3594a4cb939\lite_vs_master_report.md"

def load_json(path):
    if not os.path.exists(path):
        print(f"[ERROR] File not found: {path}")
        return []
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def build_flat_spec_map(models):
    flat_map = {}
    for m in models:
        mname = m.get("model_name", "")
        flat_map[mname] = {}
        for spec in m.get("specifications", []):
            cat = spec.get("category", "")
            for detail in spec.get("details", []):
                topic = detail.get("topic", "")
                val = detail.get("value", "")
                flat_map[mname][(cat, topic)] = val
    return flat_map

def compare_dbs(lite_db, prod_db, lang):
    report_lines = []
    report_lines.append(f"## 📊 Database Comparison: {lang.upper()} Specifications")
    
    # Map production by PDF source for easy lookup
    prod_by_pdf = {item.get("pdf_source"): item for item in prod_db if "pdf_source" in item}
    
    for lite_item in lite_db:
        pdf = lite_item.get("pdf_source", "")
        prod_item = prod_by_pdf.get(pdf)
        
        report_lines.append(f"### 📄 Brochure: `{pdf}`")
        if not prod_item:
            report_lines.append(f"> [!WARNING]\n> Brochure not found in production database.")
            continue
            
        lite_models = lite_item.get("models", [])
        prod_models = prod_item.get("models", [])
        
        report_lines.append(f"- **Lite Models ({len(lite_models)}):** " + ", ".join([f"`{m.get('model_name')}`" for m in lite_models]))
        report_lines.append(f"- **Production Models ({len(prod_models)}):** " + ", ".join([f"`{m.get('model_name')}`" for m in prod_models]))
        
        # Build flat maps
        lite_map = build_flat_spec_map(lite_models)
        prod_map = build_flat_spec_map(prod_models)
        
        all_models = sorted(list(set(lite_map.keys()) | set(prod_map.keys())))
        
        for mname in all_models:
            report_lines.append(f"#### 🚗 Model: `{mname}`")
            
            l_specs = lite_map.get(mname, {})
            p_specs = prod_map.get(mname, {})
            
            if not l_specs:
                report_lines.append(f"> [!IMPORTANT]\n> Model missing in Lite extraction.")
                continue
            if not p_specs:
                report_lines.append(f"> [!IMPORTANT]\n> Model missing in Production database.")
                continue
                
            # Compare key-value pairs
            lite_keys = set(l_specs.keys())
            prod_keys = set(p_specs.keys())
            
            common_keys = sorted(list(lite_keys & prod_keys))
            lite_only = sorted(list(lite_keys - prod_keys))
            prod_only = sorted(list(prod_keys - lite_keys))
            
            # Value differences
            diff_values = []
            for k in common_keys:
                if l_specs[k] != p_specs[k]:
                    diff_values.append((k[0], k[1], l_specs[k], p_specs[k]))
                    
            report_lines.append(f"- **Total Topics count:** Lite={len(lite_keys)} | Production={len(prod_keys)}")
            
            if not diff_values and not lite_only and not prod_only:
                report_lines.append("✅ **100% Match! No discrepancies found.**")
                continue
                
            # Print value discrepancies
            if diff_values:
                report_lines.append("\n##### 🔴 Value Discrepancies")
                report_lines.append("| Category | Topic | Lite Value (gemini-3.5-flash-lite) | Production Value (gemini-3.6-flash) |")
                report_lines.append("|---|---|---|---|")
                for cat, topic, l_val, p_val in diff_values:
                    report_lines.append(f"| {cat} | {topic} | `{l_val}` | `{p_val}` |")
                    
            # Print lite-only topics (possible hallucination/unmerged lines)
            if lite_only:
                report_lines.append("\n##### ➕ Topics present only in Lite extraction (Unmerged or Extra)")
                report_lines.append("| Category | Topic | Value |")
                report_lines.append("|---|---|---|")
                for cat, topic in lite_only:
                    report_lines.append(f"| {cat} | {topic} | `{l_specs[(cat, topic)]}` |")
                    
            # Print production-only topics (possible omission by lite model)
            if prod_only:
                report_lines.append("\n##### ➖ Topics missed by Lite extraction (Present in Production)")
                report_lines.append("| Category | Topic | Value |")
                report_lines.append("|---|---|---|")
                for cat, topic in prod_only:
                    report_lines.append(f"| {cat} | {topic} | `{p_specs[(cat, topic)]}` |")
                    
        report_lines.append("\n---")
        
    return report_lines

def main():
    print("[COMPARE] Loading databases...")
    lite_th = load_json("scratch/lite_master_specs.json")
    lite_en = load_json("scratch/lite_master_specs_en.json")
    prod_th = load_json("bmw_master_specs.json")
    prod_en = load_json("bmw_master_specs_en.json")
    
    md_content = []
    md_content.append("# 📝 Comparison Report: Gemini-3.5-Flash-Lite vs Production (Gemini-3.6-Flash)")
    md_content.append("This report audits the structural and content differences between the specifications extracted solely with the `gemini-3.5-flash-lite` model and the current production databases.")
    md_content.append("\n---")
    
    # Compare Thai
    th_reports = compare_dbs(lite_th, prod_th, "th")
    md_content.extend(th_reports)
    
    # Compare English
    en_reports = compare_dbs(lite_en, prod_en, "en")
    md_content.extend(en_reports)
    
    # Save Report
    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write("\n".join(md_content))
    print(f"[COMPARE] Comparison report saved to: {REPORT_PATH}")

if __name__ == "__main__":
    main()
