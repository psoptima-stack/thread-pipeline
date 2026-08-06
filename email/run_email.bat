@echo off
chcp 65001 >nul
cd /d "C:\Users\유나\OneDrive\바탕 화면\writer"
".venv\Scripts\python.exe" "email\send_today_post.py" >> "email\log.txt" 2>&1
