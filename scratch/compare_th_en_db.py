import json
import os
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

db_th_path = r"bmw_master_specs.json"
db_en_path = r"bmw_master_specs_en.json"
report_path = r"specsheet_audit_report.md"

TOPIC_MAP = {
    # Engine & Performance
    "ความจุกระบอกสูบ (ซีซี)": "displacement (cc)",
    "กระบอกสูบ": "displacement (cc)",
    "กำลังสูงสุด (กิโลวัตต์/แรงม้า/รอบต่อนาที)": "max. output (kw/hp/rpm)",
    "กำลังสูงสุด": "max. output (kw/hp/rpm)",
    "แรงบิดสูงสุด (นิวตันเมตร/รอบต่อนาที)": "max. torque (nm/rpm)",
    "แรงบิดสูงสุด": "max. torque (nm/rpm)",
    "ความเร็วสูงสุด (กิโลเมตร/ชั่วโมง)": "top speed (km/h)",
    "ความเร็วสูงสุด": "top speed (km/h)",
    "อัตราเร่ง 0 - 100 กิโลเมตร/ชั่วโมง (วินาที)": "acceleration 0 - 100 km/h (s)",
    "อัตราเร่ง": "acceleration 0 - 100 km/h (s)",
    
    # Fuel & CO2
    "อัตราสิ้นเปลืองน้ำมันเชื้อเพลิงเฉลี่ย - อ้างอิงผล ECO Sticker (กิโลเมตร/ลิตร)": "fuel consumption combined (km/l)",
    "ระดับการปล่อย CO2 เฉลี่ย (กรัม/กิโลเมตร)": "co2 emission combined (g/km)",
    
    # Wheels & Tyres
    "ขนาดล้อ": "wheel size",
    "ขนาดยาง": "tyre size",
    
    # Dimension
    "มิติรถยนต์ (ยาว x กว้าง x สูง) (มม.)": "dimension (l x w x h) (mm)",
    "ยาว x กว้าง x สูง (มม.)": "dimension (l x w x h) (mm)",
    "ปริมาตรในการบรรจุของห้องเก็บสัมภาระ (ลิตร)": "luggage compartment capacity (l)",
    "น้ำหนักรถสุทธิ (กก.)": "unladen weight (kg)",
    
    # References
    "วันที่พิมพ์เอกสาร": "publication date",
    "รหัสแพ็กเกจ": "package code"
}

def map_category(cat):
    if not cat:
        return ""
    cat = cat.lower().strip()
    if "เครื่องยนต์" in cat or "engine" in cat:
        return "engine and performance"
    elif "อัตราสิ้นเปลือง" in cat or "co2" in cat or "fuel" in cat:
        return "fuel consumption and co2"
    elif "ล้อ" in cat or "ยาง" in cat or "wheel" in cat or "tyre" in cat:
        return "wheels and tyres"
    elif "มิติ" in cat or "dimension" in cat:
        return "dimension"
    elif "ระบบขับเคลื่อน" in cat or "transmission" in cat or "drivetrain" in cat:
        return "transmission and technology"
    elif "paintwork" in cat or "สีตัวถัง" in cat:
        return "paintwork & upholstery"
    elif "ภายนอก" in cat or "exterior" in cat:
        return "exterior"
    elif "ภายใน" in cat or "interior" in cat:
        return "interior"
    elif "บันเทิง" in cat or "สื่อสาร" in cat or "entertainment" in cat or "communication" in cat:
        return "entertainment and communication"
    elif "ปลอดภัย" in cat or "safety" in cat:
        return "safety"
    elif "ชุดตกแต่ง" in cat or "line" in cat or "package" in cat or "แพ็กเกจ" in cat:
        return "line / package"
    elif "เอกสารอ้างอิง" in cat or "document" in cat:
        return "document references"
    elif "ตัวเลือกพิเศษ" in cat or "special option" in cat:
        return "special options"
    elif "charging" in cat or "ชาร์จ" in cat:
        if "ac" in cat or "กระแสสลับ" in cat:
            if "time" in cat or "ระยะเวลา" in cat:
                return "ac charging time"
            return "ac charging"
        elif "dc" in cat or "กระแสตรง" in cat:
            if "time" in cat or "ระยะเวลา" in cat:
                return "dc charging time"
            return "dc charging"
        return "charging"
    return cat

def get_mapped_topic_name(topic):
    if not topic:
        return ""
    topic_clean = topic.strip().lower()
    # Check in TOPIC_MAP
    mapped = TOPIC_MAP.get(topic.strip())
    if mapped:
        return mapped.lower()
    # Direct or substring check
    for k, v in TOPIC_MAP.items():
        if k.lower() == topic_clean or v.lower() == topic_clean:
            return v.lower()
    return topic_clean

def normalize_model_name(name):
    if not name:
        return ""
    normalized = name.replace("BMW", "").replace("bmw", "").lower()
    return "".join(normalized.split())

def clean_value(val):
    if not val:
        return "-"
    val = val.strip().lower()
    if val in ["-", "no", "not available", "not available"]:
        return "-"
    if val in ["■", "yes", "standard", "yes"]:
        return "■"
    
    val = val.replace("×", "x")
    th_months = {
        "มกราคม": "january", "กุมภาพันธ์": "february", "มีนาคม": "march",
        "เมษายน": "april", "พฤษภาคม": "may", "มิถุนายน": "june",
        "กรกฎาคม": "july", "สิงหาคม": "august", "กันยายน": "september",
        "ตุลาคม": "october", "พฤศจิกายน": "november", "ธันวาคม": "december"
    }
    for th_m, en_m in th_months.items():
        val = val.replace(th_m, en_m)
        
    match_be = re.search(r'(25\d{2}|26\d{2})', val)
    if match_be:
        be_yr = int(match_be.group(1))
        ce_yr = be_yr - 543
        val = val.replace(str(be_yr), str(ce_yr))
        
    val = val.replace(",", "").replace(" ", "")
    val = val.replace("ซีซี", "").replace("มม.", "").replace("กิโลวัตต์", "").replace("แรงม้า", "").replace("รอบต่อนาที", "").replace("นิวตันเมตร", "").replace("กิโลเมตร/ชั่วโมง", "").replace("วินาที", "").replace("ลิตร", "").replace("กก.", "")
    val = val.replace("cc", "").replace("mm", "").replace("kw", "").replace("hp", "").replace("ps", "").replace("rpm", "").replace("nm", "").replace("km/h", "").replace("s", "").replace("l", "").replace("kg", "")
    val = val.replace("tyres", "").replace("tyre", "").replace("ยาง", "")
    val = val.replace("front:", "").replace("rear:", "").replace("front", "").replace("rear", "")
    val = val.replace("ล้อหน้า:", "").replace("ล้อหลัง:", "").replace("ล้อหน้า", "").replace("ล้อหลัง", "")
    return val

def extract_digits(val):
    if not val:
        return []
    # Remove commas and extract all numbers (integer and decimal)
    clean = val.replace(",", "")
    return re.findall(r'\d+', clean)

def is_paintwork_value_similar(val_th, val_en):
    if val_th.strip() == "-" and val_en.strip() == "-":
        return True
    if val_th.strip() == "-" or val_en.strip() == "-":
        return False
        
    val_th_norm = val_th.lower().replace("leather", "").replace("vernasca", "").replace("'", "").replace("\"", "").replace("หนัง", "").strip()
    val_en_norm = val_en.lower().replace("leather", "").replace("vernasca", "").replace("'", "").replace("\"", "").replace("หนัง", "").strip()
    
    if val_th_norm == val_en_norm:
        return True
    if val_th_norm in val_en_norm or val_en_norm in val_th_norm:
        return True
        
    th_words = set(re.findall(r'\w+', val_th_norm))
    en_words = set(re.findall(r'\w+', val_en_norm))
    
    colors = {"black", "mocha", "cognac", "red", "oyster", "beige", "grey", "gray", "white", "brown", "blue", "tacora", "coral", "sensatec", "veganza", "merino"}
    matched_th = th_words.intersection(colors)
    matched_en = en_words.intersection(colors)
    
    if matched_th and matched_th == matched_en:
        return True
    return False

def main():
    if not os.path.exists(db_th_path) or not os.path.exists(db_en_path):
        print("[ERROR] One of the database files is missing.")
        return

    with open(db_th_path, "r", encoding="utf-8") as f:
        db_th = json.load(f)
    with open(db_en_path, "r", encoding="utf-8") as f:
        db_en = json.load(f)

    # Build lookup for Thai database by pdf_source
    th_lookup = {}
    for entry in db_th:
        pdf = entry.get("pdf_source", "")
        if pdf and "_TH" in pdf:
            prefix = pdf.split("_TH")[0]
            th_lookup[prefix] = entry

    discrepancies_count = 0
    audit_reports = []  # List of critical technical issues for specsheet_audit_report.md

    for en_entry in db_en:
        pdf_en = en_entry.get("pdf_source", "")
        if not pdf_en or "_EN" not in pdf_en:
            continue
            
        prefix = pdf_en.split("_EN")[0]
        th_entry = th_lookup.get(prefix)
        if not th_entry:
            continue

        print(f"\n[COMPARE] Comparing EN: {pdf_en} <-> TH: {th_entry.get('pdf_source')}")

        # Map TH models by normalized name
        th_models = {}
        for tm in th_entry.get("models", []):
            norm_name = normalize_model_name(tm.get("model_name"))
            if norm_name:
                th_models[norm_name] = tm

        # Clear existing Cross-DB Discrepancy flags in the English entry
        if "low_confidence_flags" in en_entry:
            en_entry["low_confidence_flags"] = [f for f in en_entry["low_confidence_flags"] if f.get("type") != "Cross-DB Discrepancy"]
        else:
            en_entry["low_confidence_flags"] = []

        # Clear existing Cross-DB Discrepancy flags in the Thai entry
        if "low_confidence_flags" in th_entry:
            th_entry["low_confidence_flags"] = [f for f in th_entry["low_confidence_flags"] if f.get("type") != "Cross-DB Discrepancy"]
        else:
            th_entry["low_confidence_flags"] = []

        for en_model in en_entry.get("models", []):
            model_name = en_model.get("model_name")
            norm_name = normalize_model_name(model_name)
            
            th_model = th_models.get(norm_name)
            if not th_model:
                print(f"  [WARNING] Model '{model_name}' not found in Thai brochure.")
                continue

            # Compare specifications category by category strictly index-by-index
            en_specs = en_model.get("specifications", [])
            th_specs = th_model.get("specifications", [])

            max_cat_len = max(len(en_specs), len(th_specs))
            if len(en_specs) != len(th_specs):
                reason = f"Category count mismatch: English has {len(en_specs)} categories, Thai has {len(th_specs)} categories"
                print(f"    [MISMATCH] {model_name} - {reason}")
                flag_data = {
                    "model_name": model_name,
                    "category": "All",
                    "topic": "Category Count",
                    "type": "Cross-DB Discrepancy",
                    "reason": reason
                }
                en_entry["low_confidence_flags"].append(flag_data)
                th_entry["low_confidence_flags"].append(flag_data)
                audit_reports.append({
                    "pdf": th_entry.get("pdf_source"),
                    "model": model_name,
                    "category": "General",
                    "type": "Category Count/Ordering Mismatch (จำนวน/ลำดับหมวดหมู่ต่างกัน)",
                    "detail": reason
                })
                discrepancies_count += 1

            for i in range(max_cat_len):
                if i >= len(en_specs):
                    # Extra category in Thai specs
                    cat_th = th_specs[i].get("category", "")
                    reason = f"Extra category in Thai brochure: '{cat_th}' (not present in English specs)"
                    print(f"    [MISMATCH] {model_name} - {reason}")
                    audit_reports.append({
                        "pdf": th_entry.get("pdf_source"),
                        "model": model_name,
                        "category": cat_th,
                        "type": "Category Count/Ordering Mismatch (จำนวน/ลำดับหมวดหมู่ต่างกัน)",
                        "detail": reason
                    })
                    discrepancies_count += 1
                    continue
                if i >= len(th_specs):
                    # Extra category in English specs
                    cat_en = en_specs[i].get("category", "")
                    reason = f"Missing category in Thai brochure: '{cat_en}' (present in English specs)"
                    print(f"    [MISMATCH] {model_name} - {reason}")
                    audit_reports.append({
                        "pdf": th_entry.get("pdf_source"),
                        "model": model_name,
                        "category": cat_en,
                        "type": "Category Count/Ordering Mismatch (จำนวน/ลำดับหมวดหมู่ต่างกัน)",
                        "detail": reason
                    })
                    discrepancies_count += 1
                    continue

                es = en_specs[i]
                ts = th_specs[i]

                cat_en = es.get("category", "")
                cat_th = ts.get("category", "")

                mapped_cat_en = map_category(cat_en)
                mapped_cat_th = map_category(cat_th)

                if mapped_cat_en != mapped_cat_th:
                    reason = f"Category mismatch/ordering difference at position {i+1}: English has '{cat_en}', Thai has '{cat_th}'"
                    print(f"    [MISMATCH] {model_name} - {reason}")
                    flag_data = {
                        "model_name": model_name,
                        "category": f"{cat_th} / {cat_en}",
                        "topic": "Category Position",
                        "type": "Cross-DB Discrepancy",
                        "reason": reason
                    }
                    en_entry["low_confidence_flags"].append(flag_data)
                    th_entry["low_confidence_flags"].append(flag_data)
                    audit_reports.append({
                        "pdf": th_entry.get("pdf_source"),
                        "model": model_name,
                        "category": cat_en,
                        "type": "Category Count/Ordering Mismatch (จำนวน/ลำดับหมวดหมู่ต่างกัน)",
                        "detail": reason
                    })
                    discrepancies_count += 1
                    continue

                details_en = es.get("details", [])
                details_th = ts.get("details", [])

                max_detail_len = max(len(details_en), len(details_th))
                if len(details_en) != len(details_th):
                    reason = f"Topic count mismatch in category '{cat_en}': English has {len(details_en)} topics, Thai has {len(details_th)} topics"
                    print(f"    [MISMATCH] {model_name} / {cat_en} - {reason}")
                    flag_data = {
                        "model_name": model_name,
                        "category": cat_en,
                        "topic": "Topic Count",
                        "type": "Cross-DB Discrepancy",
                        "reason": reason
                    }
                    en_entry["low_confidence_flags"].append(flag_data)
                    th_entry["low_confidence_flags"].append(flag_data)
                    audit_reports.append({
                        "pdf": th_entry.get("pdf_source"),
                        "model": model_name,
                        "category": cat_en,
                        "type": "Topic Count/Ordering Mismatch (จำนวน/ลำดับหัวข้อต่างกัน)",
                        "detail": reason
                    })
                    discrepancies_count += 1

                for j in range(max_detail_len):
                    if j >= len(details_en):
                        topic_th = details_th[j].get("topic", "")
                        val_th = details_th[j].get("value", "")
                        reason = f"Extra topic in Thai category '{cat_th}' at index {j}: '{topic_th}' with value '{val_th}'"
                        print(f"    [MISMATCH] {model_name} / {cat_en} - {reason}")
                        audit_reports.append({
                            "pdf": th_entry.get("pdf_source"),
                            "model": model_name,
                            "category": cat_en,
                            "type": "Topic Count/Ordering Mismatch (จำนวน/ลำดับหัวข้อต่างกัน)",
                            "detail": reason
                        })
                        discrepancies_count += 1
                        continue
                    if j >= len(details_th):
                        topic_en = details_en[j].get("topic", "")
                        val_en = details_en[j].get("value", "")
                        reason = f"Missing topic in Thai category '{cat_en}' at index {j}: '{topic_en}' (present in English specs)"
                        print(f"    [MISMATCH] {model_name} / {cat_en} - {reason}")
                        audit_reports.append({
                            "pdf": th_entry.get("pdf_source"),
                            "model": model_name,
                            "category": cat_en,
                            "type": "Topic Count/Ordering Mismatch (จำนวน/ลำดับหัวข้อต่างกัน)",
                            "detail": reason
                        })
                        discrepancies_count += 1
                        continue

                    topic_en = details_en[j].get("topic", "")
                    topic_th = details_th[j].get("topic", "")
                    val_en = details_en[j].get("value", "")
                    val_th = details_th[j].get("value", "")

                    t_en_mapped = get_mapped_topic_name(topic_en)
                    t_th_mapped = get_mapped_topic_name(topic_th)

                    if t_en_mapped != t_th_mapped:
                        reason = f"Topic name mismatch/ordering difference in category '{cat_en}' at position {j+1}: English is '{topic_en}' (mapped: '{t_en_mapped}'), Thai is '{topic_th}' (mapped: '{t_th_mapped}')"
                        print(f"    [MISMATCH] {model_name} / {cat_en} - {reason}")
                        flag_data = {
                            "model_name": model_name,
                            "category": cat_en,
                            "topic": f"{topic_th} / {topic_en}",
                            "type": "Cross-DB Discrepancy",
                            "reason": reason
                        }
                        en_entry["low_confidence_flags"].append(flag_data)
                        th_entry["low_confidence_flags"].append(flag_data)
                        audit_reports.append({
                            "pdf": th_entry.get("pdf_source"),
                            "model": model_name,
                            "category": cat_en,
                            "type": "Topic Count/Ordering Mismatch (จำนวน/ลำดับหัวข้อต่างกัน)",
                            "detail": reason
                        })
                        discrepancies_count += 1
                        continue

                    # Compare values strictly
                    is_paintwork = (mapped_cat_en == "paintwork & upholstery")
                    if is_paintwork:
                        if not is_paintwork_value_similar(val_th, val_en):
                            reason = f"Paintwork color '{topic_en}' upholstery mismatch: Thai has '{val_th}', English has '{val_en}'"
                            print(f"    [MISMATCH] {model_name} / Paintwork - {reason}")
                            flag_data = {
                                "model_name": model_name,
                                "category": cat_en,
                                "topic": topic_en,
                                "type": "Cross-DB Discrepancy",
                                "reason": reason
                            }
                            en_entry["low_confidence_flags"].append(flag_data)
                            th_entry["low_confidence_flags"].append(flag_data)
                            audit_reports.append({
                                "pdf": th_entry.get("pdf_source"),
                                "model": model_name,
                                "category": cat_en,
                                "type": "Paintwork/Upholstery Mismatch (สีตัวถัง/วัสดุเบาะหนังไม่สอดคล้องกัน)",
                                "detail": reason
                            })
                            discrepancies_count += 1
                    else:
                        clean_en = clean_value(val_en)
                        clean_th = clean_value(val_th)

                        if clean_en != clean_th:
                            reason = f"Value mismatch for '{topic_th}' / '{topic_en}': Thai has '{val_th}', English has '{val_en}'"
                            print(f"    [MISMATCH] {model_name} / {cat_en} - {reason}")

                            flag_data = {
                                "model_name": model_name,
                                "category": cat_en,
                                "topic": f"{topic_th} / {topic_en}",
                                "type": "Cross-DB Discrepancy",
                                "reason": reason
                            }
                            en_entry["low_confidence_flags"].append(flag_data)
                            th_entry["low_confidence_flags"].append(flag_data)
                            discrepancies_count += 1

                            is_option_conflict = (clean_en == "■" and clean_th == "-") or (clean_en == "-" and clean_th == "■")
                            digits_th = extract_digits(val_th)
                            digits_en = extract_digits(val_en)
                            is_numeric_conflict = (digits_th != digits_en) and (len(digits_th) > 0 or len(digits_en) > 0)

                            if is_option_conflict:
                                audit_reports.append({
                                    "pdf": th_entry.get("pdf_source"),
                                    "model": model_name,
                                    "category": cat_en,
                                    "type": "Option Presence Conflict (มี/ไม่มี ออปชันไม่ตรงกัน)",
                                    "detail": f"ระบบหนึ่งระบุเป็นมี (■) แต่อีกระบบระบุเป็นไม่มี (-) | ไทย: '{val_th}' ↔️ อังกฤษ: '{val_en}' (หัวข้อ: {topic_th})"
                                })
                            elif is_numeric_conflict:
                                audit_reports.append({
                                    "pdf": th_entry.get("pdf_source"),
                                    "model": model_name,
                                    "category": cat_en,
                                    "type": "Numerical Mismatch (ตัวเลขสเปกไม่ตรงกัน)",
                                    "detail": f"ตัวเลขสเปกทางเทคนิคขัดแย้งกัน | ไทย: '{val_th}' ↔️ อังกฤษ: '{val_en}' (หัวข้อ: {topic_th})"
                                })
                            else:
                                audit_reports.append({
                                    "pdf": th_entry.get("pdf_source"),
                                    "model": model_name,
                                    "category": cat_en,
                                    "type": "Specification Value Mismatch (ข้อมูลสเปกไม่ตรงกัน)",
                                    "detail": f"ข้อมูลสเปกขัดแย้งกัน | ไทย: '{val_th}' ↔️ อังกฤษ: '{val_en}' (หัวข้อ: {topic_th})"
                                })

    # --- AB-NORMAL OPTION OVERLAPS AUDIT ---
    # Scan the entire TH database to find if any model has conflicting suspensions or audio systems
    for entry in db_th:
        pdf = entry.get("pdf_source")
        for m in entry.get("models", []):
            model_name = m.get("model_name")
            specs = m.get("specifications", [])
            
            details = []
            for cat in specs:
                details.extend(cat.get("details", []))
                
            # A. Check suspension overlap (Adaptive M AND M Sport both active)
            adaptive_m = any(s.get("value") == "■" and ("ช่วงล่าง adaptive" in s.get("topic", "").lower() or "adaptive m suspension" in s.get("topic", "").lower()) for s in details)
            m_sport = any(s.get("value") == "■" and ("ช่วงล่าง m sport" in s.get("topic", "").lower() or "m sport suspension" in s.get("topic", "").lower()) for s in details)
            
            if adaptive_m and m_sport:
                audit_reports.append({
                    "pdf": pdf,
                    "model": model_name,
                    "category": "ระบบขับเคลื่อนและเทคโนโลยี",
                    "type": "Suspension Overlap (ช่วงล่างทับซ้อน)",
                    "detail": "พบการเลือกเปิดใช้งาน (■) ทั้ง 'ช่วงล่าง Adaptive M' และ 'ช่วงล่าง M Sport' ในรุ่นเดียวกัน"
                })

            # B. Check audio system overlap
            hifi_rows = [s for s in details if s.get("value") == "■" and "hifi" in s.get("topic", "").lower()]
            harman_rows = [s for s in details if s.get("value") == "■" and "harman kardon" in s.get("topic", "").lower()]
            
            if len(hifi_rows) > 0 and len(harman_rows) > 0:
                topics = [r.get("topic") for r in hifi_rows + harman_rows]
                if len(set(topics)) > 1:
                    audit_reports.append({
                        "pdf": pdf,
                        "model": model_name,
                        "category": "ระบบความบันเทิงและการสื่อสาร",
                        "type": "Audio System Overlap (เครื่องเสียงทับซ้อน)",
                        "detail": f"พบระบบเครื่องเสียงที่ขัดแย้งกันถูกเลือกใช้งานพร้อมกัน: {', '.join(set(topics))}"
                    })

    # Save English database with the new flags
    with open(db_en_path, "w", encoding="utf-8") as f:
        json.dump(db_en, f, ensure_ascii=False, indent=4)

    # Save Thai database with the new flags
    with open(db_th_path, "w", encoding="utf-8") as f:
        json.dump(db_th, f, ensure_ascii=False, indent=4)

    # Write the Audit Report Markdown
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# 📝 รายงานการตรวจสอบความผิดพลาดโบรชัวร์ BMW Thailand (Specsheet Audit Report)\n\n")
        f.write("รายงานฉบับนี้รวบรวมข้อขัดแย้งทางเทคนิค, ตัวเลขตัวคูณรอบที่ไม่ตรงกัน, หรือออปชันที่มีความทับซ้อนผิดปกติที่พบบนเอกสาร PDF โบรชัวร์ เพื่อใช้ส่งเรื่องให้ทาง BMW Thailand ทำการแก้ไขแก้ไขข้อมูลต่อไป\n\n")
        f.write("---\n\n")
        
        if audit_reports:
            f.write(f"### 🔍 ตรวจพบประเด็นที่ต้องตรวจสอบทั้งหมด {len(audit_reports)} รายการ:\n\n")
            f.write("| โบรชัวร์ไฟล์ | รุ่นรถ | หมวดหมู่ | ประเภทประเด็น | รายละเอียดข้อขัดแย้ง |\n")
            f.write("| :--- | :--- | :--- | :--- | :--- |\n")
            for r in audit_reports:
                f.write(f"| `{r['pdf']}` | **{r['model']}** | {r['category']} | `{r['type']}` | {r['detail']} |\n")
        else:
            f.write("### 🎉 ยินดีด้วย! ไม่พบข้อขัดแย้งสเปกที่ผิดปกติหรือตัวเลขที่ไม่ตรงกันระหว่างระบบเลยในรอบนี้\n")
            
        f.write("\n\n---\n*รายงานสร้างโดยระบบ Specsheet Audit Engine อัตโนมัติ*")

    print(f"\n[COMPLETE] Comparison complete. Found {discrepancies_count} cross-database discrepancies.")
    print(f"[AUDITOR] Specsheet audit report generated at: {report_path} with {len(audit_reports)} issues.")
    
    if "--fail" in sys.argv and discrepancies_count > 0:
        print("[FAIL] Exiting with code 1 due to detected discrepancies.")
        sys.exit(1)

if __name__ == "__main__":
    main()
