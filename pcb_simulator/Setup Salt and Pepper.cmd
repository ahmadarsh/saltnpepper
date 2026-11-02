@echo off
cd /d "%~dp0\.."
py -3 -m venv .venv
if errorlevel 1 goto :failed
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :failed
echo Setup complete. Open Start Salt and Pepper.cmd.
pause
exit /b 0
:failed
echo Setup failed. Install 64-bit Python 3.11 or newer and try again.
pause
exit /b 1
