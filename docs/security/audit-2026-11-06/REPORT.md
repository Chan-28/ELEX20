# Auditoria de segurança — ELEX20 (classificador e PRs de novembro)

**Data:** 2026-11-06 · **Base:** `main` em `67f8b2c6`, com os PRs #43, #48 e #49 mergeados e #50 e #51 abertos · **Relatórios anteriores:** [REPORT.md](../audit-2026-11-02/REPORT.md) e [REPORT-Updated.md](../audit-2026-11-02/REPORT-Updated.md)

**Como verifiquei:** li os diffs dos PRs, busquei no `main` com `git grep`, consultei os alertas do Dependabot e os checks do GitHub, conferi md5 dos arquivos baixados e rodei o `prepare_dataset.py` em modo `--report-only` com os dados reais. Passada de um único revisor, sem revisão independente. Não é uma nova auditoria completa: cobre o trabalho desta rodada e reconfere só o que está indicado. Fora de escopo: código do Hermes, imagens upstream, teste em hardware e teste de intrusão. O Gitleaks não está instalado nesta máquina, então a busca local por segredos usou apenas padrões comuns de tokens; o Gitleaks real roda no CI.

Nenhum segredo real, caminho de usuário real ou email pessoal apareceu no `main` nas buscas feitas. Os caminhos em `.archify/` usam `/home/usuario`.

## Trabalho feito

| Item                               | Estado                     | Efeito na segurança                                                                                                                  |
| ---------------------------------- | -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| #43: dataset ampliado              | Mergeado                   | Sem efeito direto; manteve o agrupamento por base tratado em F-14.                                                                   |
| #48: README reescrito              | Mergeado                   | Documentação.                                                                                                                        |
| #49: nomes e flags em inglês       | Mergeado                   | Executáveis renomeados. CI passou nos 5 executáveis. O README mantém o nome antigo só para a v1.0.0. A release real não foi testada. |
| #50: firmware sem depender da rede | Aberto, sem teste em placa | Trata F-13. Checks passam, inclusive `pio check` e testes nativos.                                                                   |
| #51: separação por autor           | Aberto                     | Trata F-14. 79 testes e ruff passam; 0 grupos em comum nos dados reais.                                                              |
| Experimentos com o modelo          | Fora do repositório        | Registrados em [docs/model-refinement](../../model-refinement/README.md). Nenhum dado novo foi enviado ao Edge Impulse Studio.       |
| FSD50K completo                    | Baixado e extraído         | Ver [Dados baixados](#dados-baixados). Fora do repositório.                                                                          |

## Achados

"Segurança" aqui inclui a segurança física de quem usa o sensor, porque ele alerta sons de perigo.

| ID   | Sev.  | Estado               | Problema                                                                                                                                                                                                                                                              | Correção ou próximo passo                                                                                                    |
| ---- | ----- | -------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| F-12 | Alta  | **Aberto**           | O melhor modelo detecta cerca de 32% dos sons de urgência 3 a 2 falsos alertas/h, contra a meta de 85%, e a latência do YAMNet na placa nunca foi medida. Um usuário que confie no alerta pode perder uma sirene.                                                     | Não publicar modelo padrão abaixo do mínimo definido antes do teste. Avisar que o sensor não é um dispositivo de segurança.  |
| F-13 | Média | **Corrigido no #50** | No `main`, o sensor reinicia se o Wi-Fi falhar e pausa a classificação enquanto tenta alcançar o Mosquitto. Quem derrubar a rede ou o broker pode calar os alertas, inclusive a vibração.                                                                             | Mesclar o #50 e testar na placa cortando Wi-Fi e broker. Detecções sem rede são descartadas e contadas em `offline_dropped`. |
| F-14 | Média | **Corrigido no #51** | As métricas estavam infladas: as três bases vêm do Freesound, mas o grupo era por base. 52 gravações estavam no treino e no teste, e 39% dos clipes de teste tinham autor no treino. A urgência 3 rendia 48,5% com autor visto e 31,9% com autor novo.                | Mesclar o #51 e gerar o dataset novo. O projeto atual no Studio segue com o vazamento até um novo envio aprovado.            |
| F-15 | Média | **Aberto**           | `firmware/lib/elex_core/settings.cpp` e `timescaledb/db-init.sql` ainda têm os rótulos antigos (`siren`, `gun_shot`), e `classes/sound_classes.json` usa os novos. Um modelo de 14 categorias ficaria sem urgência para os rótulos novos, logo sem o alerta esperado. | Atualizar firmware, banco com migração, comandos, n8n, testes e `infra-smoke.sh` junto com a escolha do modelo.              |
| F-16 | Baixa | **Aberto**           | Dependabot #548: `minimatch` com negação de serviço por expansão de padrões, corrigido na 11.0.1. Hoje `npm ls` mostra a 10.2.6, trazida pelo ESLint. Só afeta lint em desenvolvimento, não o produto.                                                                | Atualizar quando o ESLint permitir. Precisa de `npm`, sem edição manual do lockfile.                                         |
| F-17 | Baixa | **Aberto**           | `HANDOFF.md` está versionado no `main`, embora esteja no `.gitignore`, e guarda o registro de uma sessão antiga. A busca não achou dado pessoal, mas esse arquivo tende a acumular contexto que não deveria ser público.                                              | Decidir se ele sai do versionamento. A cópia de trabalho atual não deve ser commitada.                                       |
| F-18 | Info  | **Aceito**           | O md5 do FSD50K detecta corrupção, mas não prova autoria. O `yamnet.tflite` tem sha256 anotado, mas um modelo é um arquivo binário carregado pelo firmware.                                                                                                           | Baixar só da origem oficial e, se houver modelo padrão, publicá-lo com sha256 e assinatura da release.                       |
| F-19 | Info  | **Aberto**           | 3.551 de 9.697 clipes do dataset anterior são CC-BY-NC. O uso do projeto é não comercial, mas quem baixar um modelo publicado precisa saber disso.                                                                                                                    | Declarar uso não comercial e os créditos das bases na release do modelo.                                                     |

## Dados baixados

O FSD50K completo veio do registro 4060432 do Zenodo, por HTTPS.

- Os 8 arquivos (24,67 GB) passaram no md5 publicado. Um erro de conexão durante o download foi recuperado sozinho e não deixou arquivo corrompido.
- Os arquivos foram tratados como dados não confiáveis: pasta nova e vazia, scripts em outra pasta e nenhum executável rodado de dentro dela. Python que lê esses dados usa `-I`, exceto o `prepare_dataset.py`, que roda a partir do repositório e só lê metadados e cabeçalhos.
- A extração gerou 40.966 + 10.231 arquivos, todos `.wav`, sem links simbólicos e sem clipe faltando em relação ao ground truth. Não verifiquei à parte se algum arquivo foi escrito fora da pasta; o `7z` trata caminhos do arquivo.
- Nada disso entrou no repositório.

## Privacidade

No código do `main` e do #50, o payload MQTT de inferência leva rótulo, confiança, tempo, dispositivo e direção. O áudio captado não é publicado. Isso foi lido no código, não medido na rede. Sem TLS, esses metadados trafegam em claro na LAN.

## Reconferência de itens anteriores

| ID         | Estado     | O que vi                                                                                                                                    |
| ---------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| F-05       | **Aberto** | `.env.example` traz `admin` e `password`, o compose usa `POSTGRES_PASSWORD:-password` e o painel do Hermes usa `admin` como usuário padrão. |
| F-09       | **Aberto** | `N8N_ENCRYPTION_KEY` não aparece fora dos relatórios.                                                                                       |
| TLS (MQTT) | **Aberto** | Sem `8883`, `cafile` ou `WiFiClientSecure` no firmware nem no Mosquitto.                                                                    |

Os demais itens do relatório de 2026-11-02 não foram reavaliados.

## Controles adotados

- Sem chave de API do Studio: acesso só pelo navegador, com o login do usuário e aprovação antes de envio de dados ou treino.
- Treinos locais com no máximo 3 processos e limite de memória, depois que 8 processos esgotaram a memória da máquina e o kernel encerrou o aplicativo.
- Dataset, modelos e embeddings ficam fora do Git.

## Ordem sugerida

1. **F-13:** mesclar o #50 e testar na placa.
2. **F-14:** mesclar o #51 e gerar o dataset novo.
3. **F-12 e F-15:** medir a latência, escolher o modelo e atualizar os rótulos juntos.
4. **F-05 e F-09:** senhas padrão e chave do n8n.
5. **F-16 e F-17:** limpeza.

> **Atenção:** o repositório é público e este relatório descreve falhas ainda abertas.
