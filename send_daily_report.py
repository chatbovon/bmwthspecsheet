import os
import sys
import json
import subprocess
import re
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Set console encoding to UTF-8
sys.stdout.reconfigure(encoding='utf-8')

# Constants
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TH_CATALOG = os.path.join(BASE_DIR, "bmw_master_specs.json")
EN_CATALOG = os.path.join(BASE_DIR, "bmw_master_specs_en.json")
GAS_WEBAPP_URL = os.environ.get("GAS_WEBAPP_URL")
GAS_SECRET_TOKEN = os.environ.get("GAS_SECRET_TOKEN")

# Helper to check if model is a pure M (high performance) model
def is_pure_m_car(model_name):
    name = model_name.strip()
    
    # 1. XM series (including XM, XM 50e, XM Label Red) are always M Power
    if name.startswith("XM") or " XM " in f" {name} ":
        return True
        
    # 2. Starts with M followed by EXACTLY one digit (e.g. M2, M3, M4, M5, M8, M3 CS)
    if re.search(r"^M\d(?!\d)", name):
        return True
        
    # 3. M follows an X series model as a standalone letter (e.g. X3 M, X5 M Competition)
    if re.search(r"^X\d\s+M\b", name):
        return True
        
    return False

# 1. Audit PDF brochure changes via git status
def audit_pdf_changes():
    added_pdfs = []
    removed_pdfs = []
    try:
        # Run git status to find untracked or modified files
        res = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=True)
        lines = res.stdout.splitlines()
        for line in lines:
            line = line.strip()
            # Split by whitespace, format is typically "?? filepath" or "A filepath" or "D filepath"
            parts = line.split(maxsplit=1)
            if len(parts) < 2:
                continue
            status, filepath = parts[0], parts[1]
            
            # Detect PDFs
            if filepath.endswith(".pdf"):
                basename = os.path.basename(filepath)
                if "bmw_brochures_auto" in filepath:
                    if status in ["??", "A"]:
                        added_pdfs.append(f"{basename} (Active)")
                    elif status == "D":
                        removed_pdfs.append(f"{basename} (Active)")
                elif "bmw_brochures_custom" in filepath:
                    if status in ["??", "A"]:
                        # Moved to custom means archived (removed from live)
                        removed_pdfs.append(f"{basename} (Archived)")
    except Exception as e:
        print(f"[WARNING] Git status audit failed: {e}")
        
    return added_pdfs, removed_pdfs

# Helper to normalize color names for comparison (matching index.html resolveImagePath)
def normalize_color(name):
    if not name:
        return ""
    n = name.lower().strip()
    n = n.replace("metallic", "").strip()
    # Strip leading "m " (case insensitive)
    n = re.sub(r"^m\s+", "", n)
    # Strip all whitespace
    n = re.sub(r"\s+", "", n)
    return n

def find_matching_image(opt_name, images_dict):
    target = normalize_color(opt_name)
    for key, path in images_dict.items():
        k = normalize_color(key)
        if target == k or target in k or k in target:
            return path
    return None

# 2. Audit Missing Images (Non-M)
def audit_missing_images(th_data):
    missing_images_report = {}
    total_non_m_models = 0
    models_with_missing_images = 0
    
    for series_item in th_data:
        for model in series_item.get("models", []):
            model_name = model.get("model_name", "Unknown")
            if is_pure_m_car(model_name):
                continue
                
            total_non_m_models += 1
            images_dict = model.get("images", {})
            
            # Find paintwork options in specifications
            paint_options = []
            for cat in model.get("specifications", []):
                cat_name = cat.get("category", "")
                if "Paintwork" in cat_name or "สีตัวถัง" in cat_name:
                    for detail in cat.get("details", []):
                        opt_name = detail.get("topic")
                        opt_val = (detail.get("value") or "").strip()
                        if opt_name and opt_val != "-":
                            paint_options.append(opt_name)
                            
            missing_for_model = []
            if not images_dict and paint_options:
                missing_for_model.append("Missing entirely (no image dictionary)")
            else:
                for opt in paint_options:
                    img_path = find_matching_image(opt, images_dict)
                    if not img_path:
                        missing_for_model.append(f"No image path mapped for color: '{opt}'")
                    else:
                        full_img_path = os.path.join(BASE_DIR, img_path)
                        if not os.path.exists(full_img_path):
                            missing_for_model.append(f"Image file not found on disk: '{opt}' ({img_path})")
                            
            if missing_for_model:
                missing_images_report[model_name] = missing_for_model
                models_with_missing_images += 1
                
    return missing_images_report, total_non_m_models, models_with_missing_images

# 3. Cross-DB alignment and discrepancy audit
def audit_data_discrepancies(th_data, en_data):
    discrepancies = []
    total_checks = 0
    
    # Map EN models for quick lookup
    en_models_map = {}
    for series_item in en_data:
        for m in series_item.get("models", []):
            mname = m.get("model_name", "").strip()
            if mname:
                en_models_map[mname.lower()] = m
                
    for series_item in th_data:
        for th_model in series_item.get("models", []):
            mname = th_model.get("model_name", "").strip()
            if not mname:
                continue
            
            en_model = en_models_map.get(mname.lower())
            if not en_model:
                discrepancies.append({
                    "model": mname,
                    "type": "Missing Model",
                    "description": "Model exists in Thai specs but is missing from English specs."
                })
                continue
                
            # Filter out localized Notes/disclaimers
            th_specs = [c for c in th_model.get("specifications", []) if (c.get("category") or "").strip() not in ("หมายเหตุ", "Notes")]
            en_specs = [c for c in en_model.get("specifications", []) if (c.get("category") or "").strip() not in ("หมายเหตุ", "Notes")]
            
            # Check category alignment
            if len(th_specs) != len(en_specs):
                discrepancies.append({
                    "model": mname,
                    "type": "Category Count Mismatch",
                    "description": f"Category counts differ: TH={len(th_specs)} vs EN={len(en_specs)}."
                })
                
            # Compare categories one-to-one
            for idx in range(min(len(th_specs), len(en_specs))):
                th_cat = th_specs[idx]
                en_cat = en_specs[idx]
                
                th_cat_name = th_cat.get("category", "")
                en_cat_name = en_cat.get("category", "")
                
                th_details = th_cat.get("details", [])
                en_details = en_cat.get("details", [])
                
                # Check topic counts in category
                if len(th_details) != len(en_details):
                    discrepancies.append({
                        "model": mname,
                        "type": "Topic Count Mismatch",
                        "description": f"In category '{th_cat_name}': topic counts differ (TH={len(th_details)} vs EN={len(en_details)})."
                    })
                    
                # Compare topic details
                for t_idx in range(min(len(th_details), len(en_details))):
                    total_checks += 1
                    th_topic = th_details[t_idx]
                    en_topic = en_details[t_idx]
                    
                    # Clean/normalize symbols for comparison
                    th_val = (th_topic.get("value") or "").strip()
                    en_val = (en_topic.get("value") or "").strip()
                    
                    # Mismatched option checkmarks
                    if (th_val == "■" and en_val == "-") or (th_val == "-" and en_val == "■"):
                        discrepancies.append({
                            "model": mname,
                            "type": "Option Mismatch",
                            "description": f"Category '{th_cat_name}', Topic '{th_topic.get('topic')}': TH={th_val} vs EN={en_val}."
                        })
                        
    return discrepancies, total_checks

# 4. Check API Keys and token configuration
def check_api_health():
    status = []
    # Test Gemini keys
    for i in range(1, 4):
        key = os.environ.get(f"GEMINI_API_KEY_{i}")
        if not key or key == "[REMOVE]":
            status.append(f"Gemini Key #{i}: Missing / Empty")
        else:
            status.append(f"Gemini Key #{i}: Configured")
            
    mineru_token = os.environ.get("MINERU_API_TOKEN")
    if not mineru_token or mineru_token == "[REMOVE]":
        status.append("MinerU API Token: Missing / Empty")
    else:
        status.append("MinerU API Token: Configured")
        
    return status

# 5. Overrides statistics
def check_overrides_stats():
    overrides_path = os.path.join(BASE_DIR, "manual_overrides.json")
    if not os.path.exists(overrides_path):
        return 0, 0
    try:
        with open(overrides_path, encoding="utf-8") as f:
            overrides = json.load(f)
        total_files = len([k for k in overrides.keys() if not k.startswith("_")])
        total_rules = 0
        for k, v in overrides.items():
            if k.startswith("_"):
                continue
            total_rules += len(v.get("models", []))
        return total_files, total_rules
    except:
        return 0, 0

# Compile HTML Report
def generate_html_report(added_pdfs, removed_pdfs, missing_imgs, total_non_m, models_missing_imgs, discrepancies, total_checks, api_status, files_overridden, total_rules):
    # Calculate health score
    health_score = 100.0
    if total_checks > 0:
        health_score = max(0.0, 100.0 - (len(discrepancies) / total_checks * 100.0))
        
    # PDF updates table
    pdf_updates_html = ""
    if not added_pdfs and not removed_pdfs:
        pdf_updates_html = "<p style='color: #6c757d;'>No brochure changes detected today.</p>"
    else:
        pdf_updates_html = "<table style='width: 100%; border-collapse: collapse; margin-bottom: 20px; font-family: Arial, sans-serif;'>"
        pdf_updates_html += "<tr style='background-color: #f8f9fa; border-bottom: 2px solid #dee2e6; text-align: left;'><th style='padding: 8px;'>Action</th><th style='padding: 8px;'>Brochure PDF File</th></tr>"
        for pdf in added_pdfs:
            pdf_updates_html += f"<tr style='border-bottom: 1px solid #dee2e6;'><td style='padding: 8px; color: #28a745; font-weight: bold;'>➕ Added</td><td style='padding: 8px;'>{pdf}</td></tr>"
        for pdf in removed_pdfs:
            pdf_updates_html += f"<tr style='border-bottom: 1px solid #dee2e6;'><td style='padding: 8px; color: #dc3545; font-weight: bold;'>➖ Removed</td><td style='padding: 8px;'>{pdf}</td></tr>"
        pdf_updates_html += "</table>"

    # API keys layout
    api_html = "<ul>"
    for status in api_status:
        color = "#28a745" if "Configured" in status else "#dc3545"
        api_html += f"<li style='margin-bottom: 5px; font-family: Arial, sans-serif;'>{status.split(':')[0]}: <span style='color: {color}; font-weight: bold;'>{status.split(':')[1]}</span></li>"
    api_html += "</ul>"

    # Missing images table
    missing_imgs_html = ""
    if not missing_imgs:
        missing_imgs_html = "<p style='color: #28a745; font-weight: bold; font-family: Arial, sans-serif;'>🎉 All non-M models have 100% complete paintwork images mapped on disk!</p>"
    else:
        missing_imgs_html = "<table style='width: 100%; border-collapse: collapse; margin-bottom: 20px; font-family: Arial, sans-serif;'>"
        missing_imgs_html += "<tr style='background-color: #f8f9fa; border-bottom: 2px solid #dee2e6; text-align: left;'><th style='padding: 8px; width: 30%;'>Model</th><th style='padding: 8px;'>Details / Missing Colors</th></tr>"
        for model, details in missing_imgs.items():
            details_str = "<br>".join([f"• {d}" for d in details])
            missing_imgs_html += f"<tr style='border-bottom: 1px solid #dee2e6; vertical-align: top;'><td style='padding: 8px; font-weight: bold;'>{model}</td><td style='padding: 8px; color: #d9534f;'>{details_str}</td></tr>"
        missing_imgs_html += "</table>"

    # Discrepancies table
    discrepancies_html = ""
    if not discrepancies:
        discrepancies_html = "<p style='color: #28a745; font-weight: bold; font-family: Arial, sans-serif;'>🎉 No database discrepancies found between TH and EN specsheets!</p>"
    else:
        discrepancies_html = f"<p style='color: #dc3545; font-weight: bold; font-family: Arial, sans-serif;'>⚠️ Found {len(discrepancies)} discrepancies between TH and EN specsheets:</p>"
        discrepancies_html += "<table style='width: 100%; border-collapse: collapse; margin-bottom: 20px; font-family: Arial, sans-serif;'>"
        discrepancies_html += "<tr style='background-color: #f8f9fa; border-bottom: 2px solid #dee2e6; text-align: left;'><th style='padding: 8px; width: 30%;'>Model</th><th style='padding: 8px; width: 20%;'>Error Type</th><th style='padding: 8px;'>Description</th></tr>"
        for disc in discrepancies[:15]: # Cap at 15 to keep email readable
            discrepancies_html += f"<tr style='border-bottom: 1px solid #dee2e6; vertical-align: top;'><td style='padding: 8px; font-weight: bold;'>{disc['model']}</td><td style='padding: 8px; color: #f0ad4e; font-weight: bold;'>{disc['type']}</td><td style='padding: 8px;'>{disc['description']}</td></tr>"
        if len(discrepancies) > 15:
            discrepancies_html += f"<tr><td colspan='3' style='padding: 8px; text-align: center; color: #6c757d; font-style: italic;'>... and {len(discrepancies) - 15} more. View execution logs for details.</td></tr>"
        discrepancies_html += "</table>"

    # Final HTML body with glassmorphism style dashboard header
    html = f"""
    <html>
    <body style="background-color: #f4f6f9; padding: 20px; margin: 0;">
      <div style="max-width: 800px; margin: 0 auto; background-color: #ffffff; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.05); overflow: hidden;">
        
        <!-- Header -->
        <div style="background-color: #0b132b; color: #ffffff; padding: 25px; font-family: 'Helvetica Neue', Arial, sans-serif;">
          <h2 style="margin: 0; font-size: 24px; letter-spacing: 1px;">🚗 BMW SPEC SHEET DAILY STATUS</h2>
          <p style="margin: 5px 0 0 0; color: #5bc0be; font-size: 14px;">Automated Database & Image Integrity Audit Report</p>
        </div>

        <!-- Dashboard Widgets -->
        <div style="padding: 20px 20px 0 20px; display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; font-family: Arial, sans-serif;">
          
          <div style="background-color: #f8f9fa; border-left: 4px solid #0288d1; padding: 15px; border-radius: 4px;">
            <div style="font-size: 12px; color: #6c757d; font-weight: bold; text-transform: uppercase;">Alignment Score</div>
            <div style="font-size: 24px; font-weight: bold; color: { '#28a745' if health_score > 95 else '#f0ad4e' };">{health_score:.1f}%</div>
          </div>
          
          <div style="background-color: #f8f9fa; border-left: 4px solid #e28743; padding: 15px; border-radius: 4px;">
            <div style="font-size: 12px; color: #6c757d; font-weight: bold; text-transform: uppercase;">Image Coverage</div>
            <div style="font-size: 24px; font-weight: bold; color: { '#28a745' if models_missing_imgs == 0 else '#dc3545' };">{total_non_m - models_missing_imgs}/{total_non_m}</div>
            <div style="font-size: 11px; color: #6c757d;">(Non-M models with images)</div>
          </div>

          <div style="background-color: #f8f9fa; border-left: 4px solid #5bc0be; padding: 15px; border-radius: 4px;">
            <div style="font-size: 12px; color: #6c757d; font-weight: bold; text-transform: uppercase;">Manual Overrides</div>
            <div style="font-size: 24px; font-weight: bold; color: #333;">{total_rules} rules</div>
            <div style="font-size: 11px; color: #6c757d;">({files_overridden} source brochures corrected)</div>
          </div>

        </div>

        <!-- Main Content -->
        <div style="padding: 20px; font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
          
          <!-- 1. PDF Updates -->
          <h3 style="border-bottom: 2px solid #0b132b; padding-bottom: 5px; color: #0b132b;">1. 📄 Brochure PDF Changes</h3>
          {pdf_updates_html}
          
          <!-- 2. Image Audit -->
          <h3 style="border-bottom: 2px solid #0b132b; padding-bottom: 5px; color: #0b132b;">2. 🖼️ Missing Option Color Images (Non-M Models)</h3>
          {missing_imgs_html}
          
          <!-- 3. Discrepancies -->
          <h3 style="border-bottom: 2px solid #0b132b; padding-bottom: 5px; color: #0b132b;">3. 📐 TH / EN Specsheet Alignment Discrepancies</h3>
          {discrepancies_html}

          <!-- 4. Key Health -->
          <h3 style="border-bottom: 2px solid #0b132b; padding-bottom: 5px; color: #0b132b;">4. 🔑 API Key Status</h3>
          {api_html}

        </div>

        <!-- Footer -->
        <div style="background-color: #f8f9fa; padding: 15px; text-align: center; font-size: 12px; color: #6c757d; border-top: 1px solid #dee2e6; font-family: Arial, sans-serif;">
          Generated by BMW Dynamic Specsheet Automated Action Pipeline.<br>
          For system details, visit: <a href="https://github.com/chatbovon/bmwthspecsheet" style="color: #0288d1; text-decoration: none;">GitHub Workspace</a>
        </div>

      </div>
    </body>
    </html>
    """
    return html

def main():
    print("[START] Loading database catalogs...")
    if not os.path.exists(TH_CATALOG) or not os.path.exists(EN_CATALOG):
        print("[ERROR] Database catalogs not found. Skipping daily report.")
        sys.exit(0)
        
    try:
        with open(TH_CATALOG, encoding="utf-8") as f:
            th_data = json.load(f)
        with open(EN_CATALOG, encoding="utf-8") as f:
            en_data = json.load(f)
    except Exception as e:
        print(f"[ERROR] Failed to load json databases: {e}")
        sys.exit(0)
        
    # Gather report data
    print("[AUDIT] Checking PDF brochure updates...")
    added_pdfs, removed_pdfs = audit_pdf_changes()
    
    print("[AUDIT] Auditing missing color images...")
    missing_imgs, total_non_m, models_missing_imgs = audit_missing_images(th_data)
    
    print("[AUDIT] Running data discrepancy checks...")
    discrepancies, total_checks = audit_data_discrepancies(th_data, en_data)
    
    print("[AUDIT] Fetching API health parameters...")
    api_status = check_api_health()
    
    print("[AUDIT] Fetching override rules...")
    files_overridden, total_rules = check_overrides_stats()
    
    # Generate HTML Report body
    print("[REPORT] Formatting HTML body...")
    html_body = generate_html_report(
        added_pdfs, removed_pdfs, missing_imgs, 
        total_non_m, models_missing_imgs, 
        discrepancies, total_checks, 
        api_status, files_overridden, total_rules
    )
    
    # Send via Google Apps Script (GAS) Web App
    if not GAS_WEBAPP_URL or not GAS_SECRET_TOKEN:
        print("[WARNING] GAS_WEBAPP_URL or GAS_SECRET_TOKEN is not configured. Report output saved to 'daily_report_preview.html'.")
        with open("daily_report_preview.html", "w", encoding="utf-8") as f:
            f.write(html_body)
        sys.exit(0)
        
    print("[POST] Sending email report to Google Apps Script Web App...")
    payload = {
        "secret": GAS_SECRET_TOKEN,
        "subject": f"🚗 [BMW Specsheet] Daily Monitor Report ({len(discrepancies)} Issues)",
        "html_body": html_body
    }
    
    try:
        res = requests.post(GAS_WEBAPP_URL, json=payload, timeout=20)
        print(f"[API RESPONSE] Status Code: {res.status_code}, Response text: {res.text}")
        if res.status_code == 200:
            print("[SUCCESS] Email report successfully triggered and sent!")
        else:
            print(f"[FAILED] GAS Web App returned non-200 code: {res.status_code}")
    except Exception as ex:
        print(f"[ERROR] Failed to post report to GAS: {ex}")

if __name__ == "__main__":
    main()
