import os
import json
import subprocess

def main():
    workspace_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    status_file = os.path.join(workspace_dir, "scratch", "gdrive_status.json")
    gdrive_ok = False
    
    if os.path.exists(status_file):
        try:
            with open(status_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data.get("status") == "success":
                    gdrive_ok = True
        except Exception as e:
            print(f"[GIT WARNING] Could not read gdrive_status.json: {e}")

    if not gdrive_ok:
        print("[GIT] Google Drive backup incomplete/failed. Staging PDFs as emergency repository backup...")
        subprocess.run(["git", "add", "-f", "bmw_brochures_auto/*.pdf", "bmw_brochures_auto_en/*.pdf"], check=False)
    else:
        print("[GIT] Google Drive backup OK. PDFs are safely stored in Google Drive.")

if __name__ == "__main__":
    main()
