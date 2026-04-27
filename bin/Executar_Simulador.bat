@echo off
setlocal

set "ROOT=%~dp0..\"

if not exist "%ROOT%python-embed\python.exe" (
	echo [ERRO] python-embed nao encontrado.
	pause
	exit /b 1
)

"%ROOT%python-embed\python.exe" -c "import numpy, scipy, pylsl" >nul 2>nul
if errorlevel 1 (
	echo [ERRO] Dependencias Python ausentes.
	echo Execute antes: %~dp0Preparar_Ambiente_Portatil.bat
	pause
	exit /b 1
)

"%ROOT%python-embed\python.exe" "%ROOT%src\simulador_lsl_emg.py"
pause
endlocal