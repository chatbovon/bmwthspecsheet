import os
import sys
import json
import argparse

sys.stdout.reconfigure(encoding='utf-8')

def main():
    parser = argparse.ArgumentParser(description="Quickly patch a specification value in the BMW database.")
    parser.add_argument("--lang", required=True, choices=["th", "en"], help="Database language ('th' or 'en')")
    parser.add_argument("--model", required=True, help="Model name (e.g. '530e M Sport')")
    parser.add_argument("--category", required=True, help="Category name (e.g. 'ล้อและยาง' or 'Wheels and Tyres')")
    parser.add_argument("--topic", required=True, help="Specification topic (e.g. 'ขนาดยาง' or 'Tyre size')")
    parser.add_argument("--value", required=True, help="New value to set (e.g. '■' or text value)")
    
    args = parser.parse_args()
    
    filename = "bmw_master_specs_en.json" if args.lang == "en" else "bmw_master_specs.json"
    filepath = os.path.join(os.path.dirname(__file__), filename)
    
    if not os.path.exists(filepath):
        print(f"[ERROR] Database file not found: {filepath}")
        sys.exit(1)
        
    with open(filepath, "r", encoding="utf-8") as f:
        catalog = json.load(f)
        
    found_model = None
    target_model_name = args.model.strip().lower()
    
    for series in catalog:
        for model in series.get("models", []):
            if model.get("model_name", "").strip().lower() == target_model_name:
                found_model = model
                break
        if found_model:
            break
            
    if not found_model:
        print(f"[ERROR] Model '{args.model}' not found in the {args.lang.upper()} database.")
        sys.exit(1)
        
    # Find or create category
    target_cat_name = args.category.strip()
    spec_cat = next((s for s in found_model.setdefault("specifications", []) if s.get("category", "").strip().lower() == target_cat_name.lower()), None)
    
    if not spec_cat:
        spec_cat = {"category": target_cat_name, "details": []}
        found_model["specifications"].append(spec_cat)
        print(f"[INFO] Created new category: '{target_cat_name}'")
        
    # Find or create topic
    target_topic_name = args.topic.strip()
    detail = next((d for d in spec_cat.setdefault("details", []) if d.get("topic", "").strip().lower() == target_topic_name.lower()), None)
    
    old_value = None
    if detail:
        old_value = detail.get("value")
        detail["value"] = args.value
    else:
        spec_cat["details"].append({"topic": target_topic_name, "value": args.value})
        
    # Save back
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=4)
        
    if old_value is not None:
        print(f"[SUCCESS] Updated '{args.model}' -> '{target_topic_name}' from '{old_value}' to '{args.value}'")
    else:
        print(f"[SUCCESS] Added new topic '{args.model}' -> '{target_topic_name}' with value '{args.value}'")

if __name__ == "__main__":
    main()
