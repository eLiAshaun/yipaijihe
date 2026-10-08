@echo off
rem 一拍迹合 · 一键启动（Windows）
chcp 65001 >nul
cd /d "%~dp0"

where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>nul
if errorlevel 1 (
  echo 需要 Python 3.10 及以上版本：https://www.python.org/downloads/
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo 正在创建虚拟环境 .venv ...
  %PY% -m venv .venv
)

".venv\Scripts\python.exe" -c "import flask, flask_cors, dotenv, openai, requests" 2>nul
if errorlevel 1 (
  echo 正在安装依赖（首次约 1 分钟）...
  ".venv\Scripts\python.exe" -m pip install -q --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
)

if not exist ".env" copy ".env.example" ".env" >nul

set "OPEN_BROWSER=1"
set "PYTHONIOENCODING=utf-8"
".venv\Scripts\python.exe" app.py
pause