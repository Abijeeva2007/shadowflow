@echo off
REM ShadowFlow one-time setup for Windows (run from the shadowflow folder).
REM Requires Python 3.11 (`py -3.11`) and Node.js (`npm`) on PATH.

echo ==^> creating backend venv and installing backend deps
cd backend || goto :err
py -3.11 -m venv .venv || goto :err
call .venv\Scripts\activate.bat || goto :err
python -m pip install --upgrade pip
python -m pip install -r requirements.txt || goto :err
cd ..

echo ==^> installing frontend deps (npm install)
cd frontend || goto :err
call npm install || goto :err
cd ..

echo ==^> done. Next: scripts\run_data.bat then scripts\run_windows.ps1
goto :eof

:err
echo SETUP FAILED with error %errorlevel%
exit /b 1
