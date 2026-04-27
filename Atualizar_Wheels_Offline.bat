@echo off
setlocal

powershell -ExecutionPolicy Bypass -File "%~dp0scripts\baixar_wheels.ps1"
if errorlevel 1 (
  echo [ERRO] Falha ao baixar wheels offline.
  pause
  exit /b 1
)

echo Wheels atualizadas em third_party\wheels.
pause
endlocal
