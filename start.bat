@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Menyiapkan virtual environment...
  py -3 -m venv .venv || goto :error
  ".venv\Scripts\python.exe" -m pip install --upgrade pip || goto :error
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :error
)

echo Menjalankan aplikasi...
".venv\Scripts\python.exe" main.py
if errorlevel 1 goto :error
goto :eof

:error
echo.
echo Gagal menjalankan aplikasi.
echo Pastikan Python Launcher (py) dan koneksi internet tersedia saat setup pertama.
pause
exit /b 1
