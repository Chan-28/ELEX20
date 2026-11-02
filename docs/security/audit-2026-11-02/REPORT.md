# Auditoria de segurança — ELEX20

**Data:** 2026-11-02 (Feliz Dia dos Finados!) · **Commit:** `f5352e97` · **Método:** leitura de todo o código versionado e do histórico do git, mais uma verificação local do Mosquitto em container isolado (sem rede). Passada única, sem revisão independente; o que não está aqui não foi provado seguro. Fora de escopo: workflows do n8n (não versionados), código do Hermes e imagens upstream.

Não há segredos reais no repositório nem no histórico.

## Achados confirmados

| ID   | Sev.  | Problema                                                                                                                                                                                                          | Correção mínima                                                                               |
| ---- | ----- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| F-01 | Média | Mosquitto aceita conexões anônimas (`mosquitto.conf:7`) e a porta 1883 fica em `0.0.0.0`. Verificado: publicação sem credenciais foi aceita. Quem está na LAN pode forjar leituras, ler tudo e derrubar o sensor. | `allow_anonymous false` + ACL, publicar a porta só no IP necessário, credenciais no firmware. |
| F-02 | Média | Grafana, n8n e ingestão usam o superusuário `postgres`. Quem edita consultas no Grafana ou cria nós no n8n executa SQL de superusuário.                                                                           | Papéis dedicados: leitura para o Grafana, dono do banco `n8n`, `INSERT` em `sound_events`.    |
| F-03 | Média | `dependencies.py` instala do PyPI o que suas regexes acham em qualquer `.py`, inclusive em strings e docstrings. `tests/test_dependencies.py:176` já contém `import secretlib`.                                   | Sem instalação automática por padrão e detecção via `ast`.                                    |
| F-04 | Média | Imagens `latest` (`hermes-agent`, `ollama`, `lightpanda`, `alloy`, `pyroscope`) e `busybox` sem tag. O `hermes-agent` monta o socket do Docker.                                                                   | Fixar versão ou digest, começando por `hermes-agent`.                                         |
| F-05 | Média | Senhas `admin`/`password` documentadas como configuração normal.                                                                                                                                                  | Senhas obrigatórias no `.env` (`${VAR:?}`) e README ajustado.                                 |
| F-06 | Baixa | `release.yml`: verificação do cosign errada e sem âncora, artefato simulado assinado, actions sem SHA.                                                                                                            | Corrigir identidade e emissor, fixar actions, publicar só artefato real.                      |
| F-07 | Baixa | `.gitignore` não cobre `hermes_data/` nem `dependency_manager.log`.                                                                                                                                               | Adicionar as entradas.                                                                        |
| F-08 | Baixa | `claude-code.yml` tem `contents: write` e `id-token: write` em todo PR; zizmor aponta gatilhos perigosos (risco aceito, mitigado por `author_association`).                                                       | Reduzir permissões ao necessário.                                                             |
| F-09 | Baixa | n8n sem `N8N_ENCRYPTION_KEY`; o primeiro acesso vira dono.                                                                                                                                                        | Definir a chave no `.env` e fazer backup.                                                     |
| F-10 | Info  | Alloy envia todos os logs de containers ao Loki sem filtro, então segredos impressos ficam visíveis no Grafana.                                                                                                   | Redigir tokens ou limitar os containers.                                                      |
| F-11 | Info  | Firmware sem auth/TLS no MQTT, Wi-Fi no binário da flash e `runInferenceMock()` ativo, que grava dados falsos.                                                                                                    | Marcar o mock no payload ou limitá-lo ao ambiente de debug.                                   |

## Requerem validação

- **N-01 (prioridade alta):** o `hermes-agent` tem o socket do Docker, a ferramenta `docker_terminal` e canais Discord/Telegram/e-mail, sem allowlist nem aprovação visíveis no repo. Se um remetente não autorizado conseguir instruí-lo, isso vira root no host. Falta saber como o Hermes trata remetentes e aprovações. Mitigação: trocar o socket por um proxy restrito, configurar allowlist, desligar o e-mail.
- **N-02:** o workflow do n8n que grava no banco não está no repo, então não sei se valida o payload (o banco só valida `confidence`).
- **N-03:** o datasource do Grafana exige TLS, mas não vi TLS configurado no TimescaleDB; pode falhar ao conectar.

## Ordem sugerida

1. N-01 + F-04 (Hermes e imagens).
2. F-01 (MQTT).
3. F-02 + F-05 (banco e senhas).
4. F-03 (`dependencies.py`).
5. F-06 a F-11 num PR de limpeza.

> **Atenção:** o repositório é público e este relatório descreve falhas ainda abertas.
