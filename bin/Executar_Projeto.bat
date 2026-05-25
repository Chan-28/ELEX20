@echo off
setlocal

set "ROOT=%~dp0..\"

python -c "import serial, PyQt6, pyqtgraph, mne, numpy, scipy, pylsl" >nul 2>nul
if errorlevel 1 (
	echo [ERRO] Dependencias Python ausentes.
	echo Instale com: pip install -r requirements.txt
	pause
	exit /b 1
)

start "Captura EMG" cmd /k python "%ROOT%tools\captar_Dados_serial.py"
start "Filtro EMG" cmd /k python "%ROOT%tools\filtrar_Dados.py"
start "Grafico EMG" cmd /k python "%ROOT%src\Grafico.py"

echo.
echo Pipeline EMG iniciado.
echo  - Captura serial: captar_Dados_serial.py
echo  - Filtro LSL: filtrar_Dados.py
echo  - Grafico LSL: Grafico.py
pause
endlocal