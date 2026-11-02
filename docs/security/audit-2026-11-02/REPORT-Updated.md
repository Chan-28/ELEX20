# Auditoria de segurança — ELEX20 (atualizado após as correções)

**Data:** 2026-11-02 · **Base:** `main` em `19286d3d` com os PRs #24 e #25 mergeados, mais o PR #31 (aberto, com CI verde) · **Relatório original:** [REPORT.md](REPORT.md)

**Como verifiquei:** reli o código atual e executei os controles, não só o diff. O smoke de infraestrutura (`scripts/infra-smoke.sh`) passou **23/23 aqui e no CI**. O Alloy real redigiu segredos de um log de exemplo. O Hermes v0.22.5 subiu com a configuração nova, sem socket do Docker. Passada de um único revisor, sem revisão independente.

## Estado dos achados

| ID   | Sev. original | Estado                 | O que foi feito e o que sobra                                                                                                                                                                                                                                              |
| ---- | ------------- | ---------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| F-01 | Média         | **Corrigido** (#24)    | Mosquitto exige usuário e ACL (`device` publica, `n8n` só lê); porta 1883 em `MQTT_BIND` (padrão loopback). Sobra: sem TLS, o tráfego e as senhas MQTT seguem em claro na LAN.                                                                                             |
| F-02 | Média         | **Corrigido** (#24)    | Datasource do Grafana e n8n usam `grafana_ro` e `n8n_app`, sem superusuário. Sobra: o backend do Grafana e o `db-init` ainda usam `postgres`, mas um Editor do Grafana não alcança essas conexões.                                                                         |
| F-03 | Média         | **Eliminado** (#31)    | Primeiro, detecção por `ast` e instalação só com `--install` (#24); agora o `dependencies.py` foi removido (#31, aberto).                                                                                                                                                  |
| F-04 | Média         | **Corrigido** (#24)    | Imagens do compose fixadas por versão e digest. Sobra no CI: `trivy-action@master` e o ZAP `:stable`.                                                                                                                                                                      |
| F-05 | Média         | **Aberto**             | `admin`/`password` continuam nos exemplos do Grafana, Hermes e Postgres (as senhas novas do MQTT e dos papéis do banco não têm padrão).                                                                                                                                    |
| F-06 | Baixa         | **Corrigido** (#25)    | Release empacota o código-fonte real, assina com bundle do cosign e traz verificação correta; actions por SHA. Nunca rodou numa tag real.                                                                                                                                  |
| F-07 | Baixa         | **Corrigido** (#27)    | `.gitignore` cobre `hermes_data/` e `dependency_manager.log`.                                                                                                                                                                                                              |
| F-08 | Baixa         | **Parcial** (#25)      | Gatilho `pull_request` morto removido e `timeout-minutes: 30`. Sobra: `issue_comment` com escrita (a ação precisa) e o alerta `dangerous-triggers` do zizmor, aceito e mitigado por `author_association`.                                                                  |
| F-09 | Baixa         | **Aberto**             | Sem `N8N_ENCRYPTION_KEY` fixada.                                                                                                                                                                                                                                           |
| F-10 | Info          | **Corrigido** (#25)    | Alloy redige tokens, senhas e chaves antes do Loki (testado no Alloy real). Limite: valor entre aspas com espaço é redigido só até o primeiro espaço.                                                                                                                      |
| F-11 | Info          | **Parcial** (#24, #25) | Mock só no env `esp32s3_debug` e com `"mock": true`; `i2s_read` com timeout; credenciais MQTT no firmware. Sobra: Wi-Fi no binário da flash (exige acesso físico) e MQTT sem TLS.                                                                                          |
| N-01 | Triagem alta  | **Mitigado** (#24)     | Sem socket do Docker, terminal `local`, `docker_terminal` removido, e-mail desligado e allowlists por variável. Sobra: Discord e Telegram seguem habilitados (a documentação do Hermes diz que ele nega quem não está na allowlist, mas não testei com uma mensagem real). |
| N-02 | —             | **Mitigado** (#24)     | O banco rejeita `label`, `device_id`, `location` e `raw_json` fora do formato ou tamanho, e o broker limita mensagens a 2 KB. Sobra: o workflow do n8n continua fora do repositório, então a validação dele não foi revisada.                                              |
| N-03 | —             | **Resolvido** (#24)    | Confirmado `ssl = off` no TimescaleDB; o datasource passou a `sslmode: disable` (tráfego só na rede interna).                                                                                                                                                              |

## Defeitos antigos que apareceram durante os testes (corrigidos)

- O datasource do Grafana nunca teve banco definido, e `POSTGRES_DB` nem chegava ao container, então ele não conectava (#24).
- O healthcheck do TimescaleDB pode passar durante o initdb. O `db-init` agora espera o servidor definitivo (#24).
- O `docker compose up --wait` do runner falha com serviço que termina de propósito. O smoke trata o `db-init` à parte (#31).

## O que continua em aberto

1. **F-05 e F-09:** senhas de exemplo e chave de criptografia do n8n (não estavam no pedido de correção).
2. **TLS:** MQTT e banco seguem sem TLS. É aceitável em LAN confiável, mas deve ser dito a quem expõe a porta fora dela.
3. **Hermes:** a imagem sobe, mas não verifiquei que ele honra `terminal.backend: local` nem as allowlists. Vale um teste com um remetente não autorizado em instância isolada.
4. **N-02:** exportar o workflow do n8n para o repositório (sem credenciais) para revisão.
5. **Release:** testar com uma tag `v0.0.0-test` e apagá-la.
6. **Mosquitto 2.1:** `per_listener_settings` será removido na 3.0. A imagem está fixada, mas o Dependabot pode propor a atualização; ajuste a configuração antes de aceitar.

## Observação

O CI agora cobre os controles criados: `infra-smoke.yml` (banco e MQTT), ZAP, Grype por imagem, Gitleaks, zizmor e CodeQL. Uma regressão neles reprova o PR.
