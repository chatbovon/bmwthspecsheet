#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BMW Dynamic Specsheet - Spec Editor Local Backend Server
Handles APIs for:
1. Fetching models & dual-language specifications (TH/EN)
2. Managing Layer 2 PDF Overrides (manual_overrides.json) with Auto-Backup
3. Managing Layer 3 Compare Enhancements (compare_enhancements.json) with Auto-Backup
4. Serving the editor web console (editor.html)
"""

import os
import sys
import json
import shutil
import argparse
from datetime import datetime
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Force UTF-8 stdout
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKUPS_DIR = os.path.join(WORKSPACE_DIR, "backups")
MASTER_TH_FILE = os.path.join(WORKSPACE_DIR, "bmw_master_specs.json")
MASTER_EN_FILE = os.path.join(WORKSPACE_DIR, "bmw_master_specs_en.json")
OVERRIDES_FILE = os.path.join(WORKSPACE_DIR, "manual_overrides.json")
ENHANCEMENTS_FILE = os.path.join(WORKSPACE_DIR, "compare_enhancements.json")

def ensure_backups_dir():
    if not os.path.exists(BACKUPS_DIR):
        os.makedirs(BACKUPS_DIR, exist_ok=True)

def create_auto_backup(filepath, prefix="backup"):
    ensure_backups_dir()
    if not os.path.exists(filepath):
        return None
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    basename = os.path.basename(filepath)
    name_part, ext = os.path.splitext(basename)
    backup_filename = f"{name_part}_{timestamp}{ext}"
    backup_path = os.path.join(BACKUPS_DIR, backup_filename)
    shutil.copy2(filepath, backup_path)
    return backup_filename

def load_json_file(filepath, default_factory=dict):
    if not os.path.exists(filepath):
        return default_factory()
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[ERROR] Failed to load {filepath}: {e}")
        return default_factory()

def save_json_file(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

class SpecEditorHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WORKSPACE_DIR, **kwargs)

    def end_headers(self):
        # Enable CORS for local development
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def send_json(self, status_code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/api/health":
            self.send_json(200, {
                "status": "ok",
                "timestamp": datetime.now().isoformat(),
                "server": "BMW Spec Editor Local Backend"
            })
            return

        if path == "/api/models":
            self.handle_get_models()
            return

        if path == "/api/model_details":
            model_name = query.get("model_name", [""])[0]
            self.handle_get_model_details(model_name)
            return

        if path == "/api/backups":
            self.handle_get_backups()
            return

        # Redirect root to editor.html
        if path == "/" or path == "":
            self.send_response(302)
            self.send_header("Location", "/editor.html")
            self.end_headers()
            return

        # Fallback to static file serving
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        try:
            content_length = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(content_length)
            body = json.loads(post_data.decode("utf-8")) if post_data else {}
        except Exception as e:
            self.send_json(400, {"success": False, "error": f"Invalid JSON payload: {e}"})
            return

        if path == "/api/save_compare_enhancement":
            self.handle_save_compare_enhancement(body)
            return

        if path == "/api/delete_compare_enhancement":
            self.handle_delete_compare_enhancement(body)
            return

        if path == "/api/save_override":
            self.handle_save_override(body)
            return

        self.send_json(404, {"success": False, "error": f"Unknown endpoint: {path}"})

    def handle_get_models(self):
        th_data = load_json_file(MASTER_TH_FILE, list)
        en_data = load_json_file(MASTER_EN_FILE, list)
        enhancements = load_json_file(ENHANCEMENTS_FILE, dict).get("models", {})
        overrides = load_json_file(OVERRIDES_FILE, dict)

        # Map EN models by model_name
        en_map = {}
        for s in en_data:
            s_name = s.get("series", "")
            for m in s.get("models", []):
                m_name = m.get("model_name", "")
                en_map[m_name] = {
                    "series": s_name,
                    "pdf_source": m.get("pdf_source") or s.get("pdf_source", "")
                }

        model_list = []
        for s in th_data:
            s_name = s.get("series", "")
            for m in s.get("models", []):
                m_name = m.get("model_name", "")
                pdf_source_th = m.get("pdf_source") or s.get("pdf_source", "")
                en_info = en_map.get(m_name, {})
                
                # Check enhancements
                has_enh = m_name in enhancements
                enh_items = enhancements.get(m_name, {})
                enh_count = 0
                if isinstance(enh_items.get("th"), list):
                    enh_count = len(enh_items.get("th"))
                elif isinstance(enh_items.get("th"), dict) and enh_items.get("th"):
                    enh_count = 1

                # Check manual overrides
                has_ovr = False
                pdf_base = os.path.basename(pdf_source_th)
                for prefix, p_data in overrides.items():
                    if prefix.startswith("_"):
                        continue
                    if pdf_base.startswith(prefix) and isinstance(p_data, dict):
                        if m_name in p_data:
                            has_ovr = True
                            break

                model_list.append({
                    "model_name": m_name,
                    "series_th": s_name,
                    "series_en": en_info.get("series", s_name),
                    "pdf_source_th": pdf_source_th,
                    "pdf_source_en": en_info.get("pdf_source", ""),
                    "has_enhancement": has_enh,
                    "enhancement_count": enh_count,
                    "has_override": has_ovr
                })

        self.send_json(200, {"success": True, "count": len(model_list), "models": model_list})

    def handle_get_model_details(self, model_name):
        if not model_name:
            self.send_json(400, {"success": False, "error": "Missing model_name parameter"})
            return

        th_data = load_json_file(MASTER_TH_FILE, list)
        en_data = load_json_file(MASTER_EN_FILE, list)
        enhancements = load_json_file(ENHANCEMENTS_FILE, dict).get("models", {})
        overrides = load_json_file(OVERRIDES_FILE, dict)

        # Find TH model
        th_model = None
        th_series = ""
        for s in th_data:
            for m in s.get("models", []):
                if m.get("model_name", "").strip().lower() == model_name.strip().lower():
                    th_model = m
                    th_series = s.get("series", "")
                    break
            if th_model:
                break

        # Find EN model
        en_model = None
        en_series = ""
        for s in en_data:
            for m in s.get("models", []):
                if m.get("model_name", "").strip().lower() == model_name.strip().lower():
                    en_model = m
                    en_series = s.get("series", "")
                    break
            if en_model:
                break

        if not th_model and not en_model:
            self.send_json(404, {"success": False, "error": f"Model '{model_name}' not found"})
            return

        # Find overrides for this model
        matched_overrides = []
        pdf_source = (th_model or {}).get("pdf_source", "")
        pdf_base = os.path.basename(pdf_source)
        for prefix, p_data in overrides.items():
            if prefix.startswith("_"):
                continue
            if pdf_base.startswith(prefix) and isinstance(p_data, dict):
                for m_key, cat_data in p_data.items():
                    if m_key.strip().lower() == model_name.strip().lower() and isinstance(cat_data, dict):
                        for cat_name, topics in cat_data.items():
                            if cat_name.startswith("_"):
                                continue
                            if isinstance(topics, dict):
                                for top_name, val in topics.items():
                                    matched_overrides.append({
                                        "prefix": prefix,
                                        "category": cat_name,
                                        "topic": top_name,
                                        "value": val
                                    })

        # Find enhancements
        model_enh = enhancements.get(model_name, {})
        # Normalize to list
        def normalize_enh_list(val):
            if not val:
                return []
            if isinstance(val, list):
                return val
            if isinstance(val, dict):
                if "topic" in val:
                    return [val]
                return list(val.values())
            return []

        th_enh_list = normalize_enh_list(model_enh.get("th"))
        en_enh_list = normalize_enh_list(model_enh.get("en"))

        self.send_json(200, {
            "success": True,
            "model_name": model_name,
            "th": {
                "series": th_series,
                "pdf_source": (th_model or {}).get("pdf_source", ""),
                "specifications": (th_model or {}).get("specifications", [])
            },
            "en": {
                "series": en_series,
                "pdf_source": (en_model or {}).get("pdf_source", ""),
                "specifications": (en_model or {}).get("specifications", [])
            },
            "overrides": matched_overrides,
            "enhancements": {
                "th": th_enh_list,
                "en": en_enh_list
            }
        })

    def handle_save_compare_enhancement(self, payload):
        model_name = payload.get("model_name", "").strip()
        th_item = payload.get("th")
        en_item = payload.get("en")

        if not model_name:
            self.send_json(400, {"success": False, "error": "model_name is required"})
            return

        if not th_item and not en_item:
            self.send_json(400, {"success": False, "error": "At least th or en enhancement data is required"})
            return

        # 1. Create auto-backup
        backup_file = create_auto_backup(ENHANCEMENTS_FILE, "compare_enhancements")

        # 2. Load current enhancements
        enh_data = load_json_file(ENHANCEMENTS_FILE, dict)
        if "_schema_version" not in enh_data:
            enh_data["_schema_version"] = "1.0"
        if "_description" not in enh_data:
            enh_data["_description"] = "Compare-only vehicle equipment enhancements (Real-world equipment omitted in official BMW Thailand brochures)"
        if "models" not in enh_data:
            enh_data["models"] = {}

        models_dict = enh_data["models"]
        if model_name not in models_dict:
            models_dict[model_name] = {"th": [], "en": []}

        # Normalize existing entries to lists
        for lang in ["th", "en"]:
            curr = models_dict[model_name].get(lang)
            if not curr:
                models_dict[model_name][lang] = []
            elif isinstance(curr, dict):
                models_dict[model_name][lang] = [curr] if "topic" in curr else list(curr.values())

        today_str = datetime.now().strftime("%Y-%m-%d")

        # Upsert TH
        if th_item and th_item.get("topic"):
            topic_clean = th_item["topic"].strip()
            orig_topic = th_item.get("original_topic", "").strip()
            th_obj = {
                "category": th_item.get("category", "").strip(),
                "topic": topic_clean,
                "original_topic": orig_topic,
                "value": th_item.get("value", "■").strip(),
                "is_real_vehicle_verified": True,
                "note": th_item.get("note", "").strip(),
                "verified_date": th_item.get("verified_date") or today_str
            }
            # Replace existing topic or append
            th_list = models_dict[model_name]["th"]
            found = False
            for idx, existing in enumerate(th_list):
                ex_top = existing.get("topic", "").strip().lower()
                ex_orig = existing.get("original_topic", "").strip().lower()
                if ex_top == topic_clean.lower() or (orig_topic and (ex_top == orig_topic.lower() or ex_orig == orig_topic.lower())):
                    th_list[idx] = th_obj
                    found = True
                    break
            if not found:
                th_list.append(th_obj)

        # Upsert EN
        if en_item and en_item.get("topic"):
            topic_clean = en_item["topic"].strip()
            en_obj = {
                "category": en_item.get("category", "").strip(),
                "topic": topic_clean,
                "value": en_item.get("value", "■").strip(),
                "is_real_vehicle_verified": True,
                "note": en_item.get("note", "").strip(),
                "verified_date": en_item.get("verified_date") or today_str
            }
            en_list = models_dict[model_name]["en"]
            found = False
            for idx, existing in enumerate(en_list):
                if existing.get("topic", "").strip().lower() == topic_clean.lower():
                    en_list[idx] = en_obj
                    found = True
                    break
            if not found:
                en_list.append(en_obj)

        save_json_file(ENHANCEMENTS_FILE, enh_data)

        self.send_json(200, {
            "success": True,
            "message": f"Compare Enhancement for '{model_name}' saved successfully",
            "backup_file": backup_file,
            "data": models_dict[model_name]
        })

    def handle_delete_compare_enhancement(self, payload):
        model_name = payload.get("model_name", "").strip()
        topic_th = payload.get("topic_th", "").strip()
        topic_en = payload.get("topic_en", "").strip()

        if not model_name:
            self.send_json(400, {"success": False, "error": "model_name is required"})
            return

        enh_data = load_json_file(ENHANCEMENTS_FILE, dict)
        models_dict = enh_data.get("models", {})
        if model_name not in models_dict:
            self.send_json(404, {"success": False, "error": f"Model '{model_name}' not found in enhancements"})
            return

        # Backup
        backup_file = create_auto_backup(ENHANCEMENTS_FILE, "compare_enhancements")

        # Delete matching items
        if topic_th and isinstance(models_dict[model_name].get("th"), list):
            models_dict[model_name]["th"] = [
                x for x in models_dict[model_name]["th"]
                if x.get("topic", "").strip().lower() != topic_th.lower()
            ]

        if topic_en and isinstance(models_dict[model_name].get("en"), list):
            models_dict[model_name]["en"] = [
                x for x in models_dict[model_name]["en"]
                if x.get("topic", "").strip().lower() != topic_en.lower()
            ]

        save_json_file(ENHANCEMENTS_FILE, enh_data)

        self.send_json(200, {
            "success": True,
            "message": f"Enhancement removed for '{model_name}'",
            "backup_file": backup_file
        })

    def handle_save_override(self, payload):
        model_name = payload.get("model_name", "").strip()
        pdf_prefix = payload.get("pdf_prefix", "").strip()
        category = payload.get("category", "").strip()
        topic = payload.get("topic", "").strip()
        value = payload.get("value", "").strip()
        reason = payload.get("reason", "").strip()
        lang = payload.get("lang", "th").lower()

        if not model_name or not category or not topic:
            self.send_json(400, {"success": False, "error": "model_name, category, and topic are required"})
            return

        # If pdf_prefix is not provided, look it up from master specs
        if not pdf_prefix:
            master_file = MASTER_EN_FILE if lang == "en" else MASTER_TH_FILE
            master_data = load_json_file(master_file, list)
            for s in master_data:
                for m in s.get("models", []):
                    if m.get("model_name", "").strip().lower() == model_name.lower():
                        src = m.get("pdf_source") or s.get("pdf_source", "")
                        pdf_prefix = os.path.basename(src).replace(".pdf", "")
                        break
                if pdf_prefix:
                    break

        if not pdf_prefix:
            pdf_prefix = model_name

        # Create auto-backup
        backup_file = create_auto_backup(OVERRIDES_FILE, "manual_overrides")

        overrides = load_json_file(OVERRIDES_FILE, dict)
        if pdf_prefix not in overrides:
            overrides[pdf_prefix] = {}
            if reason:
                overrides[pdf_prefix]["_comment"] = reason

        if model_name not in overrides[pdf_prefix]:
            overrides[pdf_prefix][model_name] = {}

        if category not in overrides[pdf_prefix][model_name]:
            overrides[pdf_prefix][model_name][category] = {}

        overrides[pdf_prefix][model_name][category][topic] = value
        save_json_file(OVERRIDES_FILE, overrides)

        self.send_json(200, {
            "success": True,
            "message": f"Global Override for '{model_name}' saved to prefix '{pdf_prefix}'",
            "backup_file": backup_file
        })

    def handle_get_backups(self):
        ensure_backups_dir()
        files = []
        for fname in sorted(os.listdir(BACKUPS_DIR), reverse=True):
            fpath = os.path.join(BACKUPS_DIR, fname)
            if os.path.isfile(fpath) and fname.endswith(".json"):
                stat = os.stat(fpath)
                files.append({
                    "filename": fname,
                    "size_bytes": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                })
        self.send_json(200, {"success": True, "count": len(files), "backups": files})

def run_server(host="0.0.0.0", port=8000):
    server_address = (host, port)
    httpd = ThreadingHTTPServer(server_address, SpecEditorHandler)
    
    # Detect local IP for LAN / mobile access
    local_ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ips.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass

    print(f"================================================================")
    print(f"BMW Specsheet Local Server running on port {port}:")
    print(f"  Local PC:   http://localhost:{port}/index.html")
    print(f"  Compare:    http://localhost:{port}/compare.html")
    print(f"  Editor:     http://localhost:{port}/editor.html")
    for ip in local_ips:
        print(f"  Mobile/LAN: http://{ip}:{port}/index.html")
        print(f"              http://{ip}:{port}/compare.html")
    print(f"Working Directory: {WORKSPACE_DIR}")
    print(f"Backups Directory: {BACKUPS_DIR}")
    print(f"Press Ctrl+C to terminate.")
    print(f"================================================================")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server gracefully...")
        httpd.server_close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BMW Spec Editor Local Backend Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen (default: 8000)")
    args = parser.parse_args()
    run_server(host=args.host, port=args.port)
