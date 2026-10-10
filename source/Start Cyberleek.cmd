@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 goto use_python
py -3.12 launch.py
if not errorlevel 1 exit /b 0
where python >nul 2>&1
if errorlevel 1 goto failed
:use_python
python launch.py
if not errorlevel 1 exit /b 0
:failed
echo.
echo Install Python 3.12 from https://www.python.org/downloads/windows/
echo Include Tcl/Tk and the Python launcher during installation.
echo Then double-click this launcher again. See README.md for details.
pause
exit /b 1
