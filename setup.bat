@echo off
cd /d "%~dp0"
echo Installing Python libraries...
python -m pip install -r requirements.txt
echo Downloading the private AI model (about 2 GB, first time only)...
ollama pull llama3.2:3b
echo Copying the payroll data from the live database (read-only) and preparing the demo...
python prepare.py --live
echo.
echo Ready. Double-click start_demo.bat to open the portal.
pause
