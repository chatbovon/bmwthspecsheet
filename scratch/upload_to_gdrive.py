import os
import sys
import json
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from dotenv import load_dotenv

# Load local .env if present (primarily for local testing)
load_dotenv()

SCOPES = ['https://www.googleapis.com/auth/drive']

def get_drive_service_service_account(key_json_str):
    try:
        info = json.loads(key_json_str)
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"[GDRIVE] [ERROR] Failed to initialize service account: {e}")
        return None

def get_drive_service_oauth2(client_id, client_secret, refresh_token):
    try:
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=SCOPES
        )
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"[GDRIVE] [ERROR] Failed to initialize OAuth2 credentials: {e}")
        return None

def authenticate_drive(key_json, client_id, client_secret, refresh_token, folder_id):
    """
    Dual-strategy authentication:
    1. Prioritize Service Account (Permanent, enterprise-grade, never expires).
    2. Fall back to OAuth2 User Credentials if Service Account is missing or fails.
    """
    # Strategy 1: Service Account
    if key_json:
        try:
            print("[GDRIVE] Attempting authentication via Service Account...")
            svc = get_drive_service_service_account(key_json)
            if svc:
                # Perform a quick 1-file test call to verify permissions on folder_id
                svc.files().list(
                    q=f"'{folder_id}' in parents and trashed = false",
                    pageSize=1,
                    fields="files(id)"
                ).execute()
                print("[GDRIVE] [SUCCESS] Authenticated successfully via Service Account!")
                return svc, "Service Account"
        except Exception as sa_err:
            print(f"[GDRIVE] [WARNING] Service Account authentication failed: {sa_err}")

    # Strategy 2: OAuth2 User Credentials
    if client_id and client_secret and refresh_token:
        try:
            print("[GDRIVE] Attempting authentication via OAuth2 User Credentials...")
            svc = get_drive_service_oauth2(client_id, client_secret, refresh_token)
            if svc:
                # Perform a quick 1-file test call to verify permissions on folder_id
                svc.files().list(
                    q=f"'{folder_id}' in parents and trashed = false",
                    pageSize=1,
                    fields="files(id)"
                ).execute()
                print("[GDRIVE] [SUCCESS] Authenticated successfully via OAuth2 User Credentials!")
                return svc, "OAuth2"
        except Exception as oauth_err:
            print(f"[GDRIVE] [WARNING] OAuth2 authentication failed: {oauth_err}")

    return None, None

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

def save_status(status, message, uploaded=0, skipped=0, failed=0, failed_files=None):
    workspace_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    status_file = os.path.join(workspace_dir, "scratch", "gdrive_status.json")
    data = {
        "status": status,
        "message": message,
        "uploaded_count": uploaded,
        "skipped_count": skipped,
        "failed_count": failed,
        "failed_files": failed_files or []
    }
    try:
        os.makedirs(os.path.dirname(status_file), exist_ok=True)
        with open(status_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[GDRIVE] Status written to {status_file}")
    except Exception as e:
        print(f"[GDRIVE] [WARNING] Could not save status: {e}")

def main():
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

    key_json = os.getenv("GDRIVE_SERVICE_ACCOUNT_KEY")
    client_id = os.getenv("GDRIVE_CLIENT_ID")
    client_secret = os.getenv("GDRIVE_CLIENT_SECRET")
    refresh_token = os.getenv("GDRIVE_REFRESH_TOKEN")
    folder_id = os.getenv("GDRIVE_FOLDER_ID")
    
    if not folder_id:
        print("[GDRIVE] [WARNING] GDRIVE_FOLDER_ID env variable is missing. Skipping upload.")
        save_status("failed", "GDRIVE_FOLDER_ID env variable is missing", failed=len(files_to_upload), failed_files=[f[0] for f in files_to_upload])
        sys.exit(1)

    service, auth_type = authenticate_drive(key_json, client_id, client_secret, refresh_token, folder_id)

    if not service:
        err_msg = "Google Drive authentication failed (both Service Account and OAuth2 failed or missing)"
        print(f"[GDRIVE] [FATAL] {err_msg}. Exiting with error.")
        save_status("failed", err_msg, failed=len(files_to_upload), failed_files=[f[0] for f in files_to_upload])
        sys.exit(1)

    # 1. Fetch existing files in Google Drive folder
    print(f"[GDRIVE] Fetching list of existing files from Google Drive folder ({auth_type})...")
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
        print(f"[GDRIVE] [FATAL] Failed to list folder contents: {e}")
        save_status("failed", f"Failed to list folder contents: {e}", failed=len(files_to_upload), failed_files=[f[0] for f in files_to_upload])
        sys.exit(1)

    # 2. Upload only missing files
    uploaded_count = 0
    skipped_count = 0
    failed_count = 0
    failed_files = []
    
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
            else:
                failed_count += 1
                failed_files.append(fname)

    print(f"\n[GDRIVE] Sync completed:")
    print(f"  - Uploaded: {uploaded_count} files")
    print(f"  - Skipped: {skipped_count} files")
    print(f"  - Failed: {failed_count} files")

    if failed_count > 0:
        print(f"[GDRIVE] [FATAL] {failed_count} files failed to upload to Google Drive.")
        save_status("failed", f"{failed_count} files failed to upload", uploaded=uploaded_count, skipped=skipped_count, failed=failed_count, failed_files=failed_files)
        sys.exit(1)
    else:
        save_status("success", "All files synchronized successfully", uploaded=uploaded_count, skipped=skipped_count, failed=0)

if __name__ == "__main__":
    main()
