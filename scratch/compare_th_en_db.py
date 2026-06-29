import json
import os
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

db_th_path = r"bmw_master_specs.json"
db_en_path = r"bmw_master_specs_en.json"

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

def map_category(cat_th):
    cat_th = cat_th.lower()
    if "เครื่องยนต์" in cat_th:
        return "engine and performance"
    elif "อัตราสิ้นเปลือง" in cat_th or "co2" in cat_th:
        return "fuel consumption and co2"
    elif "ล้อ" in cat_th or "ยาง" in cat_th:
        return "wheels and tyres"
    elif "มิติ" in cat_th:
        return "dimension"
    elif "ระบบขับเคลื่อน" in cat_th:
        return "transmission and technology"
    elif "ภายนอก" in cat_th:
        return "exterior"
    elif "ภายใน" in cat_th:
        return "interior"
    elif "บันเทิง" in cat_th or "สื่อสาร" in cat_th:
        return "entertainment and communication"
    elif "ปลอดภัย" in cat_th:
        return "safety"
    elif "ชุดตกแต่ง" in cat_th:
        return "line / package"
    elif "paintwork" in cat_th or "สีตัวถัง" in cat_th:
        return "paintwork & upholstery"
    elif "ข้อมูลเอกสารอ้างอิง" in cat_th or "เอกสารอ้างอิง" in cat_th:
        return "document references"
    return cat_th

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
    
    # Normalize multiplication signs
    val = val.replace("×", "x")
    
    # Translate Thai months to English
    th_months = {
        "มกราคม": "january", "กุมภาพันธ์": "february", "มีนาคม": "march",
        "เมษายน": "april", "พฤษภาคม": "may", "มิถุนายน": "june",
        "กรกฎาคม": "july", "สิงหาคม": "august", "กันยายน": "september",
        "ตุลาคม": "october", "พฤศจิกายน": "november", "ธันวาคม": "december"
    }
    for th_m, en_m in th_months.items():
        val = val.replace(th_m, en_m)
        
    # Look for 4-digit BE year (2500-2699) and convert to CE (subtract 543)
    match_be = re.search(r'(25\d{2}|26\d{2})', val)
    if match_be:
        be_yr = int(match_be.group(1))
        ce_yr = be_yr - 543
        val = val.replace(str(be_yr), str(ce_yr))
        
    # Lowercase and remove commas, spaces, and units
    val = val.replace(",", "").replace(" ", "")
    # Remove Thai units
    val = val.replace("ซีซี", "").replace("มม.", "").replace("กิโลวัตต์", "").replace("แรงม้า", "").replace("รอบต่อนาที", "").replace("นิวตันเมตร", "").replace("กิโลเมตร/ชั่วโมง", "").replace("วินาที", "").replace("ลิตร", "").replace("กก.", "")
    # Remove English units
    val = val.replace("cc", "").replace("mm", "").replace("kw", "").replace("hp", "").replace("ps", "").replace("rpm", "").replace("nm", "").replace("km/h", "").replace("s", "").replace("l", "").replace("kg", "")
    # Remove structural descriptors to align tyre and wheel sizes
    val = val.replace("tyres", "").replace("tyre", "").replace("ยาง", "")
    val = val.replace("front:", "").replace("rear:", "").replace("front", "").replace("rear", "")
    val = val.replace("ล้อหน้า:", "").replace("ล้อหลัง:", "").replace("ล้อหน้า", "").replace("ล้อหลัง", "")
    return val

def is_paintwork_value_similar(val_th, val_en):
    # If both are empty or hyphens, they match
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

            # Compare specifications category by category
            en_specs = en_model.get("specifications", [])
            th_specs = th_model.get("specifications", [])

            # Map TH specifications by mapped category name
            th_spec_cats = {}
            for ts in th_specs:
                mapped_cat = map_category(ts.get("category", ""))
                th_spec_cats[mapped_cat] = ts

            for es in en_specs:
                cat_en = es.get("category", "")
                mapped_cat_en = map_category(cat_en)
                
                ts = th_spec_cats.get(mapped_cat_en)
                if not ts:
                    continue

                details_en = es.get("details", [])
                details_th = ts.get("details", [])

                is_paintwork = (mapped_cat_en == "paintwork & upholstery")

                if is_paintwork:
                    th_paint_topics = {d.get("topic").lower().strip(): d for d in details_th}
                    for de in details_en:
                        topic_en = de.get("topic", "")
                        val_en = de.get("value", "")
                        
                        dt = th_paint_topics.get(topic_en.lower().strip())
                        if dt:
                            val_th = dt.get("value", "")
                            if not is_paintwork_value_similar(val_th, val_en):
                                reason = f"Paintwork color '{topic_en}' upholstery mismatch: Thai has '{val_th}', English has '{val_en}'"
                                print(f"    [MISMATCH] {model_name} / Paintwork - {reason}")
                                flag_data_en = {
                                    "model_name": model_name,
                                    "category": cat_en,
                                    "topic": topic_en,
                                    "type": "Cross-DB Discrepancy",
                                    "reason": reason
                                }
                                en_entry["low_confidence_flags"].append(flag_data_en)
                                
                                flag_data_th = {
                                    "model_name": th_model.get("model_name", model_name),
                                    "category": ts.get("category", cat_en),
                                    "topic": dt.get("topic", topic_en),
                                    "type": "Cross-DB Discrepancy",
                                    "reason": reason
                                }
                                th_entry["low_confidence_flags"].append(flag_data_th)
                                discrepancies_count += 1
                else:
                    if len(details_en) == len(details_th):
                        for idx, de in enumerate(details_en):
                            dt = details_th[idx]
                            topic_en = de.get("topic", "")
                            topic_th = dt.get("topic", "")
                            val_en = de.get("value", "")
                            val_th = dt.get("value", "")

                            clean_en = clean_value(val_en)
                            clean_th = clean_value(val_th)

                            if clean_en != clean_th:
                                reason = f"Value mismatch for '{topic_th}' / '{topic_en}': Thai has '{val_th}', English has '{val_en}'"
                                print(f"    [MISMATCH] {model_name} / {cat_en} - {reason}")
                                flag_data_en = {
                                    "model_name": model_name,
                                    "category": cat_en,
                                    "topic": f"{topic_th} / {topic_en}",
                                    "type": "Cross-DB Discrepancy",
                                    "reason": reason
                                }
                                en_entry["low_confidence_flags"].append(flag_data_en)
                                
                                flag_data_th = {
                                    "model_name": th_model.get("model_name", model_name),
                                    "category": ts.get("category", cat_en),
                                    "topic": topic_th,
                                    "type": "Cross-DB Discrepancy",
                                    "reason": reason
                                }
                                th_entry["low_confidence_flags"].append(flag_data_th)
                                discrepancies_count += 1
                    else:
                        th_details_map = {d.get("topic").strip(): d for d in details_th}
                        th_mapped_details = {}
                        for t_th, d in th_details_map.items():
                            mapped_t = TOPIC_MAP.get(t_th)
                            if mapped_t:
                                th_mapped_details[mapped_t] = d

                        for de in details_en:
                            topic_en = de.get("topic", "").strip()
                            val_en = de.get("value", "")

                            dt = th_mapped_details.get(topic_en.lower())
                            if not dt:
                                for t_th, mapped_t in TOPIC_MAP.items():
                                    if topic_en.lower() in mapped_t or mapped_t in topic_en.lower():
                                        dt = th_details_map.get(t_th)
                                        break

                            if dt:
                                topic_th = dt.get("topic", "")
                                val_th = dt.get("value", "")
                                clean_en = clean_value(val_en)
                                clean_th = clean_value(val_th)

                                if clean_en != clean_th:
                                    reason = f"Value mismatch for '{topic_th}' / '{topic_en}': Thai has '{val_th}', English has '{val_en}'"
                                    print(f"    [MISMATCH] {model_name} / {cat_en} - {reason}")
                                    flag_data_en = {
                                        "model_name": model_name,
                                        "category": cat_en,
                                        "topic": f"{topic_th} / {topic_en}",
                                        "type": "Cross-DB Discrepancy",
                                        "reason": reason
                                    }
                                    en_entry["low_confidence_flags"].append(flag_data_en)
                                    
                                    flag_data_th = {
                                        "model_name": th_model.get("model_name", model_name),
                                        "category": ts.get("category", cat_en),
                                        "topic": topic_th,
                                        "type": "Cross-DB Discrepancy",
                                        "reason": reason
                                    }
                                    th_entry["low_confidence_flags"].append(flag_data_th)
                                    discrepancies_count += 1

    # Save English database with the new flags
    with open(db_en_path, "w", encoding="utf-8") as f:
        json.dump(db_en, f, ensure_ascii=False, indent=4)

    # Save Thai database with the new flags
    with open(db_th_path, "w", encoding="utf-8") as f:
        json.dump(db_th, f, ensure_ascii=False, indent=4)

    print(f"\n[COMPLETE] Comparison complete. Found {discrepancies_count} cross-database discrepancies.")

if __name__ == "__main__":
    main()
