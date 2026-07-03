import os
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ['https://www.googleapis.com/auth/drive']

def main():
    print("=== Google Drive OAuth2 Refresh Token Generator ===")
    client_id = input("Enter your OAuth2 Client ID: ").strip()
    client_secret = input("Enter your OAuth2 Client Secret: ").strip()
    
    if not client_id or not client_secret:
        print("[ERROR] Both Client ID and Client Secret are required.")
        return
        
    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token"
        }
    }
    
    try:
        # Run local server flow to authenticate
        flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)
        creds = flow.run_local_server(port=0)
        
        print("\n" + "="*70)
        print("🎉 SUCCESSFULLY GENERATED OAUTH2 CREDENTIALS!")
        print("="*70)
        print(f"GDRIVE_CLIENT_ID = {client_id}")
        print(f"GDRIVE_CLIENT_SECRET = {client_secret}")
        print(f"GDRIVE_REFRESH_TOKEN = {creds.refresh_token}")
        print("="*70)
        print("\nACTION REQUIRED:")
        print("1. Add GDRIVE_CLIENT_ID to your GitHub Secrets.")
        print("2. Add GDRIVE_CLIENT_SECRET to your GitHub Secrets.")
        print("3. Add GDRIVE_REFRESH_TOKEN to your GitHub Secrets.")
        print("4. You can also save them in your local .env file for local testing.")
        print("="*70)
        
    except Exception as e:
        print(f"\n[ERROR] Failed to run authorization flow: {e}")

if __name__ == "__main__":
    main()
