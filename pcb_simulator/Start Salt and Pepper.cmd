@echo off
cd /d "%~dp0\.."
.venv\Scripts\python.exe pcb_simulator\server.py
if errorlevel 1 pause
