@echo off
cd /d "%~dp0"
if not exist user_settings.json (
  echo First run: starting setup...
  python setup.py
  if errorlevel 1 exit /b 1
)
title Photo to prompt - watching
echo Start LM Studio's server (and ComfyUI, if you set it up), then drop photos into your photos folder.
python watch.py
pause
