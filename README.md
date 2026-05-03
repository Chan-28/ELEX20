# ELEX20 - Analise Neurofisiologica Portatil (Windows)

Projeto para analise de sinais EMG em tempo real com LSL, visualizacao no MNE Browser (mne-qt-browser) e graficos estatisticos com R.

## Estrutura da pasta atual

- `python-embed/`: Python local do projeto
- `R-Portable/`: R local do projeto
- `scripts/`: scripts de instalacao e helpers
- `bin/`: scripts e lançadores (Executar_Projeto.bat, Executar_Simulador.bat, Preparar_Ambiente_Portatil.bat, Atualizar_Wheels_Offline.bat, etc.)
- `src/`: código principal do aplicativo (`Grafico.py`, `simulador_lsl_emg.py`)
- `tools/`: utilitários e helpers (`captar_Dados.py`, `filtrar_Dados.py`, `enviar_CSV_Dados.py`)
- `tests/`: testes e integração (`teste_lsl_integracao.py`)
- `third_party/`: (opcional) wheels e recursos offline
- `output/`: diretório onde os gráficos e arquivos gerados são salvos
- `README.md`, `requirements.txt` e outros arquivos de suporte na raiz

Nota sobre reorganização
------------------------
Arquivos foram reorganizados para melhorar manutenção:

- `bin/` contém os lançadores e scripts que o usuário executa.
- `src/` contém o código fonte do aplicativo que roda em tempo real.
- `tools/` contém utilitários auxiliares e scripts pequenos.
- `tests/` contém scripts de teste e integração.


## Instalacao de dependencias (Python e R)

### Metodo recomendado

1. Abra PowerShell na pasta do projeto.
2. Execute o preparador do ambiente:

```powershell
.\bin\Preparar_Ambiente_Portatil.bat
```

Esse comando chama:

- `scripts\instalar_python_local.ps1` (instala Python packages no `python-embed`)
- `scripts\instalar_r_local.bat` (instala pacotes R em `R-Portable\library`)

Arquivos de confirmacao criados quando conclui:

- `.deps_python_ok`
- `.deps_r_ok`

### Metodo manual (se precisar)

Instalar so Python:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\instalar_python_local.ps1
```

Instalar so R:

```powershell
.\scripts\instalar_r_local.bat
```

## Como rodar o Grafico.py

Ordem correta de execucao:

1. Execute `bin\Preparar_Ambiente_Portatil.bat` (somente no primeiro uso, ou quando mudar dependencia) no terminal: 
```powershell
.\bin\Preparar_Ambiente_Portatil.bat
```
2. Em um terminal, execute `bin\Executar_Simulador.bat`:
```powershell
.\bin\Executar_Simulador.bat
```
3. Em outro terminal, execute `bin\Executar_Projeto.bat`:
```powershell
.\bin\Executar_Projeto.bat
```
Fluxo equivalente direto com Python local:

```powershell
.\python-embed\python.exe .\src\simulador_lsl_emg.py
.\python-embed\python.exe .\src\Grafico.py
```

## VS Code (corrigir erros de import no editor)

Se o VS Code mostrar erros como `reportMissingImports` para `mne`, `numpy`, `PyQt6` etc, selecione o interpretador:

- `python-embed\python.exe`

Obs.: este workspace ja esta configurado em `.vscode/settings.json` para usar esse interpretador por padrao.

## Validacao

1. `python-embed\python.exe` existe.
2. `.deps_python_ok` e `.deps_r_ok` existem.
3. Simulador LSL esta aberto antes do `Grafico.py`.

## Solucao de problemas

### Falha na instalacao R

- Confira se existe essa estrutura:
	- `R-Portable\R-4.5.1\bin\Rscript.exe`

### Falha na instalacao Python

- Rode novamente `Preparar_Ambiente_Portatil.bat`.
- Se necessario, rode so Python: `scripts\instalar_python_local.ps1`.

### Nenhum stream LSL

- Inicie primeiro `Executar_Simulador.bat`.
- Feche outras apps que possam estar consumindo o stream `EMG`.



