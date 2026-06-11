@echo off
cls
title Gerenciador do Ambiente Python (venv)
echo ============================================================
echo           VERIFICANDO AMBIENTE VIRTUAL (VENV)
echo ============================================================

:: 1. Define o nome padrão da pasta da venv (ajuste se a sua tiver outro nome)
set "VENV_DIR=.venv"

:: 2. Verifica se a pasta da venv existe. Se não existir, cria uma nova.
if not exist %VENV_DIR%\Scripts\activate.bat (
    echo [AVISO] Ambiente virtual '%VENV_DIR%' nao encontrado.
    echo [INFO] Criando um novo ambiente virtual...
    python -m venv %VENV_DIR%
    if errorlevel 1 (
        echo [ERRO] Falha ao criar a venv. O Python esta instalado no sistema?
        goto :error_exit
    )
    set "MUST_INSTALL=1"
)

:: 3. Ativa o ambiente virtual para que todos os comandos usem o Python isolado
echo [INFO] Ativando ambiente virtual...
call %VENV_DIR%\Scripts\activate.bat

:: 4. Se a venv acabou de ser criada ou se o requirements mudou, força a instalação
if defined MUST_INSTALL (
    echo [INFO] Instalando as dependencias do requirements.txt...
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    goto :verify_deps
)

:verify_deps
echo [INFO] Validando bibliotecas instaladas...
:: Nota: Testamos 'PIL' em vez de 'pillow', e adicionamos 'matplotlib', 'pandas' e 'sklearn'
python -c "import serial, PyQt6, pyqtgraph, mne, mne-qt-browser, numpy, scipy, pylsl, PIL, bleak, matplotlib, pandas, sklearn, psutil" >nul 2>nul

if errorlevel 1 (
    echo [AVISO] Algumas dependencias estao ausentes ou corrompidas na venv.
    echo [INFO] Atualizando ambiente com o requirements.txt...
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    
    :: Segunda validação de segurança
    python -c "import serial, PyQt6, pyqtgraph, mne, mne-qt-browser, numpy, scipy, pylsl, PIL, bleak, matplotlib, pandas, sklearn, psutil" >nul 2>nul
    if errorlevel 1 (
        echo [ERRO] Nao foi possivel alinhar as dependencias. Verifique o arquivo requirements.txt.
        goto :error_exit
    )
)

echo ============================================================
echo [SUCESSO] Ambiente validado e pronto para uso!
echo ============================================================
echo.
echo [INFO] Iniciando os programas simultaneamente em novos terminais...

:: 5. Executa os três scripts em paralelo, cada um em sua própria janela.
:: O parâmetro /k mantém a janela aberta depois que o script Python terminar ou falhar (bom para ver erros).
:: Se quiser que as janelas fechem sozinhas ao terminar, troque /k por /c

start "Captar Dados" cmd /k "call %VENV_DIR%\Scripts\activate.bat && python tools\captar_Dados.py"
start "Filtrar Dados" cmd /k "call %VENV_DIR%\Scripts\activate.bat && python tools\filtrar_Dados.py"
start "Grafico" cmd /k "call %VENV_DIR%\Scripts\activate.bat && python src\Grafico.py"

exit /b 0

:error_exit
pause
exit /b 1
