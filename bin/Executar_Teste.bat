@echo off
setlocal
set "ROOT=%~dp0..\"

if not exist "%ROOT%python-embed\python.exe" (
	echo [ERRO] python-embed nao encontrado.
	pause
	exit /b 1
)

"%ROOT%python-embed\python.exe" "%ROOT%tests\teste_lsl_integracao.py"
pause
endlocal