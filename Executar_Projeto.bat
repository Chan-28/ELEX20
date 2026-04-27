@echo off
setlocal

if not exist ".\python-embed\python.exe" (
	echo [ERRO] python-embed nao encontrado.
	pause
	exit /b 1
)

".\python-embed\python.exe" -c "import PyQt6, pyqtgraph, mne, numpy, pylsl" >nul 2>nul
if errorlevel 1 (
	echo [ERRO] Dependencias Python ausentes.
	echo Execute antes: Preparar_Ambiente_Portatil.bat
	pause
	exit /b 1
)

".\python-embed\python.exe" -c "import rpy2" >nul 2>nul
if errorlevel 1 (
	echo [AVISO] rpy2 nao encontrado. O programa pode usar fallback Python para graficos estatisticos.
)

".\python-embed\python.exe" "Grafico.py"
pause
endlocal