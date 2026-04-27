# ELEX20 - Analise Neurofisiologica Portatil (Windows)

Projeto para analise de sinais EMG em tempo real com LSL, visualizacao no MNE Browser (mne-qt-browser) e graficos estatisticos com R.

## Estrutura da pasta atual

- `python-embed/`: Python local do projeto
- `R-Portable/`: R local do projeto
- `scripts/`: scripts de instalacao
- `Grafico.py`: app principal
- `simulador_lsl_emg.py`: stream LSL EMG de teste
- `Preparar_Ambiente_Portatil.bat`: instala tudo (Python + R)
- `Executar_Simulador.bat`: inicia simulador LSL
- `Executar_Projeto.bat`: inicia Grafico.py com validacoes

## Instalacao de dependencias (Python e R)

### Metodo recomendado (automatico)

1. Abra PowerShell na pasta do projeto.
2. Execute:

```powershell
.\Preparar_Ambiente_Portatil.bat
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

## Como rodar o Grafico.py sem problemas

Ordem correta de execucao:

1. Execute `Preparar_Ambiente_Portatil.bat` (somente no primeiro uso, ou quando mudar dependencia).
2. Em um terminal, execute `Executar_Simulador.bat`.
3. Em outro terminal, execute `Executar_Projeto.bat`.

Fluxo equivalente direto com Python local:

```powershell
.\python-embed\python.exe .\simulador_lsl_emg.py
.\python-embed\python.exe .\Grafico.py
```

## VS Code (corrigir erros de import no editor)

Se o VS Code mostrar erros como `reportMissingImports` para `mne`, `numpy`, `PyQt6` etc, selecione o interpretador:

- `python-embed\python.exe`

Obs.: este workspace ja esta configurado em `.vscode/settings.json` para usar esse interpretador por padrao.

## Checklist rapido de validacao

1. `python-embed\python.exe` existe.
2. `.deps_python_ok` e `.deps_r_ok` existem.
3. Simulador LSL esta aberto antes do `Grafico.py`.
4. A barra de status do app nao mostra "Nenhum stream LSL 'EMG' encontrado" por muito tempo.

## Solucao de problemas

### Falha na instalacao R

- Confira se existe uma destas estruturas:
	- `R-Portable\R-4.5.1\bin\Rscript.exe`
	- `R-Portable\App\R-Portable\bin\x64\Rscript.exe`

### Falha na instalacao Python

- Rode novamente `Preparar_Ambiente_Portatil.bat`.
- Se necessario, rode so Python: `scripts\instalar_python_local.ps1`.

### Nenhum stream LSL

- Inicie primeiro `Executar_Simulador.bat`.
- Feche outras apps que possam estar consumindo o stream `EMG`.



