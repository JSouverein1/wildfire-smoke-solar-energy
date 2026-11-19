@echo off
setlocal
REM Open a Command Prompt in this folder or double-click this file.
cd /d "%~dp0"
python scripts\run_project.py --start-year 2005 --end-year 2025 --months 6 7 8 9 10
if errorlevel 1 (
  echo.
  echo Pipeline reported an error. Read the messages above and rerun to resume.
  pause
  exit /b 1
)
echo.
echo Finished all requested stages. The results are under data\processed\ and figures\.
pause
