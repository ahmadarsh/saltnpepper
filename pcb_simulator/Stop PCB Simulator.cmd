@echo off
cd /d "%~dp0\.."
python pcb_simulator\server.py --stop
if errorlevel 1 pause
