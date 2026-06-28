import json
import os
from datetime import datetime

en_db_path = "bmw_master_specs_en.json"
th_db_path = "bmw_master_specs.json"

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

    # Generate Markdown Report
    date_str = datetime.now().strftime("%Y-%m-%d")
    
    report_md = f"# \u2709\ufe0f [BMW Specsheet Bot] Auto-Update Report - {date_str}\n\n"
    report_md += "> [!NOTE]\n"
    report_md += "> ระบบตรวจสอบสเปกอัตโนมัติประจำวันทำงานเสร็จสิ้นแล้ว ไฟล์ PDF สเปกชีทใหม่และฐานข้อมูลได้รับการอัปเดตลงบน GitHub เรียบร้อยแล้ว\n\n"
    report_md += "---\n\n"
    report_md += "## \u2611\ufe0f 1. สรุปภาพรวมฐานข้อมูล (Database Stats)\n"
    report_md += f"* **โบรชัวร์ภาษาไทย (TH):** {total_th_pdfs} ไฟล์\n"
    report_md += f"* **โบรชัวร์ภาษาอังกฤษ (EN):** {total_en_pdfs} ไฟล์\n"
    report_md += f"* **สถานะการเปรียบเทียบ:** พบบันทึกข้อขัดแย้งออปชันและสเปกข้ามภาษาทั้งหมด **{len(flags)} จุด**\n\n"
    report_md += "---\n\n"

    if flags:
        report_md += "## \u26a0\ufe0f 2. รายการจุดขัดแย้งที่ต้องตรวจสอบ (Flags Detected)\n"
        report_md += "กรุณาเปรียบเทียบและยืนยันข้อมูลออปชันที่ขัดแย้งกันดังตารางต่อไปนี้:\n\n"
        report_md += "| ลำดับ | รุ่นรถยนต์ (ไฟล์ต้นทาง) | หมวดหมู่ / สเปก | รายละเอียดความขัดแย้ง |\n"
        report_md += "| :---: | :--- | :--- | :--- |\n"
        for idx, f in enumerate(flags, 1):
            clean_reason = f['reason'].replace('|', '\\|')
            report_md += f"| **{idx}** | **{f['model']}**<br>`({f['pdf']})` | {f['category']} / {f['topic']} | {clean_reason} |\n"
            
        report_md += "\n---\n"
    else:
        report_md += "## \u2705 2. ไม่พบจุดขัดแย้งใดๆ (No Mismatches)\nข้อมูลสเปกไทยและอังกฤษสอดคล้องกันอย่างสมบูรณ์แบบ!\n\n---\n"

    report_md += "## \u26a0\ufe0f 3. คำแนะนำถัดไป (Next Steps)\n"
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
