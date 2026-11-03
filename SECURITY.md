# Política de segurança

## Versões com suporte

Só a branch `main` recebe correções de segurança.

## Como relatar uma vulnerabilidade

**Não abra issue, PR ou discussão pública com detalhes da falha.**

1. Use o relato privado do GitHub: aba **Security → Report a vulnerability** (<https://github.com/Chan-28/ELEX20/security/advisories/new>).
2. Se não estiver disponível, abra uma issue "Contato de segurança" **sem detalhes técnicos** e peça um canal privado.

Inclua: componente afetado, commit, passos mínimos para reproduzir (com dados fictícios) e o impacto observado. Não envie senhas, tokens ou dados de terceiros; se achou um segredo exposto, diga onde está, sem copiá-lo.

Metas de resposta (projeto mantido por poucas pessoas, não são garantias): confirmação em até 7 dias, avaliação em até 14 dias, correção de falhas críticas e altas em até 30 dias. A divulgação é coordenada, e quem relatou é creditado se quiser.

## Escopo

- **Dentro:** `docker-compose.yaml` e configs dos serviços, firmware, scripts (`scripts/`), workflows em `.github/` e segredos commitados por engano.
- **Fora:** falhas dentro de software de terceiros (TimescaleDB, n8n, Grafana, Hermes etc.; relate ao projeto responsável), DoS volumétrico, engenharia social e scanners sem impacto demonstrado.

## Regras para pesquisa

Teste apenas a sua própria instância. Não acesse nem altere dados de terceiros, não esgote recursos de serviços compartilhados e não divulgue antes da correção. Pesquisa de boa-fé dentro dessas regras não será tratada como violação.

## Práticas do projeto

- **Segredos:** `.env`, tokens e senhas nunca são commitados (use `.env.example`). Credenciais do firmware entram pelo ambiente ou `firmware/.env` (`firmware/load_env.py`). Segredo vazado deve ser revogado, não só apagado do histórico.
- **Rede:** o TimescaleDB não publica porta; n8n, Grafana e painel do Hermes escutam só em `127.0.0.1`. O Mosquitto exige usuário e senha (`device` publica em `sound/*`, `n8n` só lê) e só publica a porta 1883 no IP de `MQTT_BIND` (padrão `127.0.0.1`; para o ESP32, use o IP do host na LAN, nunca `0.0.0.0`). Não há TLS no MQTT nem no banco: use só em LAN confiável ou coloque TLS na frente antes de expor.
- **Privilégios:** o Grafana lê o banco com o papel `grafana_ro` e o n8n usa `n8n_app`; nenhum é superusuário. O socket do Docker não é montado em nenhum container, e o Hermes só aceita usuários listados em `TELEGRAM_ALLOWED_USERS` e `DISCORD_ALLOWED_USERS`. Nunca use `GATEWAY_ALLOW_ALL_USERS` num agente que executa comandos.
- **Dados:** o banco rejeita leituras com `label`, `device_id`, `location` ou `raw_json` fora do formato ou tamanho, e o broker limita as mensagens a 2 KB.
- **Dependências:** Python só por `pyproject.toml` + `uv.lock` (`uv sync --frozen`; `uv add`/`uv remove` para mudar); npm por `package-lock.json`; Dependabot diário. Imagens do compose são fixadas por versão e digest; não volte para `latest`.
- **CI:** actions fixadas por SHA, permissões mínimas, e verificações com CodeQL, Gitleaks, Grype, Trivy config, OWASP ZAP, zizmor, `pip-audit`, `pio check` e o smoke de infraestrutura (`scripts/infra-smoke.sh`, que testa os papéis do banco e a ACL do MQTT). Workflows acionados por comentário só respondem a OWNER, MEMBER e COLLABORATOR.
- **Contribuições:** Conventional Commits, hooks sem `--no-verify`. Mudanças em compose, `mosquitto/` ou `timescaledb/` devem manter o smoke de infraestrutura passando. Textos não confiáveis (issues, e-mails, páginas) que passam por IA são tratados como dado, nunca como instrução.
- **Instalador:** gera todas as senhas com `secrets` (nunca troca as de um `.env` existente), grava o `.env` com permissão 600 e não envia nada pela rede. Os executáveis da release são assinados com cosign (keyless) e trazem `.sha256`; o Windows e o macOS os tratam como "não assinados" (sem certificado pago), então confira a assinatura se tiver dúvida.
- **Senhas de exemplo:** `admin`/`password` nos arquivos de exemplo valem só para desenvolvimento local; troque-as antes de qualquer uso fora da sua máquina.
