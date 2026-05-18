# ELEX20 - Análise Neurofisiológica Portátil

Projeto para captura, simulação e visualização de sinais EMG em tempo real no Windows, usando Python, LSL, PyQt6 e R.

## Visão geral

O workspace deve ser aberto na pasta `ELEX20`. Dentro dela está o projeto `ESP32_EMG`, que contém o firmware do ESP32 e as configurações do PlatformIO.

Estrutura principal:

- `ESP32_EMG/`: firmware do ESP32 e arquivos do PlatformIO
- `bin/`: scripts `.bat` para executar o projeto
- `src/`: aplicativos Python principais
- `tools/`: utilitários de captura, filtro e exportação
- `tests/`: testes de integração LSL
- `output/`: saídas geradas pelos gráficos e relatórios

## Pré-requisitos

Instale e valide estes itens antes de executar o projeto:

- Python 3.10 ou superior
- R 4.5 ou superior
- VS Code com extensões Python e PlatformIO IDE
- Git, se for clonar ou atualizar o repositório
- Para o firmware: placa ESP32, cabo USB e driver serial funcionando

Confira se os comandos abaixo respondem no terminal:

```bash
python --version
R --version
```

## Configuração do Python

Na raiz do workspace `ELEX20`, crie e ative um ambiente virtual:

```bash
python -m venv .venv
.venv\Scripts\activate
```

Depois instale as dependências do projeto:

```bash
pip install -r requirements.txt
```

Se quiser validar rapidamente os pacotes instalados:

```bash
pip list
```

Pacotes esperados incluem `PyQt6`, `pyqtgraph`, `mne`, `numpy`, `pylsl`, `matplotlib`, `pandas`, `scipy` e `scikit-learn`.

## Configuração do R

Abra o R ou o RStudio e instale os pacotes usados nos scripts de análise:

```r
install.packages(c("ggplot2", "tidyr", "dplyr", "scales", "GGally"))
```

Se aparecer erro de repositório, escolha um mirror CRAN próximo.

## Configuração do PlatformIO

1. Abra o workspace pela pasta `ELEX20`, não apenas por `ESP32_EMG`.
2. No VS Code, confirme que a extensão PlatformIO IDE está instalada.
3. Abra a pasta `ESP32_EMG` quando for trabalhar com o firmware do ESP32.
4. Execute um build inicial do projeto para baixar as bibliotecas em `.pio/libdeps/`.

No firmware, as dependências principais são:

- `NimBLE-Arduino`
- `Adafruit ADS1X15`

Se o IntelliSense não reconhecer os includes do Arduino, execute um build do PlatformIO e depois recarregue a janela do VS Code.

## Como executar o projeto Python

Há dois jeitos comuns de rodar a aplicação:

### Via scripts `.bat`

Na pasta `bin/` existem atalhos prontos:

```bash
.\bin\Executar_Simulador.bat
.\bin\Executar_Projeto.bat
.\bin\Executar_Teste.bat
```

Ordem recomendada para uso normal:

1. Inicie o simulador LSL.
2. Em outro terminal, inicie o gráfico principal.

### Via Python direto

```bash
python .\src\simulador_lsl_emg.py
python .\src\Grafico.py
```

## Como executar o firmware do ESP32

1. Abra a pasta `ESP32_EMG` no VS Code com PlatformIO.
2. Conecte o ESP32 ao computador via USB.
3. Execute o build do PlatformIO.
4. Faça upload do firmware para a placa.
5. Abra o monitor serial se quiser acompanhar o log de calibração e conexão BLE.

O firmware transmite notificações BLE no formato:

```text
[timestamp de 4 bytes] + [voltage float de 4 bytes]
```

No Python, o receptor BLE espera o dispositivo com nome `ESP32-EMG` e a característica `bef8d6c9-9c21-4c9e-b632-bd763f7a92bf`.

## Checklist de validação

Antes de considerar o projeto pronto, confirme:

1. `python --version` funciona.
2. `R --version` funciona.
3. `pip install -r requirements.txt` termina sem erro.
4. O build do PlatformIO no `ESP32_EMG` termina com sucesso.
5. O simulador LSL inicia antes do gráfico principal.
6. O dispositivo BLE aparece com o nome esperado `ESP32-EMG`.

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

- Abra primeiro o simulador LSL.
- Verifique se o nome do stream é `EMG`.
- Feche outras aplicações que possam estar consumindo o mesmo stream.

### O IntelliSense do ESP32 mostra erro de include

- Confirme que a pasta do workspace é `ELEX20`.
- Reabra o arquivo dentro de `ESP32_EMG`.
- Rode um build do PlatformIO para baixar as bibliotecas.
- Recarregue a janela do VS Code se necessário.

### O BLE não conecta no ESP32

- Confirme o nome do dispositivo: `ESP32-EMG`.
- Verifique se o ESP32 está ligado e com Bluetooth ativo.
- Tente aproximar o computador da placa.
- Se necessário, aumente o timeout de scan no script Python.

## Observação sobre o workspace

Para manter os caminhos consistentes, abra o projeto a partir da pasta `ELEX20`. Assim os paths relativos em `.vscode/c_cpp_properties.json` e nos scripts Python funcionam sem depender de diretórios absolutos do seu usuário.



