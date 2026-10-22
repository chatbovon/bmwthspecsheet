import os
import sys
import json
import urllib.request
import urllib.error

# Add root directory to sys.path so we can import audits from send_daily_report
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from send_daily_report import (
    audit_data_discrepancies,
    audit_uncategorized_series,
    audit_gdrive_status,
    check_api_health,
    TH_CATALOG,
    EN_CATALOG,
    CUSTOM_TH_CATALOG,
    CUSTOM_EN_CATALOG
)

TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
REPO = os.environ.get("GITHUB_REPOSITORY", "chatbovon/bmwthspecsheet")
API_BASE = f"https://api.github.com/repos/{REPO}"

def api_request(method, endpoint, payload=None):
    if not TOKEN:
        print(f"[GITHUB API SIMULATION] {method} {endpoint} | Payload keys: {list(payload.keys()) if payload else None}")
        return None

    url = f"{API_BASE}/{endpoint.lstrip('/')}"
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "BMW-Specsheet-Issue-Manager"
    }
    
    data = json.dumps(payload).encode("utf-8") if payload else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            res_data = res.read().decode("utf-8")
            return json.loads(res_data) if res_data else {}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        print(f"[GITHUB API ERROR] {method} {url} returned HTTP {e.code}: {err_body}")
        return None
    except Exception as e:
        print(f"[GITHUB API ERROR] Request to {url} failed: {e}")
        return None

def get_open_issues():
    if not TOKEN:
        return []
    issues = api_request("GET", "issues?state=open&per_page=100")
    if not issues or not isinstance(issues, list):
        return []
    # Filter out pull requests
    return [i for i in issues if "pull_request" not in i]

def sync_issue(identifier_tag, title, body, is_active, open_issues, labels=None):
    matching_issue = None
    for issue in open_issues:
        if identifier_tag in issue.get("title", ""):
            matching_issue = issue
            break

    if is_active:
        if matching_issue:
            issue_num = matching_issue["number"]
            print(f"[ISSUE] Issue #{issue_num} '{matching_issue['title']}' is already open. Adding progress update comment...")
            comment_payload = {
                "body": f"### 🔄 Automated Status Update\n\nThis issue remains active:\n\n{body}"
            }
            api_request("POST", f"issues/{issue_num}/comments", comment_payload)
        else:
            print(f"[ISSUE] Creating new issue: '{title}'...")
            issue_payload = {
                "title": title,
                "body": body,
                "labels": labels or ["automated-alert"]
            }
            res = api_request("POST", "issues", issue_payload)
            if res and "number" in res:
                print(f"[ISSUE] Successfully created Issue #{res['number']}!")
    else:
        # Problem is resolved, close the issue if open
        if matching_issue:
            issue_num = matching_issue["number"]
            print(f"[ISSUE] Condition resolved for '{identifier_tag}'. Closing Issue #{issue_num}...")
            close_comment = {
                "body": "### ✅ Issue Resolved\n\nAutomated audit confirms that this issue has been resolved in the latest pipeline run. Closing issue."
            }
            api_request("POST", f"issues/{issue_num}/comments", close_comment)
            api_request("PATCH", f"issues/{issue_num}", {"state": "closed"})
            print(f"[ISSUE] Successfully closed Issue #{issue_num}!")
        else:
            print(f"[ISSUE] Condition '{identifier_tag}' is clean (0 problems). No action needed.")

def main():
    print(f"[ISSUE MANAGER] Starting issue audit for repository: {REPO}")
    if not TOKEN:
        print("[ISSUE MANAGER] GITHUB_TOKEN not found. Running in dry-run / simulation mode.")
    
    open_issues = get_open_issues()
    print(f"[ISSUE MANAGER] Found {len(open_issues)} existing open issue(s).")

    # Load databases
    try:
        with open(TH_CATALOG, encoding="utf-8") as f:
            th_data = json.load(f)
        with open(EN_CATALOG, encoding="utf-8") as f:
            en_data = json.load(f)
    except Exception as e:
        print(f"[ISSUE MANAGER] [ERROR] Failed to load catalog databases: {e}")
        return

    custom_th_data = []
    custom_en_data = []
    if os.path.exists(CUSTOM_TH_CATALOG):
        try:
            with open(CUSTOM_TH_CATALOG, encoding="utf-8") as f:
                custom_th_data = json.load(f)
        except:
            pass
    if os.path.exists(CUSTOM_EN_CATALOG):
        try:
            with open(CUSTOM_EN_CATALOG, encoding="utf-8") as f:
                custom_en_data = json.load(f)
        except:
            pass

    # ---------------------------------------------------------
    # 1. Check Google Drive Backup Status
    # ---------------------------------------------------------
    gdrive_data = audit_gdrive_status()
    gdrive_failed = False
    gdrive_body = ""
    if gdrive_data:
        g_status = gdrive_data.get("status")
        g_failed_count = gdrive_data.get("failed_count", 0)
        g_msg = gdrive_data.get("message", "")
        failed_files = gdrive_data.get("failed_files", [])

        if g_status == "failed" or g_failed_count > 0:
            gdrive_failed = True
            file_list_md = "\n".join([f"- `{fn}`" for fn in failed_files[:15]])
            if len(failed_files) > 15:
                file_list_md += f"\n- *... and {len(failed_files) - 15} more files.*"

            gdrive_body = f"""## 🚨 Google Drive Upload Failed / Incomplete

**Reason:** {g_msg}  
**Failed Files Count:** {g_failed_count}  

### 📄 Files Pending Upload:
{file_list_md}

### 🛡️ Safety Fallback Action Taken:
The automated workflow has temporarily committed these PDFs to the GitHub repository as a safety backup to ensure no data loss occurred when the runner terminated.

### 🛠️ Required Action:
1. Verify Google Drive OAuth2 credentials / Refresh Token status in GitHub Repository Secrets (`GDRIVE_REFRESH_TOKEN`, `GDRIVE_FOLDER_ID`).
2. If using OAuth2 with testing mode, ensure the token is re-authorized or publish the OAuth Consent Screen to Production.
"""

    sync_issue(
        identifier_tag="[Backup Alert]",
        title="🚨 [Backup Alert] Google Drive Backup Incomplete / Failed",
        body=gdrive_body,
        is_active=gdrive_failed,
        open_issues=open_issues,
        labels=["automated-alert", "bug", "backup"]
    )

    # ---------------------------------------------------------
    # 2. Check Category 99 (Uncategorized Series)
    # ---------------------------------------------------------
    uncategorized = audit_uncategorized_series(th_data, en_data, custom_th_data, custom_en_data)
    cat99_active = len(uncategorized) > 0
    cat99_body = ""
    if cat99_active:
        rows_md = ""
        for u in uncategorized:
            models_str = ", ".join(u["models"][:3])
            if len(u["models"]) > 3:
                models_str += f" (+{len(u['models'])-3} models)"
            rows_md += f"| **{u['database']}** | `{u['series']}` | `{u['pdf_source']}` | {models_str} |\n"

        cat99_body = f"""## 🚨 Uncategorized Series Detected (Category 99)

The following series could not be categorized into any of the standard BMW Series groups (Series 2-8, X, Z, i, M, XM). This causes them to fall into Category 99 at the bottom of the dropdown:

| Database | Series Name | PDF Source | Models |
| :--- | :--- | :--- | :--- |
{rows_md}

### 🛠️ Required Action:
- Check `detect_series_and_fuel` or update the series name formatting in `bmw_master_specs.json` / `bmw_custom_specs.json`.
"""

    sync_issue(
        identifier_tag="[Data Alert: Category 99]",
        title="🚨 [Data Alert: Category 99] Uncategorized Series Detected",
        body=cat99_body,
        is_active=cat99_active,
        open_issues=open_issues,
        labels=["automated-alert", "bug", "data-integrity"]
    )

    # ---------------------------------------------------------
    # 3. Check TH / EN Specsheet Alignment Discrepancies
    # ---------------------------------------------------------
    discrepancies, total_checks = audit_data_discrepancies(th_data, en_data)
    disc_active = len(discrepancies) > 0
    disc_body = ""
    if disc_active:
        disc_rows = ""
        for d in discrepancies[:20]:
            disc_rows += f"| **{d['model']}** | `{d['type']}` | {d['description']} |\n"
        if len(discrepancies) > 20:
            disc_rows += f"| ... | ... | *... and {len(discrepancies) - 20} more discrepancies.* |\n"

        disc_body = f"""## ⚠️ TH / EN Specsheet Alignment Discrepancies ({len(discrepancies)} detected)

Strict parity check detected discrepancies between Thai and English brochures:

| Model | Error Type | Description |
| :--- | :--- | :--- |
{disc_rows}

### 🛠️ Required Action:
- Review the affected models in `bmw_master_specs.json` and `bmw_master_specs_en.json`.
- If caused by source PDF printing typos published by BMW Thailand, add correction rules in `manual_overrides.json`.
- If caused by AI extraction mismatch, review extractor prompt or post-processing healing rules.
"""

    sync_issue(
        identifier_tag="[Spec Mismatch]",
        title=f"⚠️ [Spec Mismatch] TH / EN Specsheet Alignment Discrepancies ({len(discrepancies)} Issues)",
        body=disc_body,
        is_active=disc_active,
        open_issues=open_issues,
        labels=["automated-alert", "data-integrity"]
    )

    # ---------------------------------------------------------
    # 4. Check API Health
    # ---------------------------------------------------------
    api_status = check_api_health()
    api_failed = any("Not Configured" in s or "Invalid" in s for s in api_status)
    api_body = ""
    if api_failed:
        api_body = "## 🔑 API Key Health Alert\n\nOne or more required API keys are not configured or invalid:\n\n"
        for s in api_status:
            status_emoji = "❌" if ("Not Configured" in s or "Invalid" in s) else "✅"
            api_body += f"- {status_emoji} **{s}**\n"
        api_body += "\n### 🛠️ Required Action:\n- Update the required keys in GitHub Repository Secrets."

    sync_issue(
        identifier_tag="[API Alert]",
        title="🔑 [API Alert] API Key Invalid or Missing",
        body=api_body,
        is_active=api_failed,
        open_issues=open_issues,
        labels=["automated-alert", "configuration"]
    )

    print("[ISSUE MANAGER] All issue audits completed.")

if __name__ == "__main__":
    main()
