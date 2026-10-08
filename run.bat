@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
if not exist user_settings.json (
  echo First run: starting setup...
  python setup.py
  if errorlevel 1 exit /b 1
)
title Photo to prompt
echo LM Studio: load a vision model and start the local server (Developer tab) first.
set "FOLDER="
set /p "FOLDER=Photo folder (Enter to use the one from setup): "
if defined FOLDER set "FOLDER=!FOLDER:"=!"
start "Dashboard" /min python dashboard.py
if defined FOLDER (python photos_to_prompts.py "!FOLDER!") else (python photos_to_prompts.py)
pause
