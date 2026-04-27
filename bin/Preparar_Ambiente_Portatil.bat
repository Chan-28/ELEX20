@echo off
setlocal

set "ROOT=%~dp0..\"

echo ============================================
echo  Preparando ambiente portatil do ELEX20
echo ============================================

powershell -ExecutionPolicy Bypass -File "%ROOT%scripts\instalar_python_local.ps1"
if errorlevel 1 (
  echo [ERRO] Falha ao preparar dependencias Python.
  exit /b 1
)

call "%ROOT%scripts\instalar_r_local.bat"
if errorlevel 1 (
  echo [ERRO] Falha ao preparar dependencias R.
  exit /b 1
)

echo.
echo Ambiente pronto. Execute:
echo   - Executar_Simulador.bat
echo   - Executar_Projeto.bat

echo.
pause
endlocal
