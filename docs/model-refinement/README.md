# Refinamento do modelo de sons

Registro de como o classificador de 14 categorias do wearable foi avaliado e melhorado até 2026-11-06. Serve para quem for continuar o trabalho sem repetir tentativas nem confiar em números antigos.

**Estado atual:** nenhum modelo atinge as metas. No teste com limiar congelado, o melhor modelo dá **31% de sensibilidade** a 0,5–0,9 falso alerta/h, medido contra 13,84 h de negativos, com latência na placa ainda não medida.

| Meta                      | Alvo     | Hoje                                            |
| ------------------------- | -------- | ----------------------------------------------- |
| Sensibilidade, urgência 3 | ≥ 85%    | ~31% com limiar congelado; ver curva na etapa 8 |
| Falsos alertas por hora   | ≤ 2      | Ponto de operação escolhido, não uma conquista  |
| Tempo por janela          | < 500 ms | Sem medição; estimativa de 0,5 a 2,5 s na rede  |

Urgência 3 reúne `sirene`, `buzina`, `alarme`, `tiro_explosao` e `grito`.

## Como avaliar

Estas regras vieram de erros cometidos abaixo. Um número fora delas não é comparável.

- **Grupo por autor do Freesound.** FSD50K, UrbanSound8K e ESC-50 vêm do Freesound, então agrupar por base deixa o mesmo autor nos dois lados.
- **Escolha por validação cruzada em grupos** (`GroupKFold` de 5 dobras). O teste já foi usado várias vezes: não ajuste nada olhando para ele.
- **Limiar congelado** antes do teste, por quantil dos negativos e em float64. Em float32, as probabilidades saturam.
- **Regra de alerta:** média causal de 3 janelas, máximo das probabilidades de urgência 3, e rajada conta como 1 falso alerta.
- **Horas de áudio:** soma de `0,975 + (n - 1) * 0,5` s por clipe.
- **Comparação:** bootstrap pareado por grupo, com intervalo de 95%, e pelo menos duas sementes. A semente muda cerca de 5 pontos.
- **Critério fixado antes de testar.** Uma variante só avança se o intervalo pareado ficar acima de zero nas duas sementes.

## Linha do tempo

Os números das etapas 1 a 5 usam o conjunto com vazamento. Servem para comparar etapas entre si, não como desempenho real.

### 1. CNN no Edge Impulse

Janela de 975 ms, passo de 500 ms, MFE com 3.840 features.

| Tentativa                 | Resultado                                                                                            |
| ------------------------- | ---------------------------------------------------------------------------------------------------- |
| 60 ciclos, lote 32        | O Studio abortou: estimativa acima do limite de 60 min por job. Lote 64 resolveu.                    |
| Aumento de dados padrão   | Validação caiu para 22%, com 7 categorias zeradas. Ruído alto é o suspeito; a causa não foi isolada. |
| CNN 32-64-128 sem aumento | Validação 59,6%, mas **teste 46,8%** por clipe.                                                      |

A validação do Studio é aleatória por janela, com janelas do mesmo clipe nos dois lados. Por isso ela não serve para comparar modelos.

### 2. Embeddings do YAMNet

| Modelo                           | Por clipe | Por janela |
| -------------------------------- | --------- | ---------- |
| YAMNet + regressão logística     | 75,1%     | 59,8%      |
| YAMNet + MLP 256                 | 73,8%     | 58,1%      |
| YAMNet direto (classes mapeadas) | 61,9%     | 50,7%      |
| CNN 32-64-128                    | 46,8%     | 36,3%      |

O YAMNet deu o maior salto, mas custa 69,2 M de MACs contra 1,4 M da CNN. O binário de medição compila com 4,67 MB de flash e nunca foi gravado na placa.

### 3. Do acerto por clipe ao alerta

- **Limiar fixo de 0,6:** 240 falsos alertas/h com 83% de sensibilidade. O modelo precisa escolher uma das 14 classes, sem saída para "nada".
- **Confirmação no tempo:** a média de 3 janelas é a melhor regra. Exigir 3 ou mais janelas seguidas não funciona em 162 de 728 clipes de urgência 3, que têm 1 ou 2 janelas.
- **Filtro de rótulos fracos pela força do YAMNet:** descartado. Tira sons reais e não melhora de forma mensurável.

### 4. Classe de rejeição

Foram acrescentados negativos do ESC-50 e do UrbanSound8K: 4,84 h no treino e 0,65 h no teste. No teste com limiar congelado, a sensibilidade foi de **14,7% para 21,3%** (diferença +6,6 pontos, IC95 +4,6 a +8,7). Foi um ganho real, adotado como linha de base.

### 5. Cabeças sobre os embeddings

A cerca de 2 falsos alertas/h na validação cruzada:

| Cabeça                     | Sensibilidade |
| -------------------------- | ------------- |
| Regressão logística        | 26,9%         |
| **MLP 256 + média de 3**   | 35% a 40%     |
| GRU + média de 3           | 35% a 39%     |
| Conv1D causal + média de 3 | 25% a 26%     |
| MIL, atenção               | 35,7% e 41,6% |
| MIL, misto                 | 38,6% e 37,7% |
| MIL, linear softmax        | 34,1% e 33,5% |

A MLP levou o teste de 21,3% para 27,2% a 32,0%. A GRU não superou a MLP, então o ganho veio da não linearidade, não do contexto temporal. Nenhuma variante MIL passou no critério fixado antes. **Trocar a cabeça se esgotou.**

### 6. Queda de `sirene` e vazamento

`sirene` caía de cerca de 60% na validação cruzada para 35% a 38% no teste. A investigação achou duas causas:

- **Gravação difícil:** 28 clipes de fundo vêm de uma única gravação em que o YAMNet quase não ouve sirene. O teste de `sirene` é 88% som de fundo no UrbanSound8K. O áudio não foi ouvido, então isso se apoia nos metadados e nas saídas do modelo.
- **Vazamento:** 52 gravações estavam no treino e no teste, e 39% dos clipes de teste tinham autor no treino. A urgência 3 rendeu 48,5% com autor visto e 31,9% com autor novo.

Refazendo com autores separados, MLP, sementes 7 e 11:

| Medida                     | Resultado     |
| -------------------------- | ------------- |
| Validação cruzada a ~2/h   | 30,7% e 33,1% |
| Teste com limiar congelado | 27,7% e 29,5% |
| Teste a ~2/h               | 32% e 31%     |
| Teste a 5/h                | 46% a 49%     |
| Teste a 15/h               | 61% a 62%     |

Estes números substituíram os das etapas anteriores e foram atualizados na etapa 8. O ranking das cabeças não foi refeito com autores separados.

### 7. Dados completos

O FSD50K local estava incompleto. A seleção com autores separados pedia clipes ausentes, então o conjunto completo foi baixado: 40.966 clipes `dev` e 10.231 `eval`. A correção de `training/prepare_dataset.py` agrupa por autor e sorteia o teste antes do treino ([#51](https://github.com/Chan-28/ELEX20/pull/51)).

Seleção real, sem converter áudio:

| Partição | Clipes | Horas | Autores ou gravações |
| -------- | ------ | ----- | -------------------- |
| Treino   | 7.482  | 14,29 | 1.785                |
| Teste    | 1.633  | 4,04  | 795                  |

Nenhum grupo aparece nos dois lados. `sirene` fica com 556 clipes no treino, `buzina` com 258, `aeronave` com 153 e `impacto` com 171. Nessa seleção, o script ainda descartou 2 clipes mudos ao converter, e o dataset final ficou com 9.113 clipes.

### 8. Negativos do FSD50K e aumento por mistura

Protocolo fixado antes de ver os resultados: validação cruzada por autor, sementes 7 e 11, com todas as variantes medidas nos mesmos clipes, sem aumento. Uma variante só avança se o intervalo pareado ficar acima de zero nas duas sementes.

- **Negativos:** 17.727 clipes no treino e 4.738 no teste, de FSD50K, ESC-50 e UrbanSound8K, com autores separados. Os rótulos `Tools` e `Wind` ficaram de fora, por lembrarem categorias não urgentes.
- **Aumento:** duas cópias de cada clipe de urgência 3 do treino, misturadas com ruído de rua a SNR de 0 a 15 dB. No total, foram 5.794 clipes. O aumento nunca entra na validação nem no teste, e cópias com som ou ruído de um autor da validação saem do treino daquela dobra.

| Variante              | Sensibilidade a ~2/h | Diferença e IC95                      | Decisão    |
| --------------------- | -------------------- | ------------------------------------- | ---------- |
| Base                  | 32,5% e 31,4%        | —                                     | Referência |
| + negativos do FSD50K | 34,9% e 35,1%        | +2,4 [+1,3; +3,6] e +3,8 [+2,8; +4,9] | Aprovada   |
| + negativos + aumento | 33,0% e 34,7%        | -1,8 [-5,4; +1,1] e -0,4 [-2,9; +2,0] | Reprovada  |

O aumento subiu `buzina` e `tiro_explosao`, mas derrubou `sirene` de cerca de 60% para cerca de 46%. Aplicá-lo só às classes favorecidas seria escolher pelo resultado, então ele precisaria de uma hipótese e de um novo protocolo.

Medição única no teste, com limiares congelados (728 clipes de urgência 3, 13,84 h de negativos, 1.878 autores):

| Modelo                 | Sensibilidade (IC95)    | Falsos alertas/h (IC95) | Acerto por clipe |
| ---------------------- | ----------------------- | ----------------------- | ---------------- |
| Base, semente 7        | 29,3% (23,7 a 34,7)     | 1,16 (0,51 a 1,93)      | 76,5%            |
| Base, semente 11       | 28,3% (22,8 a 33,7)     | 0,87 (0,36 a 1,47)      | 76,5%            |
| **FSD50K, semente 7**  | **31,0%** (25,3 a 37,0) | **0,51** (0,14 a 1,03)  | 77,0%            |
| **FSD50K, semente 11** | **31,5%** (25,6 a 37,2) | **0,87** (0,31 a 1,58)  | 77,1%            |

A diferença para a base foi +1,8 ponto (IC95 -0,4 a +4,2) na semente 7 e +3,1 (IC95 +1,1 a +5,7) na semente 11. O ganho se repetiu, mas ficou estatisticamente claro só em uma semente.

Ajustando o limiar no próprio teste, o que é otimista, a variante aprovada dá 39% a 40% a 2/h, 48% a 50% a 5/h e 59% a 61% a 15/h. Esses valores não são comparáveis com os da etapa 6, porque o teste tem bem mais horas de negativos. Por classe, com limiar congelado: `buzina` 49%, `tiro_explosao` 34%, `sirene` 34%, `alarme` 25% a 26% e `grito` 22% a 24%.

A variante com negativos do FSD50K é a nova linha de base.

## Resumo

- O vazamento foi o erro mais caro: até a etapa 5, as comparações pareciam melhores do que eram.
- Os ganhos reais vieram do YAMNet, da classe de rejeição e da MLP. A cabeça temporal e a MIL não ajudaram.
- Negativos variados ajudaram pouco, mas de forma repetida. O aumento por mistura, como foi feito, não ajudou.
- Mais do mesmo tipo de dado não fecha a distância até a meta: faltam gravações reais de rua e, provavelmente, rever a meta ou o tipo de alerta.
- O conjunto negativo não representa uma rua real, então os falsos alertas em campo são desconhecidos.

## Próximos passos

1. Medir a latência do YAMNet na placa. Até cerca de 500 ms, integrar; de 0,5 a 2 s, usar passo maior; acima de 2 s, usar rede menor ou processar fora da placa.
2. Coletar gravações de rua reais, com o microfone do sensor. Elas medem os falsos alertas de verdade e são o dado que mais falta.
3. Refazer o ranking das cabeças com autores separados, selecionando por validação cruzada.
4. Só depois, com uma hipótese nova, testar outro aumento. O teste já foi usado de novo: não ajuste nada olhando para ele.
5. Com o modelo decidido, atualizar juntos firmware, banco, comandos, n8n, testes e smoke. Hoje eles ainda usam os rótulos antigos.

## Licenças

Parte dos dados é CC-BY-NC.
