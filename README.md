# ELEX20 - Analise Neurofisiologica Portatil (Windows)

Projeto para analise de sinais EMG em tempo real com LSL, visualizacao no MNE Browser e graficos estatisticos com R (ggplot2).

## Objetivo de Portabilidade

Este repositorio foi preparado para rodar em Windows usando recursos locais dentro da pasta do projeto:

- Python embutido em `python-embed/`
- R portatil em `R-Portable/`
- Scripts de preparo de ambiente em `scripts/`
- Atalhos `.bat` para facilitar execucao

## Estrutura Principal

- `Grafico.py`: aplicacao principal
- `simulador_lsl_emg.py`: simulador de stream LSL
- `Preparar_Ambiente_Portatil.bat`: instala dependencias Python e R localmente
- `Executar_Simulador.bat`: inicia o simulador
- `Executar_Projeto.bat`: inicia a aplicacao
- `Atualizar_Wheels_Offline.bat`: baixa pacotes Python para instalacao offline

## Primeiro Uso (Windows)

1. Execute `Preparar_Ambiente_Portatil.bat`
2. Abra `Executar_Simulador.bat`
3. Abra `Executar_Projeto.bat`

## Fluxo Offline (para distribuir em outro PC)

No computador que tem internet:

1. Execute `Atualizar_Wheels_Offline.bat`
2. Execute `Preparar_Ambiente_Portatil.bat`
3. Compacte toda a pasta `ELEX20` em `.zip`

No computador destino (sem internet):

1. Extraia a pasta `ELEX20`
2. Execute `Preparar_Ambiente_Portatil.bat`
3. Rode `Executar_Simulador.bat` e `Executar_Projeto.bat`

## O Que Ja Foi Automatizado

- Instalacao de dependencias Python no `python-embed`
- Instalacao de pacotes R em biblioteca local `R-Portable/library`
- Configuracao automatica de `R_HOME`, `PATH` e `R_LIBS_USER` no codigo
- Validacao de dependencias nos atalhos de execucao

## O Que Ainda Exige Acao do Usuario

1. Internet ao menos uma vez para baixar dependencias (Python e R), caso a pasta ainda nao tenha sido preparada.
2. Permitir execucao de script PowerShell quando o Windows bloquear (ExecutionPolicy).
3. Garantir que antivirus/firewall nao bloqueiem processos locais do Python/LSL.
4. Algumas combinacoes de versao (ex.: Python muito novo) podem nao ter wheel para todas as bibliotecas. Nesse caso, o instalador tenta modo sem `rpy2` e a analise R pode ficar indisponivel.

### Recomendacao de compatibilidade

- Se o objetivo for 100% de recursos R em qualquer PC, prefira distribuir a pasta ja preparada apos executar `Preparar_Ambiente_Portatil.bat` na maquina de origem.
- Se ainda houver incompatibilidade de wheel, use uma distribuicao Python embutida 3.11 ou 3.12 para maior compatibilidade com ecossistema cientifico/R.

## Solucao de Problemas

### Aplicacao abre com linha reta nos sinais

- Verifique se o simulador esta rodando antes da aplicacao.
- Confirme se o stream `EMG` foi encontrado na barra de status da janela.
- Se necessario, reinicie ambos os `.bat`.

### Erro de dependencia Python

- Execute novamente `Preparar_Ambiente_Portatil.bat`.

### Erro de pacote R (ggplot2/GGally etc.)

- Execute `scripts\instalar_r_local.bat`.

### "Nenhum stream LSL encontrado"

- Inicie primeiro `Executar_Simulador.bat`.
- Verifique se outra aplicacao nao ocupou o stream com mesmo nome.

## Observacoes Tecnicas

- O MNE Browser usa no maximo 4 canais por requisito de usabilidade.
- Os graficos de tempo real usam janela deslizante com suavizacao temporal leve.
- A analise estatistica prioriza R + ggplot2 e utiliza fallback Python quando necessario.


