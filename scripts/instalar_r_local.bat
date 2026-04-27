@echo off
setlocal
set "PROJECT_ROOT=%~dp0.."
set "RSCRIPT=%PROJECT_ROOT%\R-Portable\App\R-Portable\bin\x64\Rscript.exe"

if not exist "%RSCRIPT%" (
  echo [ERRO] Rscript nao encontrado em: %RSCRIPT%
  echo Verifique se a pasta R-Portable foi copiada corretamente.
  exit /b 1
)

echo Instalando pacotes R na biblioteca local do projeto...
"%RSCRIPT%" "%PROJECT_ROOT%\scripts\install_r_packages_local.R" "%PROJECT_ROOT%"
if errorlevel 1 (
  echo [ERRO] Falha ao instalar pacotes R locais.
  exit /b 1
)

echo Pacotes R locais prontos.
endlocal
