@echo off
setlocal

set "ROOT=%~dp0..\"

python -c "import numpy, scipy, pylsl" >nul 2>nul
if errorlevel 1 (
	echo [ERRO] Dependencias Python ausentes.
	echo Instale com: pip install -r requirements.txt
	pause
	exit /b 1
)

python "%ROOT%src\simulador_lsl_emg.py"
pause
endlocal