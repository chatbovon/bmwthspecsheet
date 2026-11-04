@echo off
chcp 65001 >nul
echo ====================================================================
echo Starting BMW Spec Editor Local Server...
echo ====================================================================
start "" "http://127.0.0.1:8000/editor.html"
python editor_server.py --port 8000
pause
