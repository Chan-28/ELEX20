# ELEX20 - Análise Neurofisiológica Portátil

Projeto para captura, simulação e visualização de sinais EMG em tempo real no Windows, usando Python, LSL, PyQt6 e R.

## Visão geral

O workspace deverá ser aberto na pasta `ELEX20`.
Estrutura principal:

- `ESP32_EMG/`: firmware do ESP32 e arquivos do PlatformIO
- `bin/`: scripts `.bat` para executar o projeto
- `src/`: aplicativos Python principais
- `tools/`: utilitários de captura, filtro e exportação
- `tests/`: testes de integração LSL
- `output/`: saídas geradas pelos gráficos e relatórios

## Pré-requisitos

Instale e valide estes itens antes de executar o projeto:

- Python 3.10 ou superior, e inferior a Python 3.13
- R 4.5 ou superior
- VS Code com extensões Python e relacionados
- Git, se for clonar ou atualizar o repositório

Para checar a disponibilidade dos linguagens, execute os seguintes comandos no terminal, por exemplo:

```bash
python --version
R --version
```

## Configuração do Python

Na raiz do workspace `ELEX20`, crie e ative um ambiente virtual (para Python 3.12):

```bash
(Windows)

py -3.12 -m venv .venv 
.venv\Scripts\activate 

(Linux)

python3.12 -m venv .venv 
source .venv/bin/activate 

```

Depois instale as dependências do projeto:

```bash
pip install -r requirements.txt
```

Se quiser validar rapidamente os pacotes instalados:

```bash
pip list
```

IMPORTANTE!!!
As bibliotecas `bleak` e `pylsl` requerem dependências extras para o SO de Linux:
```bash
(bleak)
sudo apt install glib-2.0 libbluetooth-dev bluez
(pylsl)
conda install -c conda-forge liblsl
```

Pacotes esperados incluem `PyQt6`, `pyqtgraph`, `mne`, `numpy`, `pylsl`, `matplotlib`, `pandas`, `scipy`, `scikit-learn`, `pillow` e `bleak`.

## Configuração do R

Abra o R ou o RStudio e instale os pacotes usados na coanfecção dos gráficos:

```r
install.packages(c("ggplot2", "tidyr", "dplyr", "scales", "GGally", "gridExtra"))
```

Se aparecer erro de repositório, escolha um mirror CRAN próximo.

Obs.: Para Linux, o comando
```bash
sudo apt install build-essential libcurl4-openssl-dev libssl-dev libxml2-dev
```
é obrigatório para que garantir que ele possua as ferramentas de compilação do R.

## Como executar o projeto Python

Há dois jeitos comuns de rodar a aplicação:

### Via scripts `.bat` (Somente para Windows)

Na pasta `bin/` existe um atalho pronto:

```bash
.\bin\Executar_Projeto.bat
```

O script `Executar_Projeto.bat` roda a cadeia completa do projeto em janelas separadas:

1. `tools/captar_Dados.py` captura os dados do BLE e publica o stream `EMG`.
2. `tools/filtrar_Dados.py` lê `EMG`, processa e publica `EMG_Processado`.
3. `src/Grafico.py` consome `EMG` e `EMG_Processado` e plota os dois sinais em gráficos distintos.


Para validar o fluxo real do ESP32 antes de abrir a interface, o seguintes programas devem ser executados:

```bash
(Windows)
python .\tests\verificar_stream.py
(Linux)
python3 tests/verificar_stream.py
```

Esse teste confirma se os streams LSL `EMG` e `EMG_Processado` aparecem com os nomes esperados.

### Via Python direto

```bash
(Windows)
python .\src\captar_Dados.py
python .\src\filtrar_Dados.py
python .\src\Grafico.py
(Linux)
python3 src/captar_Dados.py
python3 src/filtrar_Dados.py
python3 src/Grafico.py

```

## Checklist de validação

Antes de considerar o projeto pronto, confirme:

1. `python --version` funciona.
2. `R --version` funciona.
3. `pip install -r requirements.txt` termina sem erro.
4. O simulador LSL inicia antes do gráfico principal.
5. O dispositivo BLE aparece com o nome esperado `ESP32_EMG`.

## Solução de problemas

### O Python não encontra pacotes

Reinstale as dependências:

```bash
pip install -r requirements.txt
```

Se estiver usando ambiente virtual, confirme que ele está ativado.

### O R não abre ou não é reconhecido

Verifique o PATH e rode:

```bash
R --version
```

Depois instale novamente os pacotes usados pelo projeto.

### O stream LSL não aparece no gráfico

- Verifique se os nomes dos streams são `EMG` e `EMG_Processado`.
- Feche outras aplicações que possam estar consumindo o mesmo stream.


### O BLE não conecta no ESP32

- Confirme o nome do dispositivo: `ESP32_EMG`.
- Verifique se o ESP32 está ligado e com Bluetooth ativo.
- Tente aproximar o computador da placa.

## Observação sobre o workspace

Para manter os caminhos consistentes, abra o projeto a partir da pasta `ELEX20`.

# Flags de saúde

[![CodeScene Average Code Health](https://codescene.io/projects/83420/status-badges/average-code-health)](https://codescene.io/projects/83420)
[![CodeScene Hotspot Code Health](https://codescene.io/projects/83420/status-badges/hotspot-code-health)](https://codescene.io/projects/83420)
[![CodeScene System Mastery](https://codescene.io/projects/83420/status-badges/system-mastery)](https://codescene.io/projects/83420)
[![CodeScene general](https://codescene.io/images/analyzed-by-codescene-badge.svg)](https://codescene.io/projects/83420)

# Histórico

## Star History

<a href="https://www.star-history.com/?repos=Chan2007%2FELEX20.git&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=Chan2007/ELEX20.git&type=date&theme=dark&legend=top-left&sealed_token=CvYSEE_Lm-1VGT3vpOjwnM3pcNtnthKgm4hBF1Z4jAfO8WVhlBztJhHJdR5TLhGkH4HoNKka-OwnKQq873n-FE0Ruwo8B_cMXUrvwC-LMADyJDu6hdotKJKv9Bw8Vwgyw5bOjB91wIJ4RD5rZQSvFU9OWihr8Ox6ZcRTyKRZFc7cR4gzw_JaekoPL3qH" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=Chan2007/ELEX20.git&type=date&legend=top-left&sealed_token=CvYSEE_Lm-1VGT3vpOjwnM3pcNtnthKgm4hBF1Z4jAfO8WVhlBztJhHJdR5TLhGkH4HoNKka-OwnKQq873n-FE0Ruwo8B_cMXUrvwC-LMADyJDu6hdotKJKv9Bw8Vwgyw5bOjB91wIJ4RD5rZQSvFU9OWihr8Ox6ZcRTyKRZFc7cR4gzw_JaekoPL3qH" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=Chan2007/ELEX20.git&type=date&legend=top-left&sealed_token=CvYSEE_Lm-1VGT3vpOjwnM3pcNtnthKgm4hBF1Z4jAfO8WVhlBztJhHJdR5TLhGkH4HoNKka-OwnKQq873n-FE0Ruwo8B_cMXUrvwC-LMADyJDu6hdotKJKv9Bw8Vwgyw5bOjB91wIJ4RD5rZQSvFU9OWihr8Ox6ZcRTyKRZFc7cR4gzw_JaekoPL3qH" />
 </picture>
</a>


