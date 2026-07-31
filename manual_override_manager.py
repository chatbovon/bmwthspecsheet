import os
import json
import difflib
import re

WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
OVERRIDES_FILE = os.path.join(WORKSPACE_DIR, "manual_overrides.json")

def normalize_key(text):
    if not text:
        return ""
    text = text.strip().lower()
    # Normalize spaces and special symbols
    text = text.replace('\xa0', ' ').replace('\u200b', '')
    text = text.replace('×', 'x').replace('x', 'x')
    # Standardize Thai character sequences (like decomposed sora-am)
    text = text.replace('ำ', 'ำ') # Ensuring consistent representation
    # Strip all non-alphanumeric/non-Thai characters
    text = re.sub(r'[^a-zA-Z0-9\u0e00-\u0e7f]', '', text)
    return text

def calculate_similarity(str1, str2):
    return difflib.SequenceMatcher(None, str1, str2).ratio()

def apply_overrides(pdf_source, model_json):
    """
    Applies overrides from manual_overrides.json to a model specification JSON dict.
    Updates the values in place and normalizes spelling to the override keys.
    
    IMPORTANT: This system is designed solely to correct mistakes inherent in the
    source PDF brochures published by BMW Thailand (e.g., typographical errors,
    incorrect technical specifications, or missing options in the original print).
    It is NOT for patching AI extraction failures. AI parsing issues should be
    resolved by refining system prompts or extraction logic.
    """
    # Skip overrides for English brochures since they are written in Thai
    if "_en" in os.path.basename(pdf_source).lower():
        return

    if not os.path.exists(OVERRIDES_FILE):
        return

    try:
        with open(OVERRIDES_FILE, "r", encoding="utf-8") as f:
            overrides_db = json.load(f)
    except Exception as e:
        print(f"[WARNING] Failed to load manual_overrides.json: {e}")
        return

    # Find matching prefix in overrides
    matching_prefix = None
    pdf_basename = os.path.basename(pdf_source)
    
    for prefix in overrides_db:
        # Ignore comments/metadata keys starting with "_"
        if prefix.startswith("_"):
            continue
        if pdf_basename.startswith(prefix):
            matching_prefix = prefix
            break

    if not matching_prefix:
        return

    prefix_overrides = overrides_db[matching_prefix]
    model_name = model_json.get("model_name", "")
    
    # Match model name (strict or normalized)
    override_model_key = None
    for o_mname in prefix_overrides:
        # Ignore comments/metadata keys starting with "_"
        if o_mname.startswith("_"):
            continue
        if o_mname.strip().lower() == model_name.strip().lower():
            override_model_key = o_mname
            break
            
    if not override_model_key:
        return

    model_overrides = prefix_overrides[override_model_key]
    specifications = model_json.get("specifications", [])

    print(f"[OVERRIDE-MANAGER] Patching source PDF/brochure errors for model '{model_name}' under PDF prefix '{matching_prefix}'...")

    for override_cat_name, override_topics in model_overrides.items():
        # Ignore comments/metadata keys starting with "_"
        if override_cat_name.startswith("_"):
            continue
        # Find category in spec
        target_cat = None
        for cat in specifications:
            if cat.get("category", "").strip().lower() == override_cat_name.strip().lower():
                target_cat = cat
                break
                
        if not target_cat:
            # If category doesn't exist, create it to apply override
            target_cat = {"category": override_cat_name, "details": []}
            specifications.append(target_cat)
            
        details = target_cat.setdefault("details", [])
        
        # Loop through override topics to find match in details
        for override_topic, override_val in override_topics.items():
            # Ignore comments/metadata keys starting with "_"
            if override_topic.startswith("_"):
                continue
            matched_detail = None
            match_stage = None
            
            # Normalization of override key
            norm_override_topic = normalize_key(override_topic)
            
            # Stage 1: Strict Direct Match
            for d in details:
                if d.get("topic", "").strip() == override_topic.strip():
                    matched_detail = d
                    match_stage = "Stage 1 (Strict)"
                    break
                    
            # Stage 2: Normalized Match
            if not matched_detail:
                for d in details:
                    if normalize_key(d.get("topic", "")) == norm_override_topic:
                        matched_detail = d
                        match_stage = "Stage 2 (Normalized)"
                        break
                        
            # Stage 3: Fuzzy Match
            if not matched_detail:
                best_ratio = 0.0
                best_detail = None
                for d in details:
                    ratio = calculate_similarity(normalize_key(d.get("topic", "")), norm_override_topic)
                    if ratio > best_ratio:
                        best_ratio = ratio
                        best_detail = d
                if best_ratio >= 0.90:
                    matched_detail = best_detail
                    match_stage = f"Stage 3 (Fuzzy: {best_ratio:.2f})"
            
            # Apply Override
            if matched_detail:
                old_val = matched_detail.get("value")
                old_topic = matched_detail.get("topic")
                
                # Update value and correct spelling to the locked key spelling
                matched_detail["value"] = override_val
                matched_detail["topic"] = override_topic
                
                print(f"  [APPLIED] {match_stage} override for '{override_topic}'")
                print(f"    Topic: '{old_topic}' -> '{override_topic}'")
                print(f"    Value: '{old_val}' -> '{override_val}'")
            else:
                # If not matched at all (Stage 4), it's a new override topic. Add it.
                details.append({
                    "topic": override_topic,
                    "value": override_val
                })
                print(f"  [ADDED] New override topic '{override_topic}' with value '{override_val}'")
