import os
import json
import shutil

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
live_list_path = os.path.join(WORKSPACE_DIR, "scratch", "live_web_pdfs.txt")

def archive_discontinued_in_db(db_path):
    if not os.path.exists(db_path):
        print(f"[ARCHIVER] [WARNING] Database file not found: {db_path}")
        return False
        
    with open(db_path, "r", encoding="utf-8") as f:
        db = json.load(f)
        
    # Read live PDFs list
    if not os.path.exists(live_list_path):
        print(f"[ARCHIVER] [ERROR] Live web PDFs list not found at: {live_list_path}")
        return False
        
    with open(live_list_path, "r", encoding="utf-8") as f:
        live_pdfs = {line.strip().lower() for line in f if line.strip()}
        
    print(f"\n[ARCHIVER] Scanning database: {os.path.basename(db_path)}")
    print(f"[ARCHIVER] Found {len(live_pdfs)} live PDFs on web.")
    
    modified_count = 0
    
    # Track files moved in this run to avoid duplicate move messages
    moved_files = set()
    
    for item in db:
        pdf_source = item.get("pdf_source")
        if not pdf_source:
            continue
            
        pdf_source_lower = pdf_source.strip().lower()
        is_live_on_web = pdf_source_lower in live_pdfs
        
        # 1. Update Database Entries
        for m in item.get("models", []):
            is_currently_archived = m.get("is_custom_archived", False)
            
            # If PDF is not live on web and model is not yet tagged as custom archived:
            if not is_live_on_web and not is_currently_archived:
                m["is_custom_archived"] = True
                modified_count += 1
                print(f"   [ARCHIVE] Discontinued model tagged: '{m.get('model_name')}' (Source: {pdf_source})")
        
        # 2. Move Physical PDF Files
        if not is_live_on_web and pdf_source_lower not in moved_files:
            # Determine directory paths
            if "en.json" in db_path.lower():
                src_dir = os.path.join(WORKSPACE_DIR, "bmw_brochures_auto_en")
                dest_dir = os.path.join(WORKSPACE_DIR, "bmw_brochures_custom_en")
            else:
                src_dir = os.path.join(WORKSPACE_DIR, "bmw_brochures_auto")
                dest_dir = os.path.join(WORKSPACE_DIR, "bmw_brochures_custom")
                
            src_file = os.path.join(src_dir, pdf_source)
            if os.path.exists(src_file):
                if not os.path.exists(dest_dir):
                    os.makedirs(dest_dir)
                dest_file = os.path.join(dest_dir, pdf_source)
                try:
                    if os.path.exists(dest_file):
                        os.remove(src_file)
                        print(f"   [ARCHIVE] [FILE-MOVE] Deleted duplicate file in auto: {pdf_source}")
                    else:
                        shutil.move(src_file, dest_file)
                        print(f"   [ARCHIVE] [FILE-MOVE] Moved file: {pdf_source} -> {os.path.basename(dest_dir)}")
                    moved_files.add(pdf_source_lower)
                except Exception as move_err:
                    print(f"   [ARCHIVE] [ERROR] Failed to move PDF file {pdf_source}: {move_err}")
                
    if modified_count > 0:
        with open(db_path, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=4)
        print(f"[ARCHIVER] [SUCCESS] Database updated! Archived {modified_count} discontinued models.")
        return True
    else:
        print(f"[ARCHIVER] No new discontinued models detected in this database.")
        return False

def main():
    th_db = os.path.join(WORKSPACE_DIR, "bmw_master_specs.json")
    en_db = os.path.join(WORKSPACE_DIR, "bmw_master_specs_en.json")
    
    archive_discontinued_in_db(th_db)
    archive_discontinued_in_db(en_db)

if __name__ == "__main__":
    main()
