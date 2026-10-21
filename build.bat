@echo off
setlocal
cd /d "%~dp0"
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
py -m PyInstaller --noconfirm --clean --onefile --windowed --name gamelist_editor main.py
if errorlevel 1 (
  echo.
  echo Build failed. Check the error messages above.
  pause
  exit /b 1
)
echo.
echo Build complete: dist\gamelist_editor.exe
pause
