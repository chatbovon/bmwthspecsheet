import os
import sys
import json
import time
from dotenv import load_dotenv

# Fix Windows console encoding for Thai characters
sys.stdout.reconfigure(encoding='utf-8')

# Import the core MinerU + Gemini extraction pipeline
from mineru_extractor import run_extraction_pipeline

WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(WORKSPACE_DIR, ".env"), override=True)

def run_batch_extraction(lang="th", target_file=None):
    if lang == "en":
        auto_folder = "bmw_brochures_auto_en"
        output_file = "bmw_master_specs_en.json"
        compat_file = "bmw_ai_specs_en.json"
    else:
        auto_folder = "bmw_brochures_auto"
        output_file = "bmw_master_specs.json"
        compat_file = "bmw_ai_specs.json"

    if not os.path.exists(auto_folder):
        os.makedirs(auto_folder)

    # Scan PDFs in folder
    pdf_entries = sorted([f for f in os.listdir(auto_folder) if f.lower().endswith(".pdf")])

    if target_file:
        pdf_entries = [f for f in pdf_entries if target_file in f or target_file in os.path.basename(f)]
        if not pdf_entries:
            print(f"[ERROR] Target file '{target_file}' not found in '{auto_folder}'.")
            return

    if not pdf_entries:
        print(f"[WARNING] No PDF files found in '{auto_folder}'.")
        return

    print(f"\n[BATCH] [{lang.upper()}] Found {len(pdf_entries)} PDF files to process in '{auto_folder}'.")

    # Load master catalog
    master_specs = []
    processed_pdfs = set()

    if os.path.exists(output_file):
        try:
            with open(output_file, 'r', encoding='utf-8') as f:
                master_specs = json.load(f)
                if not isinstance(master_specs, list):
                    master_specs = []
                processed_pdfs = {item["pdf_source"] for item in master_specs if "pdf_source" in item}
                print(f"[BATCH] Loaded existing catalog. Already processed: {len(processed_pdfs)} files.")
        except Exception as e:
            print(f"[WARNING] Failed to load existing '{output_file}': {e}")
            master_specs = []

    success_count = len(processed_pdfs)

    for i, filename in enumerate(pdf_entries, 1):
        if filename in processed_pdfs and not target_file:
            print(f"--- [{i}/{len(pdf_entries)}] Skipping (already processed): {filename} ---")
            continue

        pdf_path = os.path.join(auto_folder, filename)
        print(f"\n--- [{i}/{len(pdf_entries)}] Starting MinerU Extraction: {filename} ---")

        # Temporary output path for this specific PDF extraction
        temp_json = os.path.join(WORKSPACE_DIR, f"temp_{filename.rsplit('.', 1)[0]}.json")
        if os.path.exists(temp_json):
            os.remove(temp_json)

        try:
            # Call the MinerU + Gemini extraction pipeline
            run_extraction_pipeline(pdf_path, temp_json, lang)

            # Load the extracted result
            if os.path.exists(temp_json):
                with open(temp_json, "r", encoding="utf-8") as f:
                    result = json.load(f)

                # Ensure pdf_source is set
                result["pdf_source"] = filename

                # If target_file is specified, replace the existing entry
                if target_file:
                    master_specs = [item for item in master_specs if item.get("pdf_source") != filename]

                master_specs.append(result)
                success_count += 1

                # Save back to master catalog immediately
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(master_specs, f, ensure_ascii=False, indent=4)

                # Save compatibility file
                with open(compat_file, 'w', encoding='utf-8') as f:
                    json.dump(result, f, ensure_ascii=False, indent=4)

                print(f"[BATCH] Successfully processed and saved: {filename}")
                
                # Auto-commit & push to GitHub after each file if running in GitHub Actions
                if os.environ.get("GITHUB_ACTIONS") == "true":
                    try:
                        import subprocess
                        print(f"[GIT] Committing and pushing progress for {filename}...")
                        subprocess.run(["git", "config", "--global", "user.name", "github-actions[bot]"], check=False)
                        subprocess.run(["git", "config", "--global", "user.email", "github-actions[bot]@users.noreply.github.com"], check=False)
                        
                        # Rebase pull to prevent conflicts
                        subprocess.run(["git", "pull", "--rebase"], check=False)
                        
                        # Stage updated files
                        subprocess.run(["git", "add", output_file], check=False)
                        subprocess.run(["git", "add", "-f", compat_file], check=False)
                        subprocess.run(["git", "add", "-f", pdf_path], check=False)
                        
                        # Commit progress
                        subprocess.run(["git", "commit", "-m", f"Auto-update: Processed {filename} [skip ci]"], check=False)
                        
                        # Push changes
                        push_res = subprocess.run(["git", "push"], capture_output=True, text=True, check=False)
                        if push_res.returncode == 0:
                            print(f"[GIT] Successfully committed and pushed progress for: {filename}")
                        else:
                            print(f"[GIT WARNING] Git push failed: {push_res.stderr.strip()}")
                    except Exception as push_err:
                        print(f"[GIT WARNING] Failed to run Git progress push: {push_err}")

                os.remove(temp_json)
            else:
                print(f"[ERROR] Extraction pipeline finished but output file was not created for {filename}")

        except Exception as e:
            print(f"[ERROR] Pipeline crashed on {filename}: {e}")

    print(f"\n[SUCCESS] [{lang.upper()}] Master specs successfully saved to '{output_file}'!")
    print(f"[SUMMARY] Successfully extracted {success_count}/{len(pdf_entries)} files")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="BMW Specsheet Batch Extractor using MinerU")
    parser.add_argument("--lang", type=str, default="th", choices=["th", "en"], help="Language of brochures to extract (th or en)")
    parser.add_argument("--file", "--target", dest="file", type=str, default=None, help="Target specific PDF filename to extract")
    args = parser.parse_args()
    run_batch_extraction(lang=args.lang, target_file=args.file)