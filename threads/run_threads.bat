@echo off
chcp 65001 >nul
cd /d "C:\Users\유나\OneDrive\바탕 화면\writer"
set PYTHONIOENCODING=utf-8
".venv\Scripts\python.exe" "threads\post_to_threads.py" >> "threads\log.txt" 2>&1
