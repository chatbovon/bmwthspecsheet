import json
import os
from datetime import datetime

en_db_path = "bmw_master_specs_en.json"
th_db_path = "bmw_master_specs.json"

def is_color_present(spec_color, images_dict):
    if not images_dict:
        return False
    norm_spec = spec_color.lower().strip()
    norm_spec_clean = norm_spec.replace("metallic", "").replace("solid", "").strip()
    
    for key in images_dict.keys():
        k = key.lower().strip()
        k_clean = k.replace("metallic", "").replace("solid", "").replace("m ", "").replace("individual ", "").strip()
        
        if (norm_spec == k or 
            norm_spec.replace(" ", "") == k.replace(" ", "") or
            norm_spec in k or 
            k in norm_spec or
            norm_spec_clean == k_clean):
            return True
            
    return False

def audit_images(db_data):
    missing_entirely = []
    incomplete = []
    complete = []
    
    for series_obj in db_data:
        series_name = series_obj.get("series", "Unknown Series")
        pdf_source = series_obj.get("pdf_source", "unknown.pdf")
                
        for model in series_obj.get("models", []):
            model_name = model.get("model_name", "")
            
            # Skip if this is archived
            if model.get("is_custom_archived", False):
                continue
                
            # Find paintwork category for this specific model
            paint_specs = []
            for cat in model.get("specifications", []):
                cat_name = cat.get("category", "")
                if "paintwork" in cat_name.lower() or "สีตัวถัง" in cat_name.lower():
                    paint_specs = cat.get("details", [])
                    break
            
            # Find expected colors (where value is not "-" and not empty)
            expected_colors = []
            for spec in paint_specs:
                color_name = spec.get("topic", "")
                val = spec.get("value", "")
                if color_name and val and val.strip() != "-":
                    expected_colors.append(color_name)
                    
            if not expected_colors:
                # No paint colors listed or needed
                continue
                
            images_dict = model.get("images")
            
            if not images_dict:
                missing_entirely.append({
                    "series": series_name,
                    "model": model_name,
                    "pdf": pdf_source,
                    "expected": expected_colors
                })
            else:
                missing_colors = []
                for color in expected_colors:
                    if not is_color_present(color, images_dict):
                        missing_colors.append(color)
                        
                if missing_colors:
                    incomplete.append({
                        "series": series_name,
                        "model": model_name,
                        "pdf": pdf_source,
                        "missing": missing_colors,
                        "expected": expected_colors,
                        "found_count": len(images_dict)
                    })
                else:
                    complete.append({
                        "series": series_name,
                        "model": model_name
                    })
                    
    return missing_entirely, incomplete, complete

def main():
    if not os.path.exists(en_db_path) or not os.path.exists(th_db_path):
        print("Missing database files. Cannot generate report.")
        return

    with open(en_db_path, "r", encoding="utf-8") as f:
        db_en = json.load(f)
    with open(th_db_path, "r", encoding="utf-8") as f:
        db_th = json.load(f)

    # Count total PDFs
    total_th_pdfs = len(db_th)
    total_en_pdfs = len(db_en)

    # Gather flags
    flags = []
    for entry in db_en:
        pdf = entry.get("pdf_source", "")
        for flag in entry.get("low_confidence_flags", []):
            if flag.get("type") == "Cross-DB Discrepancy":
                flags.append({
                    "pdf": pdf,
                    "model": flag.get("model_name"),
                    "category": flag.get("category"),
                    "topic": flag.get("topic"),
                    "reason": flag.get("reason")
                })

    # Run image audit
    missing_entirely, incomplete, complete = audit_images(db_th)

    # Generate Markdown Report
    date_str = datetime.now().strftime("%Y-%m-%d")
    
    report_md = f"# ✉️ [BMW Specsheet Bot] Auto-Update Report - {date_str}\n\n"
    report_md += "> [./report.md]\n"
    report_md += "> ระบบตรวจสอบสเปกและรูปภาพประจำวันทำงานเสร็จสิ้นแล้ว ไฟล์โบรชัวร์และฐานข้อมูลได้รับการอัปเดตลงบน GitHub เรียบร้อยแล้ว\n\n"
    report_md += "---\n\n"
    report_md += "## ☑️ 1. สรุปภาพรวมฐานข้อมูล (Database Stats)\n"
    report_md += f"* **โบรชัวร์ภาษาไทย (TH):** {total_th_pdfs} ไฟล์\n"
    report_md += f"* **โบรชัวร์ภาษาอังกฤษ (EN):** {total_en_pdfs} ไฟล์\n"
    report_md += f"* **สถานะข้อมูลขัดแย้ง:** พบบันทึกข้อขัดแย้งออปชันข้ามภาษาทั้งหมด **{len(flags)} จุด**\n"
    report_md += f"* **สถานะรูปภาพตัวอย่างรถ:** มีรูปภาพครบถ้วน **{len(complete)} รุ่น** | มีรูปไม่ครบ **{len(incomplete)} รุ่น** | ไม่มีรูปภาพเลย **{len(missing_entirely)} รุ่น**\n\n"
    report_md += "---\n\n"

    # Mismatch Table
    if flags:
        report_md += "## ⚠️ 2. รายการจุดขัดแย้งที่ต้องตรวจสอบ (Flags Detected)\n"
        report_md += "กรุณาเปรียบเทียบและยืนยันข้อมูลออปชันที่ขัดแย้งกันดังตารางต่อไปนี้:\n\n"
        report_md += "| ลำดับ | รุ่นรถยนต์ (ไฟล์ต้นทาง) | หมวดหมู่ / สเปก | รายละเอียดความขัดแย้ง |\n"
        report_md += "| :---: | :--- | :--- | :--- |\n"
        for idx, f in enumerate(flags, 1):
            clean_reason = f['reason'].replace('|', '\\|')
            report_md += f"| **{idx}** | **{f['model']}**<br>`({f['pdf']})` | {f['category']} / {f['topic']} | {clean_reason} |\n"
        report_md += "\n---\n"
    else:
        report_md += "## ✅ 2. ไม่พบจุดขัดแย้งข้อมูล (No Mismatches)\nข้อมูลสเปกไทยและอังกฤษสอดคล้องกันอย่างสมบูรณ์แบบ!\n\n---\n"

    # Image Audit Section
    report_md += "## 🖼️ 3. รายงานสถานะรูปภาพตัวอย่างรถยนต์ (Vehicle Image Assets Status)\n"
    
    if missing_entirely or incomplete:
        report_md += "มีรายละเอียดรุ่นที่รูปภาพยังไม่สมบูรณ์ดังต่อไปนี้:\n\n"
        report_md += "| สถานะ | ซีรีส์ / รุ่นรถยนต์ | รายละเอียดไฟล์ภาพขาดหาย |\n"
        report_md += "| :---: | :--- | :--- |\n"
        
        # List Missing Entirely
        for item in missing_entirely:
            expected_list = ", ".join(item['expected'])
            report_md += f"| 🔴 **ไม่มีรูปเลย** | **{item['series']}**<br>{item['model']} | ขาดรูปภาพทั้งหมดสำหรับสี: *{expected_list}* |\n"
            
        # List Incomplete
        for item in incomplete:
            missing_list = ", ".join(item['missing'])
            report_md += f"| 🟡 **มีรูปไม่ครบ** | **{item['series']}**<br>{item['model']} | พบแล้ว {item['found_count']} สี | ขาดรูปสี: *{missing_list}* |\n"
            
        report_md += "\n"
    else:
        report_md += "🎉 **รูปภาพตัวอย่างรถยนต์ครบถ้วน 100% ครบทุกรุ่นย่อยและทุกสีเรียบร้อยแล้ว!**\n\n"
        
    if complete:
        report_md += "<details>\n<summary><b>🔍 รายการรุ่นรถยนต์ที่ภาพสมบูรณ์แล้ว (Click to expand)</b></summary>\n\n"
        for item in complete:
            report_md += f"* ✅ {item['series']} | {item['model']}\n"
        report_md += "</details>\n\n"
        
    # Scraper Warnings Section
    warnings_file = "scratch/scraper_warnings.json"
    if os.path.exists(warnings_file):
        try:
            with open(warnings_file, "r", encoding="utf-8") as f:
                warnings_data = json.load(f)
            if warnings_data:
                report_md += "## ⚠️ 4. รายงานระบบกวาดรูปภาพรถยนต์ล้มเหลว (Image Scraper Warnings)\n"
                report_md += "พบการกวาดรูปภาพล้มเหลวเนื่องจากระดับคะแนนความมั่นใจต่ำ (Score < 80) หรือไม่พบตัวเลือก ดังตารางต่อไปนี้:\n\n"
                report_md += "| รุ่นรถยนต์ | คะแนนสูงสุดที่พบ | ปุ่มตัวเลือกบนเว็บที่ใกล้เคียงที่สุด |\n"
                report_md += "| :--- | :---: | :--- |\n"
                for w in warnings_data:
                    report_md += f"| **{w['model_name']}** | {w['best_score']} / 150 | {w['best_candidate'] or 'ไม่พบปุ่มตัวเลือกเลย'} |\n"
                report_md += "\n---\n\n"
            
            # Clean up the warnings file after compile
            os.remove(warnings_file)
        except Exception as e:
            print("Error processing scraper warnings:", e)

    report_md += "## ⚠️ 5. คำแนะนำถัดไป (Next Steps)\n"
    report_md += "1. ดึงข้อมูลล่าสุดลงในเครื่องคอมพิวเตอร์ของคุณโดยใช้คำสั่ง:\n"
    report_md += "   ```bash\n"
    report_md += "   git pull\n"
    report_md += "   ```\n"
    report_md += "2. รันเซิร์ฟเวอร์โลคอลเพื่อตรวจสอบความถูกต้องบนหน้าเว็บสเปกชีทได้ทันทีครับ\n"

    with open("report.md", "w", encoding="utf-8") as f:
        f.write(report_md)
    print("report.md generated successfully.")

if __name__ == "__main__":
    main()
