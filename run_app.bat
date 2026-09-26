@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
echo ========================================================
echo Starting DayBook Analytics Dashboard (Demo Khelauna)...
echo ========================================================
echo App URL: http://localhost:8501
echo.
python -m streamlit run app.py
pause
