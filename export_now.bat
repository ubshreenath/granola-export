@echo off
REM Run the export once, on demand. Any arguments are passed through, e.g.:
REM   export_now.bat --out "D:\Notes\Granola"
python "%~dp0export_granola.py" %*
echo.
pause
