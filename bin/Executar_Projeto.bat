@echo off
setlocal

set "ROOT=%~dp0..\"

if not exist "%ROOT%python-embed\python.exe" (
	echo [ERRO] python-embed nao encontrado.
	pause
	exit /b 1
)

"%ROOT%python-embed\python.exe" -c "import PyQt6, pyqtgraph, mne, numpy, pylsl" >nul 2>nul
if errorlevel 1 (
	echo [ERRO] Dependencias Python ausentes.
	echo Execute antes: %~dp0Preparar_Ambiente_Portatil.bat
	pause
	exit /b 1
)

"%ROOT%python-embed\python.exe" -c "import rpy2" >nul 2>nul
if errorlevel 1 (
	echo [AVISO] rpy2 nao encontrado. O programa pode usar fallback Python para graficos estatisticos.
)

"%ROOT%python-embed\python.exe" "%ROOT%src\Grafico.py"
pause
endlocal