@echo off
rem Atalho para quem clonou o repositorio (Windows): roda o instalador com o Python do sistema.
rem Sem Python? Baixe o executavel pronto na pagina de Releases.
cd /d "%~dp0"
where py >nul 2>nul && (py -3 installer\elex_installer.py %* & goto fim)
where python >nul 2>nul && (python installer\elex_installer.py %* & goto fim)
echo Python 3 nao encontrado. Instale em https://www.python.org/downloads/ ou use o executavel da pagina de Releases.
:fim
pause
