@echo off
setlocal

set "ROOT=%~dp0..\"

python -c "import PyQt6, pyqtgraph, mne, numpy, pylsl" >nul 2>nul
if errorlevel 1 (
	echo [ERRO] Dependencias Python ausentes.
	echo Instale com: pip install -r requirements.txt
	pause
	exit /b 1
)

python "%ROOT%src\Grafico.py"
pause
endlocal