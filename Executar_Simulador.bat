@echo off
setlocal

if not exist ".\python-embed\python.exe" (
	echo [ERRO] python-embed nao encontrado.
	pause
	exit /b 1
)

".\python-embed\python.exe" -c "import numpy, scipy, pylsl" >nul 2>nul
if errorlevel 1 (
	echo [ERRO] Dependencias Python ausentes.
	echo Execute antes: Preparar_Ambiente_Portatil.bat
	pause
	exit /b 1
)

".\python-embed\python.exe" "simulador_lsl_emg.py"
pause
endlocal