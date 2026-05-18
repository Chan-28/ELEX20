# ELEX20 - Análise Neurofisiológica Portátil (Windows)

Projeto para análise de sinais EMG em tempo real com LSL, visualização no MNE Browser (mne-qt-browser) e gráficos estatísticos com R.

## Pré-requisitos

- **Python 3.10+** instalado globalmente no sistema
- **R 4.5+** instalado globalmente no sistema
- Ambos devem estar acessíveis via terminal (PATH configurado)

## Estrutura da pasta

- `bin/`: scripts lançadores (`Executar_Projeto.bat`, `Executar_Simulador.bat`)
- `src/`: código principal do aplicativo (`Grafico.py`, `simulador_lsl_emg.py`)
- `tools/`: utilitários e helpers (`captar_Dados.py`, `filtrar_Dados.py`, `enviar_CSV_Dados.py`)
- `tests/`: testes e integração (`teste_lsl_integracao.py`)
- `output/`: diretório onde os gráficos e arquivos gerados são salvos
- `requirements.txt`: dependências Python do projeto


## Instalação de dependências Python

No terminal, na raiz do projeto:

```bash
pip install -r requirements.txt
```

Se estiver usando um ambiente virtual (recomendado):

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## Instalação de dependências R

Abra R e execute:

```r
install.packages(c("ggplot2", "tidyr", "dplyr", "scales", "GGally"))
```

## Como rodar o Grafico.py

Ordem correta de execução:

1. Em um terminal, execute `bin\Executar_Simulador.bat`:
```bash
.\bin\Executar_Simulador.bat
```

2. Em outro terminal, execute `bin\Executar_Projeto.bat`:
```bash
.\bin\Executar_Projeto.bat
```

Ou execute diretamente com Python:

```bash
python .\src\simulador_lsl_emg.py
python .\src\Grafico.py
```

## VS Code

Se estiver usando VS Code, configure o interpretador Python no workspace:
- Pressione `Ctrl+Shift+P` → "Python: Select Interpreter"
- Escolha o Python global ou do venv

## Checklist rápido de validação

1. `python --version` e `R --version` funcionam no terminal
2. `pip list` mostra pacotes instalados (PyQt6, pyqtgraph, mne, numpy, pylsl, rpy2)
3. Simulador LSL está aberto antes do `Grafico.py`
4. A barra de status do app não mostra "Nenhum stream LSL 'EMG' encontrado" por muito tempo

## Solução de problemas

### Dependências Python ausentes

```bash
pip install -r requirements.txt
```

### R não encontrado

- Verifique: `R --version` no terminal
- Instale pacotes R necessários:
```r
install.packages(c("ggplot2", "tidyr", "dplyr", "scales", "GGally"))
```

### Nenhum stream LSL

- Inicie primeiro `Executar_Simulador.bat`
- Feche outras apps que possam estar consumindo o stream `EMG`



