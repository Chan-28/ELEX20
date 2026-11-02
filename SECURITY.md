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

- **Dentro:** `docker-compose.yaml` e configs dos serviços, firmware, scripts Python, workflows em `.github/` e segredos commitados por engano.
- **Fora:** falhas dentro de software de terceiros (TimescaleDB, n8n, Grafana, Hermes etc.; relate ao projeto responsável), DoS volumétrico, engenharia social e scanners sem impacto demonstrado.

## Regras para pesquisa

Teste apenas a sua própria instância. Não acesse nem altere dados de terceiros, não esgote recursos de serviços compartilhados e não divulgue antes da correção. Pesquisa de boa-fé dentro dessas regras não será tratada como violação.

## Práticas do projeto

- **Segredos:** `.env`, tokens e senhas nunca são commitados (use `.env.example`). Credenciais do firmware entram por `sysenv`. Segredo vazado deve ser revogado, não só apagado do histórico.
- **Rede:** o TimescaleDB não publica porta; n8n, Grafana e painel do Hermes escutam só em `127.0.0.1`. A porta MQTT 1883 fica aberta para o ESP32 na LAN; fora de uma LAN confiável, ative autenticação, ACL e TLS no Mosquitto.
- **Privilégios:** montar o socket do Docker num container equivale a dar root ao host. Use só conscientemente e restrinja quem fala com o agente. Em uso real, prefira papéis de banco por serviço em vez do superusuário.
- **Dependências:** Python só por `pyproject.toml` + `uv.lock` (`uv sync --frozen`); npm por `package-lock.json`; Dependabot diário.
- **CI:** actions fixadas por SHA, permissões mínimas, e verificações com CodeQL, Gitleaks, Grype, Trivy config, OWASP ZAP, zizmor, `pip-audit` e `pio check`. Workflows acionados por comentário só respondem a OWNER, MEMBER e COLLABORATOR.
- **Contribuições:** Conventional Commits, hooks sem `--no-verify`, teste para código Python novo. Textos não confiáveis (issues, e-mails, páginas) que passam por IA são tratados como dado, nunca como instrução.

## Limitações conhecidas

O `docker compose` padrão é para desenvolvimento local: o MQTT aceita conexões anônimas, as senhas de exemplo (`admin`/`password`) são fracas e o Hermes tem acesso ao Docker. Troque as senhas antes de qualquer uso fora da sua máquina. Relatos que só reapontem esses pontos terão baixa prioridade.
