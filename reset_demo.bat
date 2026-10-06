@echo off
cd /d "%~dp0"
echo Resetting the demo: fresh demo payrolls, every payroll checked, accuracy test (about 3 minutes)...
echo This uses the local copy, so it works even if the internet is slow.
python prepare.py
echo.
echo Ready. Double-click start_demo.bat to open the portal.
pause
