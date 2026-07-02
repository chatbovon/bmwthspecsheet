"""
spec_merger.py
==============
Iterates through a folder of processed model JSON files, merging them into
the consolidated master database file (e.g., bmw_master_specs.json).
Maintains strict category/topic structure and applies last-wins-for-dash updates.
"""

import os
import sys
import json

def merge_models(target_models: list[dict], source_models: list[dict]):
    """
    Merge a list of source models into the target models list.
    """
    model_map = {m["model_name"]: m for m in target_models}
    
    for sm in source_models:
        name = sm.get("model_name")
        if not name:
            continue
        if name not in model_map:
            # Model does not exist yet under this series, append it
            target_models.append(sm)
            model_map[name] = sm
            continue
            
        # Merge specifications for existing model
        tm = model_map[name]
        for s_spec in sm.get("specifications", []):
            cat_name = s_spec.get("category")
            if not cat_name:
                continue
                
            # Find category in target model
            cat_ref = next((c for c in tm.get("specifications", []) if c["category"] == cat_name), None)
            if not cat_ref:
                cat_ref = {"category": cat_name, "details": []}
                tm.setdefault("specifications", []).append(cat_ref)
                
            # Merge details (last-wins-for-dash)
            topic_map = {d["topic"]: d for d in cat_ref["details"]}
            for s_detail in s_spec.get("details", []):
                topic = s_detail.get("topic")
                val = s_detail.get("value", "-")
                if not topic:
                    continue
                if topic not in topic_map:
                    cat_ref["details"].append(s_detail)
                    topic_map[topic] = s_detail
                else:
                    existing = topic_map[topic]
                    # Overwrite empty or dash value with actual spec details
                    if str(existing.get("value", "-")).strip() in ("-", "", "None") and \
                       str(val).strip() not in ("-", "", "None"):
                        existing["value"] = val

def merge_single_json_into_catalog(catalog: list[dict], source_data: dict) -> list[dict]:
    """
    Merge a single source specsheet JSON dict into the catalog list.
    """
    source_series = source_data.get("series")
    if not source_series:
        return catalog
        
    source_series = source_series.strip()
    source_file = source_data.get("source_file") or source_data.get("pdf_source")
    
    # Try to find matching series in catalog where the source_file also matches
    series_ref = next(
        (s for s in catalog 
         if s.get("series", "").strip() == source_series 
         and (s.get("source_file") == source_file or s.get("pdf_source") == source_file)), 
        None
    )
    
    # If not found exactly, try fuzzy matching for series name with exact source_file match
    if not series_ref:
        norm = lambda x: "".join(x.split()).lower().replace(".", "")
        series_ref = next(
            (s for s in catalog 
             if norm(s.get("series", "")) == norm(source_series) 
             and (s.get("source_file") == source_file or s.get("pdf_source") == source_file)), 
            None
        )
        
    if not series_ref:
        # Create new series entry with source_file and pdf_source tracking
        series_ref = {
            "series": source_series, 
            "source_file": source_file,
            "pdf_source": source_file,
            "models": []
        }
        catalog.append(series_ref)
        
    merge_models(series_ref.setdefault("models", []), source_data.get("models", []))
    return catalog

def run_merge(input_folder: str, master_json_path: str):
    print(f"[LOAD] Reading master catalog: {master_json_path}")
    catalog = []
    if os.path.exists(master_json_path):
        try:
            with open(master_json_path, "r", encoding="utf-8") as f:
                catalog = json.load(f)
            if not isinstance(catalog, list):
                print(f"[WARNING] Master catalog is not a list. Resetting.")
                catalog = []
        except Exception as e:
            print(f"[WARNING] Could not read master catalog: {e}. Starting fresh.")
            catalog = []
            
    if not os.path.isdir(input_folder):
        print(f"[ERROR] Input folder '{input_folder}' does not exist.")
        sys.exit(1)
        
    json_files = [
        f for f in os.listdir(input_folder)
        if f.lower().endswith(".json") and f != os.path.basename(master_json_path)
    ]
    print(f"[MERGE] Found {len(json_files)} specsheet files to merge.")
    
    merged_count = 0
    for filename in json_files:
        filepath = os.path.join(input_folder, filename)
        print(f"   [MERGE] Merging: {filename}")
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                source_data = json.load(f)
            catalog = merge_single_json_into_catalog(catalog, source_data)
            merged_count += 1
        except Exception as e:
            print(f"   [ERROR] Failed to merge {filename}: {e}")
            
    # Save master file
    print(f"[SAVE] Saving master catalog ({len(catalog)} series total) to {master_json_path}")
    with open(master_json_path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=4)
        
    print(f"[COMPLETE] Successfully merged {merged_count} file(s) into {master_json_path}!")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python spec_merger.py <input_folder> <master_json_path>")
        sys.exit(1)
    run_merge(sys.argv[1], sys.argv[2])
