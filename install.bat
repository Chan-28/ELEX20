@echo off
rem Atalho para quem clonou o repositorio (Windows). Instala a biblioteca da interface em um
rem ambiente isolado; se nao conseguir, o instalador segue com perguntas em texto simples.
cd /d "%~dp0"
set "TEXTUAL=textual==8.2.8"
set "VENV=.installer-venv\Scripts\python.exe"
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo Python 3 not found. Install it from https://www.python.org/downloads/ or use the executable from the Releases page.
  goto fim
)
if not exist "%VENV%" %PY% -m venv .installer-venv >nul 2>nul
if exist "%VENV%" (
  "%VENV%" -m pip install --quiet --disable-pip-version-check "%TEXTUAL%" >nul 2>nul && (
    "%VENV%" installer\elex_installer.py %*
    goto fim
  )
)
echo Could not set up the full-screen interface; using plain text prompts.
%PY% installer\elex_installer.py %*
:fim
pause
