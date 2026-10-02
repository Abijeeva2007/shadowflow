@echo off
REM ShadowFlow: regenerate synthetic data and run the detection pipeline (Windows).
REM Run from the shadowflow folder after setup_windows.bat.

cd backend || goto :err
if not exist .venv\Scripts\python.exe (
  echo Backend venv not found. Run scripts\setup_windows.bat first.
  exit /b 1
)
.venv\Scripts\python.exe generate_data.py || goto :err
.venv\Scripts\python.exe -c "from engine.pipeline import run_pipeline; st = run_pipeline(); print('pipeline ok:', len(st.rings), 'rings,', st.filter_counts['alerts_before'], '->', st.filter_counts['alerts_after'], 'alerts')" || goto :err
cd ..
goto :eof

:err
echo DATA GENERATION FAILED with error %errorlevel%
exit /b 1
