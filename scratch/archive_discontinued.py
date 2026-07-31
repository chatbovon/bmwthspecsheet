import os
import json
import shutil

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
live_list_path = os.path.join(WORKSPACE_DIR, "scratch", "live_web_pdfs.txt")

def archive_discontinued_in_db(db_path, custom_db_path):
    if not os.path.exists(db_path):
        print(f"[ARCHIVER] [WARNING] Master database file not found: {db_path}")
        return False
        
    with open(db_path, "r", encoding="utf-8") as f:
        master_db = json.load(f)
        
    # Read custom/archived database
    custom_db = []
    if os.path.exists(custom_db_path):
        try:
            with open(custom_db_path, "r", encoding="utf-8") as f:
                custom_db = json.load(f)
            if not isinstance(custom_db, list):
                custom_db = []
        except Exception:
            custom_db = []
            
    # Read live PDFs list
    if not os.path.exists(live_list_path):
        print(f"[ARCHIVER] [ERROR] Live web PDFs list not found at: {live_list_path}")
        return False
        
    with open(live_list_path, "r", encoding="utf-8") as f:
        live_pdfs = {line.strip().lower() for line in f if line.strip()}
        
    # Circuit Breaker: If live PDFs count is dangerously low (e.g. < 5), abort immediately
    if len(live_pdfs) < 5:
        print(f"[ARCHIVER] [CRITICAL] Dangerously low live PDFs count ({len(live_pdfs)}). BMW site might be down. Aborting archiving to prevent database corruption.")
        return False
        
    print(f"\n[ARCHIVER] Scanning databases: {os.path.basename(db_path)} and {os.path.basename(custom_db_path)}")
    print(f"[ARCHIVER] Found {len(live_pdfs)} live PDFs on web.")
    
    modified = False
    new_master_db = []
    moved_count = 0
    
    # 1. Process master database items
    for item in master_db:
        pdf_source = item.get("pdf_source")
        if not pdf_source:
            new_master_db.append(item)
            continue
            
        pdf_source_lower = pdf_source.strip().lower()
        is_live_on_web = pdf_source_lower in live_pdfs
        
        if is_live_on_web:
            # Keep in master, clean up archived property
            for m in item.get("models", []):
                if "is_custom_archived" in m:
                    del m["is_custom_archived"]
            new_master_db.append(item)
        else:
            # Move to custom, set is_custom_archived
            for m in item.get("models", []):
                m["is_custom_archived"] = True
            
            # Avoid duplicate PDF source in custom
            custom_db = [x for x in custom_db if x.get("pdf_source") != pdf_source]
            custom_db.append(item)
            
            moved_count += len(item.get("models", []))
            print(f"   [ARCHIVE -> CUSTOM] Moved entry: '{pdf_source}' ({len(item.get('models', []))} models) to custom db.")
            modified = True
            
            # Move Physical PDF File
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
                except Exception as move_err:
                    print(f"   [ARCHIVE] [ERROR] Failed to move PDF file {pdf_source}: {move_err}")

    # 2. Process custom database items (for restoration)
    new_custom_db = []
    restored_count = 0
    
    for item in custom_db:
        pdf_source = item.get("pdf_source")
        if not pdf_source:
            new_custom_db.append(item)
            continue
            
        pdf_source_lower = pdf_source.strip().lower()
        is_live_on_web = pdf_source_lower in live_pdfs
        
        if not is_live_on_web:
            new_custom_db.append(item)
        else:
            # Move back to master
            for m in item.get("models", []):
                if "is_custom_archived" in m:
                    del m["is_custom_archived"]
            
            new_master_db = [x for x in new_master_db if x.get("pdf_source") != pdf_source]
            new_master_db.append(item)
            
            restored_count += len(item.get("models", []))
            print(f"   [CUSTOM -> MASTER] Restored entry: '{pdf_source}' ({len(item.get('models', []))} models) to master db.")
            modified = True
            
            # Restore Physical PDF File
            if "en.json" in db_path.lower():
                custom_dir = os.path.join(WORKSPACE_DIR, "bmw_brochures_custom_en")
                auto_dir = os.path.join(WORKSPACE_DIR, "bmw_brochures_auto_en")
            else:
                custom_dir = os.path.join(WORKSPACE_DIR, "bmw_brochures_custom")
                auto_dir = os.path.join(WORKSPACE_DIR, "bmw_brochures_auto")
                
            custom_file = os.path.join(custom_dir, pdf_source)
            if os.path.exists(custom_file):
                if not os.path.exists(auto_dir):
                    os.makedirs(auto_dir)
                auto_file = os.path.join(auto_dir, pdf_source)
                try:
                    if os.path.exists(auto_file):
                        os.remove(custom_file)
                        print(f"   [RESTORE] [FILE-MOVE] Deleted duplicate in custom: {pdf_source}")
                    else:
                        shutil.move(custom_file, auto_file)
                        print(f"   [RESTORE] [FILE-MOVE] Restored file: {pdf_source} -> {os.path.basename(auto_dir)}")
                except Exception as restore_err:
                    print(f"   [RESTORE] [ERROR] Failed to restore PDF file {pdf_source}: {restore_err}")

    if modified:
        with open(db_path, "w", encoding="utf-8") as f:
            json.dump(new_master_db, f, ensure_ascii=False, indent=4)
        with open(custom_db_path, "w", encoding="utf-8") as f:
            json.dump(new_custom_db, f, ensure_ascii=False, indent=4)
        print(f"[ARCHIVER] [SUCCESS] Updated databases: Moved {moved_count} models to custom, restored {restored_count} models to master.")
        return True
    else:
        print(f"[ARCHIVER] No database updates needed.")
        return False

def main():
    th_db = os.path.join(WORKSPACE_DIR, "bmw_master_specs.json")
    th_custom_db = os.path.join(WORKSPACE_DIR, "bmw_custom_specs.json")
    en_db = os.path.join(WORKSPACE_DIR, "bmw_master_specs_en.json")
    en_custom_db = os.path.join(WORKSPACE_DIR, "bmw_custom_specs_en.json")
    
    archive_discontinued_in_db(th_db, th_custom_db)
    archive_discontinued_in_db(en_db, en_custom_db)

if __name__ == "__main__":
    main()
