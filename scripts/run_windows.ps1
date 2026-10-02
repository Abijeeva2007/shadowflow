# ShadowFlow - start backend and frontend on Windows (PowerShell).
# Run from the shadowflow folder:
#   powershell -ExecutionPolicy Bypass -File scripts\run_windows.ps1
# Each server opens in its own console window; stop a server with Ctrl-C there.

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

Write-Host "Starting backend on :8000 (first start needs ~15s) ..."
Start-Process -WorkingDirectory "$root\backend" `
  -FilePath "$root\backend\.venv\Scripts\python.exe" `
  -ArgumentList "-m", "uvicorn", "main:app", "--port", "8000"

Write-Host "Starting frontend on :3000 ..."
Start-Process -WorkingDirectory "$root\frontend" `
  -FilePath "cmd.exe" `
  -ArgumentList "/c", "npx next dev -p 3000"

Write-Host ""
Write-Host "  backend  -> http://localhost:8000  (first start needs ~15s)"
Write-Host "  frontend -> http://localhost:3000"
Write-Host "Open http://localhost:3000 in your browser."
