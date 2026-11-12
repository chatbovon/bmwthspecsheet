import os
import sys
import json
import subprocess
import re
import html as html_lib
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
CUSTOM_TH_CATALOG = os.path.join(BASE_DIR, "bmw_custom_specs.json")
CUSTOM_EN_CATALOG = os.path.join(BASE_DIR, "bmw_custom_specs_en.json")
GAS_WEBAPP_URL = os.environ.get("GAS_WEBAPP_URL")
GAS_SECRET_TOKEN = os.environ.get("GAS_SECRET_TOKEN")

# Category 99 (Uncategorized / Unknown Series) classifier matching custom.html getSortScore
def get_sort_category(series_name):
    name = (series_name or "").strip().upper()
    if name.startswith("BMW "):
        name = name[4:].strip()
        
    category = 99
    secondary = name
    
    if re.match(r'^\d', name):
        category = 1  # Series 2-8
        match = re.match(r'^(\d+)', name)
        if match:
            secondary = match.group(1).zfill(3)
    elif name.startswith("X") and len(name) > 1 and re.match(r'^\d', name[1:]):
        category = 2  # X1-7
        match = re.match(r'^(\d+)', name[1:])
        if match:
            secondary = match.group(1).zfill(3)
    elif name.startswith("Z"):
        category = 3  # Z
    elif name.startswith("I") or name.startswith("IX"):
        category = 4  # i / iX
    elif name.startswith("M") or name.startswith("XM"):
        category = 5  # M & XM
        
    return category, secondary

def audit_uncategorized_series(th_data, en_data, custom_th_data=None, custom_en_data=None):
    uncategorized = []
    datasets = [
        ("Master Specs (TH)", th_data),
        ("Master Specs (EN)", en_data),
    ]
    if custom_th_data:
        datasets.append(("Custom Specs (TH)", custom_th_data))
    if custom_en_data:
        datasets.append(("Custom Specs (EN)", custom_en_data))
        
    for db_label, db_list in datasets:
        if not isinstance(db_list, list):
            continue
        for entry in db_list:
            series_name = entry.get("series", "")
            cat, _ = get_sort_category(series_name)
            if cat == 99:
                models = [m.get("model_name", "") for m in entry.get("models", [])]
                pdf_source = entry.get("pdf_source", entry.get("pdf_filename", "Unknown PDF"))
                uncategorized.append({
                    "database": db_label,
                    "series": series_name or "(Empty Series Name)",
                    "pdf_source": pdf_source,
                    "models": models
                })
    return uncategorized

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
BLOCKED_IMAGE_STATUSES = {"blocked_th_en_conflict", "pending_paired_language"}


def categorize_missing_images(th_data):
    """Categorize non-M image coverage into complete, broken, pending_configurator, and blocked buckets."""
    broken = {}
    pending_configurator = {}
    blocked = {}
    total_non_m = 0
    complete_count = 0

    for series_item in th_data:
        for model in series_item.get("models", []):
            model_name = model.get("model_name", "Unknown")
            if is_pure_m_car(model_name):
                continue

            total_non_m += 1
            images_dict = model.get("images", {}) or {}
            image_status = (model.get("image_status") or "").strip()

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

            if image_status in BLOCKED_IMAGE_STATUSES:
                blocked[model_name] = missing_for_model or [f"Image scraping halted ({image_status})"]
            elif image_status == "pending_configurator":
                pending_configurator[model_name] = missing_for_model or [
                    "Waiting for BMW Thailand web configurator update (image_status: pending_configurator)"
                ]
            elif missing_for_model:
                broken[model_name] = missing_for_model
            else:
                complete_count += 1

    return {
        "broken": broken,
        "pending_configurator": pending_configurator,
        "blocked": blocked,
        "total_non_m": total_non_m,
        "complete_count": complete_count,
        "broken_count": len(broken),
        "pending_count": len(pending_configurator),
        "blocked_count": len(blocked),
    }


def audit_missing_images(th_data):
    breakdown = categorize_missing_images(th_data)
    missing_images_report = {}
    missing_images_report.update(breakdown["broken"])
    missing_images_report.update(breakdown["pending_configurator"])
    missing_images_report.update(breakdown["blocked"])
    return missing_images_report, breakdown["total_non_m"], len(missing_images_report)

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
                
            # Strict TH/EN image mapping & image_status 100% alignment (Rule 6 / Rule 7)
            th_imgs = th_model.get("images") or {}
            en_imgs = en_model.get("images") or {}
            total_checks += 1
            if th_imgs != en_imgs:
                discrepancies.append({
                    "model": mname,
                    "type": "Image Mapping Mismatch",
                    "description": f"Image mappings differ between TH ({len(th_imgs)} colors) and EN ({len(en_imgs)} colors).",
                })

            th_img_status = th_model.get("image_status") or ""
            en_img_status = en_model.get("image_status") or ""
            total_checks += 1
            if th_img_status != en_img_status:
                discrepancies.append({
                    "model": mname,
                    "type": "Image Status Mismatch",
                    "description": f"image_status differs between TH ({th_img_status!r}) and EN ({en_img_status!r}).",
                })

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

# Check Google Drive Upload Status
def audit_gdrive_status():
    status_file = os.path.join(BASE_DIR, "scratch", "gdrive_status.json")
    if not os.path.exists(status_file):
        return None
    try:
        with open(status_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[WARNING] Could not read gdrive_status.json: {e}")
        return None

# Audit TH/EN Visual Fingerprint Conflicts & Pending Paired Language Updates
def audit_image_conflicts(th_data, en_data, reconciliation_report_path=None):
    conflict_statuses = {"blocked_th_en_conflict", "pending_paired_language"}
    found_map = {}

    def _collect(data, lang_label):
        for series_item in data or []:
            series_name = (series_item.get("series") or "").strip()
            pdf_src = series_item.get("pdf_source") or ""
            for m in series_item.get("models", []) or []:
                status = (m.get("image_status") or "").strip()
                if status not in conflict_statuses:
                    continue
                mname = (m.get("model_name") or "").strip()
                key = (series_name.lower(), mname.lower())
                entry = found_map.setdefault(
                    key,
                    {
                        "series": series_name,
                        "model_name": mname,
                        "image_status": status,
                        "conflict_type": (
                            "TH/EN Visual Fingerprint Conflict"
                            if status == "blocked_th_en_conflict"
                            else "Waiting for Paired Language Brochure"
                        ),
                        "reason": (
                            f"{lang_label} flagged image_status='{status}' ({pdf_src})."
                        ),
                        "languages": [],
                    },
                )
                if lang_label not in entry["languages"]:
                    entry["languages"].append(lang_label)
                # Prefer blocked_th_en_conflict precedence if both statuses occur across languages
                if status == "blocked_th_en_conflict" and entry["image_status"] != "blocked_th_en_conflict":
                    entry["image_status"] = status

    _collect(th_data, "TH")
    _collect(en_data, "EN")

    if reconciliation_report_path is None:
        reconciliation_report_path = os.path.join(BASE_DIR, "scratch", "th_en_reconciliation_report.json")

    if reconciliation_report_path and os.path.exists(reconciliation_report_path):
        try:
            with open(reconciliation_report_path, "r", encoding="utf-8") as f:
                rep = json.load(f)
            for c in rep.get("conflicts", []) or []:
                c_series = (c.get("series") or "").strip()
                c_model = (c.get("model_name") or "").strip()
                c_status = (c.get("image_status") or "blocked_th_en_conflict").strip()
                if c_status not in conflict_statuses:
                    continue
                key = (c_series.lower(), c_model.lower())
                if key in found_map:
                    if c.get("conflict_type"):
                        found_map[key]["conflict_type"] = c["conflict_type"]
                    if c.get("reason"):
                        found_map[key]["reason"] = c["reason"]
                else:
                    found_map[key] = {
                        "series": c_series,
                        "model_name": c_model,
                        "image_status": c_status,
                        "conflict_type": c.get("conflict_type") or c_status,
                        "reason": c.get("reason") or "Flagged by Dual-Language Reconciliation Gate.",
                        "languages": ["TH", "EN"],
                    }
        except Exception as e:
            print(f"[WARNING] Could not read reconciliation report '{reconciliation_report_path}': {e}")

    return list(found_map.values())


# Compile HTML Report
def generate_html_report(added_pdfs, removed_pdfs, missing_imgs, total_non_m, models_missing_imgs, discrepancies, total_checks, api_status, files_overridden, total_rules, uncategorized=None, gdrive_status=None, image_conflicts=None, missing_img_breakdown=None):
    # Calculate health score
    health_score = 100.0
    if total_checks > 0:
        health_score = max(0.0, 100.0 - (len(discrepancies) / total_checks * 100.0))
        
    # Google Drive Status Banner
    gdrive_html = ""
    if gdrive_status:
        g_status = gdrive_status.get("status")
        g_uploaded = gdrive_status.get("uploaded_count", 0)
        g_skipped = gdrive_status.get("skipped_count", 0)
        g_failed = gdrive_status.get("failed_count", 0)
        g_msg = gdrive_status.get("message", "")
        failed_files = gdrive_status.get("failed_files", [])

        if g_status == "failed" or g_failed > 0:
            file_list_str = "<br>".join([f"• {fn}" for fn in failed_files[:10]])
            if len(failed_files) > 10:
                file_list_str += f"<br>• ... and {len(failed_files) - 10} more files."
            gdrive_html = f"""
            <div style="background-color: #fff3f3; border: 2px solid #dc3545; border-radius: 8px; padding: 16px; margin-bottom: 24px; font-family: Arial, sans-serif;">
              <h3 style="color: #dc3545; margin-top: 0; font-size: 18px; display: flex; align-items: center; gap: 8px;">
                🚨 [ALERT] การสำรองไฟล์ขึ้น Google Drive ไม่สมบูรณ์ / ขัดข้อง!
              </h3>
              <p style="margin: 0 0 10px 0; color: #721c24; font-size: 14px; line-height: 1.5;">
                <strong>สาเหตุ:</strong> {g_msg}<br>
                <strong>ไฟล์ที่อัปโหลดไม่ผ่าน:</strong> <span style="color: #dc3545; font-weight: bold;">{g_failed} ไฟล์</span> (สำเร็จ: {g_uploaded}, ข้าม: {g_skipped})<br>
                <strong>ระบบสำรองฉุกเฉิน (Fallback):</strong> ระบบได้นำไฟล์ PDF ค้างไว้บน <strong>GitHub Repository</strong> เป็นการชั่วคราวแล้ว ไฟล์จะไม่สูญหาย เมื่อแก้ไขสิทธิ์ Google Drive เสร็จแล้ว รอบถัดไปจะอัปขึ้น Drive และเคลียร์ออกจาก Git ให้โดยอัตโนมัติ
              </p>
              <div style="font-size: 12px; color: #491217; background-color: #f8d7da; padding: 10px; border-radius: 4px; max-height: 140px; overflow-y: auto;">
                {file_list_str}
              </div>
            </div>
            """
        else:
            gdrive_html = f"""
            <div style="background-color: #e8f5e9; border: 1px solid #c8e6c9; border-radius: 6px; padding: 12px 16px; margin-bottom: 20px; font-family: Arial, sans-serif;">
              <span style="color: #2e7d32; font-size: 14px; font-weight: bold;">☁️ Google Drive Backup:</span>
              <span style="color: #2e7d32; font-size: 14px;"> สำรองไฟล์ PDF ขึ้น Google Drive เรียบร้อยสมบูรณ์ ({g_uploaded} ไฟล์ใหม่ถูกอัปโหลด, {g_skipped} ไฟล์เดิมข้าม, ไม่มีไฟล์ตกค้าง)</span>
            </div>
            """

    # Uncategorized Series Alert Banner (Category 99)
    uncategorized_html = ""
    if uncategorized:
        uncategorized_html = f"""
        <div style="background-color: #fff3f3; border: 2px solid #dc3545; border-radius: 8px; padding: 16px; margin-bottom: 24px; font-family: Arial, sans-serif;">
          <h3 style="color: #dc3545; margin-top: 0; font-size: 18px; display: flex; align-items: center; gap: 8px;">
            🚨 ตรวจพบข้อมูลใน &quot;หมวด 99 (อื่นๆ)&quot; - โปรดตรวจสอบทันที!
          </h3>
          <p style="margin: 0 0 12px 0; color: #721c24; font-size: 14px; line-height: 1.5;">
            พบชื่อซีรีส์ที่ไม่ตรงตามมาตรฐานการจัดกลุ่ม (Series 2-8, X, Z, i, M, XM) ส่งผลให้ระบบจัดเข้าหมวด 99 (ตกไปอยู่ท้ายสุดของ Dropdown ใน custom.html):
          </p>
          <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
            <tr style="background-color: #f8d7da; border-bottom: 2px solid #f5c6cb; text-align: left;">
              <th style="padding: 8px;">ฐานข้อมูล</th>
              <th style="padding: 8px;">ชื่อ Series ที่พบ</th>
              <th style="padding: 8px;">ไฟล์ PDF ต้นทาง</th>
              <th style="padding: 8px;">รุ่นรถยนต์</th>
            </tr>
        """
        for item in uncategorized:
            models_str = ", ".join(item["models"][:3])
            if len(item["models"]) > 3:
                models_str += f" (+{len(item['models'])-3} รุ่น)"
            uncategorized_html += f"""
            <tr style="border-bottom: 1px solid #f5c6cb; vertical-align: top;">
              <td style="padding: 8px; font-weight: bold;">{item['database']}</td>
              <td style="padding: 8px; font-weight: bold; color: #dc3545;">{item['series']}</td>
              <td style="padding: 8px;">{item['pdf_source']}</td>
              <td style="padding: 8px;">{models_str}</td>
            </tr>
            """
        uncategorized_html += "</table></div>"

    # TH/EN Image Conflict & Pending Paired Language Banner
    image_conflicts_html = ""
    if image_conflicts:
        blocked_count = sum(1 for c in image_conflicts if c.get("image_status") == "blocked_th_en_conflict")
        pending_count = sum(1 for c in image_conflicts if c.get("image_status") == "pending_paired_language")
        border_col = "#dc3545" if blocked_count > 0 else "#e67e22"
        bg_col = "#fff3f3" if blocked_count > 0 else "#fff8eb"
        head_bg = "#f8d7da" if blocked_count > 0 else "#ffe8cc"
        title_txt = (
            f"🚨 [ALERT] ตรวจพบความขัดแย้ง TH/EN ของรูปภาพ ({blocked_count} รุ่นถูกระงับ, {pending_count} รุ่นรอจับคู่ภาษา)"
            if blocked_count > 0
            else f"⏳ [PENDING] มี {pending_count} รุ่นรอไฟล์โบรชัวร์คู่ภาษา (TH/EN Paired Update Gate)"
        )
        image_conflicts_html = f"""
        <div style="background-color: {bg_col}; border: 2px solid {border_col}; border-radius: 8px; padding: 16px; margin-bottom: 24px; font-family: Arial, sans-serif;">
          <h3 style="color: {border_col}; margin-top: 0; font-size: 18px;">{html_lib.escape(title_txt)}</h3>
          <p style="margin: 0 0 12px 0; color: #5c2a2a; font-size: 14px; line-height: 1.5;">
            ระบบได้หยุดการดึงรูปสีอัตโนมัติสำหรับรุ่นที่มีความขัดแย้งระหว่างข้อมูล TH และ EN เพื่อป้องกันรูปภาพไม่ตรงกันทั้งสองภาษา:
          </p>
          <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
            <tr style="background-color: {head_bg}; border-bottom: 2px solid {border_col}; text-align: left;">
              <th style="padding: 8px;">รุ่นรถยนต์</th>
              <th style="padding: 8px;">สถานะ</th>
              <th style="padding: 8px;">ประเภท</th>
              <th style="padding: 8px;">รายละเอียด</th>
            </tr>
        """
        for item in image_conflicts:
            st = html_lib.escape(str(item.get("image_status", "")))
            md = html_lib.escape(str(item.get("model_name", "")))
            ct = html_lib.escape(str(item.get("conflict_type", "")))
            rs = html_lib.escape(str(item.get("reason", "")))
            image_conflicts_html += f"""
            <tr style="border-bottom: 1px solid #f5c6cb; vertical-align: top;">
              <td style="padding: 8px; font-weight: bold;">{md}</td>
              <td style="padding: 8px; font-weight: bold; color: {border_col};">{st}</td>
              <td style="padding: 8px;">{ct}</td>
              <td style="padding: 8px;">{rs}</td>
            </tr>
            """
        image_conflicts_html += "</table></div>"

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

    # Missing images breakdown (2A Broken vs 2B Pending BMW Configurator, excluding blocked models from broken)
    if missing_img_breakdown is None:
        fallback_broken = missing_imgs if isinstance(missing_imgs, dict) else {}
        broken_imgs = fallback_broken
        pending_imgs = {}
        blocked_imgs = {}
        complete_count = max(0, total_non_m - models_missing_imgs)
        broken_count = len(broken_imgs) if broken_imgs else models_missing_imgs
        pending_count = 0
        blocked_count = 0
    else:
        broken_imgs = missing_img_breakdown.get("broken", {})
        pending_imgs = missing_img_breakdown.get("pending_configurator", {})
        blocked_imgs = missing_img_breakdown.get("blocked", {})
        complete_count = missing_img_breakdown.get("complete_count", max(0, total_non_m - models_missing_imgs))
        broken_count = missing_img_breakdown.get("broken_count", len(broken_imgs))
        pending_count = missing_img_breakdown.get("pending_count", len(pending_imgs))
        blocked_count = missing_img_breakdown.get("blocked_count", len(blocked_imgs))

    if broken_count > 0 or blocked_count > 0:
        coverage_color = "#dc3545"
    elif pending_count > 0:
        coverage_color = "#f0ad4e"
    else:
        coverage_color = "#28a745"

    if broken_count == 0 and pending_count == 0 and blocked_count == 0:
        coverage_sublabel = "(Non-M models with images)"
    else:
        coverage_sublabel = (
            f"({complete_count} complete | {broken_count} broken | "
            f"{pending_count} pending configurator | {blocked_count} blocked)"
        )

    def _render_img_issue_table(items_dict, text_color):
        tbl = "<table style='width: 100%; border-collapse: collapse; margin-bottom: 16px; font-family: Arial, sans-serif;'>"
        tbl += "<tr style='background-color: #f8f9fa; border-bottom: 2px solid #dee2e6; text-align: left;'><th style='padding: 8px; width: 30%;'>Model</th><th style='padding: 8px;'>Details / Missing Colors</th></tr>"
        for m_name, details in items_dict.items():
            esc_model = html_lib.escape(str(m_name))
            details_str = "<br>".join([f"• {html_lib.escape(str(d))}" for d in details])
            tbl += f"<tr style='border-bottom: 1px solid #dee2e6; vertical-align: top;'><td style='padding: 8px; font-weight: bold;'>{esc_model}</td><td style='padding: 8px; color: {text_color};'>{details_str}</td></tr>"
        tbl += "</table>"
        return tbl

    missing_imgs_html = "<h4 style='margin: 12px 0 6px 0; color: #0b132b; font-family: Arial, sans-serif;'>2A. Broken / Missing Images</h4>"
    if not broken_imgs:
        missing_imgs_html += "<p style='color: #28a745; font-weight: bold; font-family: Arial, sans-serif;'>🎉 Zero broken/unexplained missing paintwork images on disk!</p>"
    else:
        missing_imgs_html += _render_img_issue_table(broken_imgs, "#d9534f")

    missing_imgs_html += "<h4 style='margin: 14px 0 6px 0; color: #8a6d3b; font-family: Arial, sans-serif;'>2B. Pending BMW Configurator</h4>"
    if not pending_imgs:
        missing_imgs_html += "<p style='color: #6c757d; font-family: Arial, sans-serif;'>⏳ Pending BMW Configurator: 0 models waiting.</p>"
    else:
        missing_imgs_html += "<p style='color: #8a6d3b; font-size: 13px; margin: 0 0 8px 0; font-family: Arial, sans-serif;'>รุ่นที่ Spec Guard / Auto-Scraper รอข้อมูลหรือรูปสีใหม่จาก BMW Thailand Online Configurator (ระบบจะลองดึงใหม่อัตโนมัติทุกวัน โดยไม่นับเป็นรูปเสีย):</p>"
        missing_imgs_html += _render_img_issue_table(pending_imgs, "#8a6d3b")

    if blocked_imgs:
        blocked_names = html_lib.escape(", ".join(blocked_imgs.keys()))
        missing_imgs_html += f"<p style='color: #6c757d; font-size: 13px; font-family: Arial, sans-serif;'>🚫 Blocked / Unpaired TH-EN models ({len(blocked_imgs)}: {blocked_names}) are excluded from Broken Images and listed in the TH/EN Conflict Gate above.</p>"

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
            <div style="font-size: 24px; font-weight: bold; color: {coverage_color};">{complete_count}/{total_non_m}</div>
            <div style="font-size: 11px; color: #6c757d;">{coverage_sublabel}</div>
          </div>

          <div style="background-color: #f8f9fa; border-left: 4px solid #5bc0be; padding: 15px; border-radius: 4px;">
            <div style="font-size: 12px; color: #6c757d; font-weight: bold; text-transform: uppercase;">Manual Overrides</div>
            <div style="font-size: 24px; font-weight: bold; color: #333;">{total_rules} rules</div>
            <div style="font-size: 11px; color: #6c757d;">({files_overridden} source brochures corrected)</div>
          </div>

        </div>

        <!-- Main Content -->
        <div style="padding: 20px; font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
          
          {gdrive_html}
          {uncategorized_html}
          {image_conflicts_html}

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

    # Load custom/archived catalogs if present
    custom_th_data = []
    custom_en_data = []
    if os.path.exists(CUSTOM_TH_CATALOG):
        try:
            with open(CUSTOM_TH_CATALOG, encoding="utf-8") as f:
                custom_th_data = json.load(f)
        except Exception as e:
            print(f"[WARNING] Failed to load custom TH catalog: {e}")
    if os.path.exists(CUSTOM_EN_CATALOG):
        try:
            with open(CUSTOM_EN_CATALOG, encoding="utf-8") as f:
                custom_en_data = json.load(f)
        except Exception as e:
            print(f"[WARNING] Failed to load custom EN catalog: {e}")
        
    # Gather report data
    print("[AUDIT] Checking PDF brochure updates...")
    added_pdfs, removed_pdfs = audit_pdf_changes()
    
    print("[AUDIT] Auditing missing color images...")
    img_breakdown = categorize_missing_images(th_data)
    missing_imgs, total_non_m, models_missing_imgs = audit_missing_images(th_data)
    
    print("[AUDIT] Running data discrepancy checks...")
    discrepancies, total_checks = audit_data_discrepancies(th_data, en_data)
    
    print("[AUDIT] Auditing Category 99 (Uncategorized series)...")
    uncategorized = audit_uncategorized_series(th_data, en_data, custom_th_data, custom_en_data)
    if uncategorized:
        print(f"[ALERT] Found {len(uncategorized)} entries categorized as Category 99 (Uncategorized)!")
    else:
        print("[AUDIT] All series correctly categorized (0 in Category 99).")

    print("[AUDIT] Fetching API health parameters...")
    api_status = check_api_health()
    
    print("[AUDIT] Fetching override rules...")
    files_overridden, total_rules = check_overrides_stats()
    
    print("[AUDIT] Checking Google Drive backup status...")
    gdrive_status = audit_gdrive_status()

    print("[AUDIT] Auditing TH/EN image conflicts & paired update status...")
    image_conflicts = audit_image_conflicts(th_data, en_data)
    if image_conflicts:
        print(f"[ALERT] Found {len(image_conflicts)} model(s) with TH/EN image conflict or pending paired update!")
    else:
        print("[AUDIT] No TH/EN image conflicts detected (0 blocked/pending).")

    # Generate HTML Report body
    print("[REPORT] Formatting HTML body...")
    html_body = generate_html_report(
        added_pdfs, removed_pdfs, missing_imgs, 
        total_non_m, models_missing_imgs, 
        discrepancies, total_checks, 
        api_status, files_overridden, total_rules,
        uncategorized=uncategorized,
        gdrive_status=gdrive_status,
        image_conflicts=image_conflicts,
        missing_img_breakdown=img_breakdown
    )
    
    # Send via Google Apps Script (GAS) Web App
    if not GAS_WEBAPP_URL or not GAS_SECRET_TOKEN:
        print("[WARNING] GAS_WEBAPP_URL or GAS_SECRET_TOKEN is not configured. Report output saved to 'daily_report_preview.html'.")
        with open("daily_report_preview.html", "w", encoding="utf-8") as f:
            f.write(html_body)
        sys.exit(0)
        
    print("[POST] Sending email report to Google Apps Script Web App...")
    subject_prefix = ""
    if gdrive_status and (gdrive_status.get("status") == "failed" or gdrive_status.get("failed_count", 0) > 0):
        subject_prefix += "🚨 [ALERT: GDrive Backup Failed] "
    if uncategorized:
        subject_prefix += f"🚨 [ALERT: {len(uncategorized)} Uncategorized Series (หมวด 99)] "

    if image_conflicts:
        blocked_cnt = sum(1 for c in image_conflicts if c.get("image_status") == "blocked_th_en_conflict")
        pending_cnt = sum(1 for c in image_conflicts if c.get("image_status") == "pending_paired_language")
        if blocked_cnt > 0:
            subject_prefix += f"🚨 [ALERT: {blocked_cnt} TH/EN Image Conflict(s)] "
        elif pending_cnt > 0:
            subject_prefix += f"⏳ [PENDING: {pending_cnt} Unpaired Update(s)] "

    payload = {
        "secret": GAS_SECRET_TOKEN,
        "subject": f"{subject_prefix}🚗 [BMW Specsheet] Daily Monitor Report ({len(discrepancies)} Issues)",
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
