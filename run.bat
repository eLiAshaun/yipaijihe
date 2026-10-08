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

set "PIP=.venv\Scripts\python.exe -m pip install --disable-pip-version-check"
set "MIRROR=-i https://pypi.tuna.tsinghua.edu.cn/simple"

".venv\Scripts\python.exe" -c "import flask, flask_cors, dotenv, openai, requests" 2>nul
if errorlevel 1 (
  echo 正在安装依赖（首次约 1 分钟）...
  %PIP% -q --upgrade pip
  %PIP% -q -r requirements.txt || %PIP% -q %MIRROR% -r requirements.txt
)

rem 视频分析组件（本地语音转写 + 截取画面）：可选，装不上不影响其他功能
if not "%SKIP_VIDEO_DEPS%"=="1" (
  ".venv\Scripts\python.exe" -c "import faster_whisper, av, PIL, yt_dlp" 2>nul
  if errorlevel 1 (
    echo 正在安装视频分析组件（本地语音转写，约 100MB，只需一次）...
    %PIP% -r requirements-video.txt || %PIP% %MIRROR% -r requirements-video.txt || echo 视频分析组件没装上，将跳过「听语音」，其他功能不受影响
  )
)

if not exist ".env" copy ".env.example" ".env" >nul

set "OPEN_BROWSER=1"
set "PYTHONIOENCODING=utf-8"
".venv\Scripts\python.exe" app.py
pause