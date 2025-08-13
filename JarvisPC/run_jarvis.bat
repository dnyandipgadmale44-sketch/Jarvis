@echo off
setlocal
cd /d %~dp0
if not exist .venv\Scripts\activate.bat (
    echo Creating venv...
    py -3 -m venv .venv
)
call .venv\Scripts\activate.bat
if exist requirements.txt (
    pip install -r requirements.txt
)
python main.py
