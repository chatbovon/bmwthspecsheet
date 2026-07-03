import os
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from dotenv import load_dotenv

# Load local .env if present (primarily for local testing)
load_dotenv()

SCOPES = ['https://www.googleapis.com/auth/drive']

def get_drive_service(key_json_str):
    try:
        info = json.loads(key_json_str)
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"[GDRIVE] [ERROR] Failed to authenticate service account: {e}")
        return None

def upload_pdf_to_folder(service, folder_id, file_path):
    filename = os.path.basename(file_path)
    print(f"[GDRIVE] Uploading: {filename}...")
    
    file_metadata = {
        'name': filename,
        'parents': [folder_id]
    }
    
    media = MediaFileUpload(file_path, mimetype='application/pdf', resumable=True)
    
    try:
        uploaded_file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id'
        ).execute()
        print(f"   -> [SUCCESS] Uploaded successfully! File ID: {uploaded_file.get('id')}")
        return True
    except Exception as e:
        print(f"   -> [ERROR] Failed to upload {filename}: {e}")
        return False

def main():
    key_json = os.getenv("GDRIVE_SERVICE_ACCOUNT_KEY")
    folder_id = os.getenv("GDRIVE_FOLDER_ID")
    
    if not key_json:
        print("[GDRIVE] [WARNING] GDRIVE_SERVICE_ACCOUNT_KEY env variable is missing. Skipping upload.")
        return
    if not folder_id:
        print("[GDRIVE] [WARNING] GDRIVE_FOLDER_ID env variable is missing. Skipping upload.")
        return

    service = get_drive_service(key_json)
    if not service:
        return

    # 1. Fetch existing files in Google Drive folder
    print("[GDRIVE] Fetching list of existing files from Google Drive...")
    existing_files = {}
    try:
        page_token = None
        while True:
            query = f"'{folder_id}' in parents and trashed = false"
            results = service.files().list(
                q=query,
                spaces='drive',
                fields='nextPageToken, files(id, name)',
                pageToken=page_token
            ).execute()
            
            for file in results.get('files', []):
                existing_files[file['name']] = file['id']
                
            page_token = results.get('nextPageToken', None)
            if not page_token:
                break
        print(f"[GDRIVE] Found {len(existing_files)} existing files on Google Drive.")
    except Exception as e:
        print(f"[GDRIVE] [ERROR] Failed to list folder contents: {e}")
        return

    # 2. Scan local directories
    workspace_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    target_dirs = [
        "bmw_brochures_auto",
        "bmw_brochures_auto_en",
        "bmw_brochures_custom",
        "bmw_brochures_custom_en"
    ]

    files_to_upload = []
    for dname in target_dirs:
        dir_path = os.path.join(workspace_dir, dname)
        if not os.path.exists(dir_path):
            continue
        for fname in os.listdir(dir_path):
            if fname.lower().endswith(".pdf"):
                full_path = os.path.join(dir_path, fname)
                files_to_upload.append((fname, full_path))

    print(f"[GDRIVE] Found {len(files_to_upload)} total local PDFs across directories.")

    # 3. Upload only missing files
    uploaded_count = 0
    skipped_count = 0
    
    for fname, full_path in files_to_upload:
        if fname in existing_files:
            skipped_count += 1
            if skipped_count <= 5:
                print(f"[GDRIVE] Skipped (already exists): {fname}")
            elif skipped_count == 6:
                print("[GDRIVE] ... and more already-uploaded files skipped.")
        else:
            success = upload_pdf_to_folder(service, folder_id, full_path)
            if success:
                uploaded_count += 1

    print(f"\n[GDRIVE] Sync completed:")
    print(f"  - Uploaded: {uploaded_count} files")
    print(f"  - Skipped: {skipped_count} files")

if __name__ == "__main__":
    main()
