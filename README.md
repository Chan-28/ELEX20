<!-- markdownlint-disable MD033 MD041 -->
<div align="center">

# ELEX20

**Wearable que reconhece sons da rua e indica por vibração de onde eles vêm.**

[![Release](https://img.shields.io/github/v/release/Chan-28/ELEX20)](https://github.com/Chan-28/ELEX20/releases)
[![Licença](https://img.shields.io/github/license/Chan-28/ELEX20)](LICENSE)

</div>
<!-- markdownlint-enable MD033 -->

## Como funciona

O ELEX20 ouve o ambiente com quatro microfones e reconhece sons como sirenes, buzinas e gritos. Quando o som é importante, o motor do lado de onde ele veio vibra, com mais força nos sons mais urgentes.

Tudo isso acontece no próprio aparelho, sem internet. Se quiser, você também pode ligar um servidor no seu computador para ver o histórico em painéis e receber alertas no Telegram ou no Discord.

## O que você precisa

- **Para o servidor:** Windows, macOS ou Linux com [Docker](https://www.docker.com/products/docker-desktop/), [Git](https://git-scm.com/downloads) e [Python 3](https://www.python.org/downloads/).
- **Para o aparelho:** placa ESP32-S3 (N16R8), 4 microfones INMP441, 4 motores de vibração, Wi-Fi de 2,4 GHz e o [PlatformIO](https://platformio.org/install/cli). Veja [como ligar os componentes](docs/reference.md#ligações).

## Instalação

Com o Docker aberto, rode:

```bash
git clone https://github.com/Chan-28/ELEX20.git
cd ELEX20
./install.sh
```

No Windows, use `install.bat` no lugar de `./install.sh`.

Abre um assistente em inglês no terminal. Escolha a pasta, ligue só o que for usar e confira tudo na última tela: nada é instalado antes disso. Se você vai usar o aparelho, preencha o nome e a senha do Wi-Fi na tela **Set up the device**.

> [!WARNING]
> Guarde o arquivo `.env` criado na pasta e não o compartilhe, porque ele contém as suas senhas.

## Gravar o aparelho

O modelo que reconhece os sons não vem neste repositório. Exporte o seu pelo [Edge Impulse](https://edgeimpulse.com/) como **Arduino library** e extraia em `firmware/lib/ei-model/`. Os nomes dos sons precisam seguir [esta lista](docs/reference.md#rótulos-e-urgência).

Depois, conecte a placa pela USB e rode:

```bash
cd firmware
pio run -e esp32s3_model -t upload && pio device monitor
```

## Como usar

Com o aparelho gravado e ligado, basta usar: ele vibra sozinho quando reconhece um som importante.

Com o servidor ligado, abra no navegador:

| O que                               | Endereço                | Login inicial        |
| ----------------------------------- | ----------------------- | -------------------- |
| **Grafana:** histórico e painéis    | <http://localhost:3000> | `admin` / `password` |
| **Hermes:** assistente              | <http://localhost:9119> | `admin` / `password` |
| **n8n:** automações (já vem pronto) | <http://localhost:5678> | crie no 1º acesso    |

> [!CAUTION]
> Troque os logins iniciais antes de usar fora da sua máquina.

Para parar e voltar a ligar o servidor:

```bash
docker compose stop
docker compose start
```

Para remover o ELEX20, rode `./install.sh --uninstall`. Seus dados só são apagados se você pedir. Veja [Desinstalar](docs/reference.md#desinstalar).

## Problemas comuns

- **O instalador diz que o Docker não está rodando:** abra o Docker e espere ele iniciar.
- **O aparelho não conecta:** confira se o Wi-Fi é de 2,4 GHz e se o computador está na mesma rede.
- **O log mostra `Sem modelo`:** falta extrair o modelo em `firmware/lib/ei-model/`.
- **O bot do Telegram não responde:** o servidor precisa estar ligado.

Para outros casos, veja [Solução de problemas](docs/reference.md#solução-de-problemas).

## Saiba mais

O [guia completo](docs/reference.md) traz a instalação sem o instalador, a configuração, o desenvolvimento e todos os detalhes do projeto.

## Licença

Distribuído sob a licença [MIT](LICENSE).
