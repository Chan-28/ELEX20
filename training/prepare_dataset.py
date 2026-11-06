"""Monta o dataset local das categorias de som a partir de FSD50K, UrbanSound8K e ESC-50.

A lista vem de classes/sound_classes.json. A saída tem WAVs de 16 kHz mono em train/ e
test/, com o rótulo antes do primeiro ponto do nome, como o Edge Impulse espera, mais
manifest.csv (origem e licença de cada clipe) e report.json (contagens).
As três bases vêm do Freesound, então o grupo é o autor, comum a elas. O diretório do
UrbanSound8K precisa ter o FREESOUNDCREDITS.txt, que dá o autor de cada gravação.
Nada aqui envia dados a um serviço externo.

Uso:
  uv run python training/prepare_dataset.py --fsd50k <dir> --urbansound8k <dir> \
      --esc50 <dir> --output <dir> [--no-nc] [--report-only]
"""

import argparse
import array
import csv
import json
import random
import re
import subprocess
import wave
import zlib
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
TAXA = 16000
MAX_CLIPE_S = 30.0  # um clipe longo não pode dominar a categoria
LIMITE_TREINO_S = 80 * 60.0  # teto por categoria: as raras ficam com o que existe
LIMITE_TESTE_S = 20 * 60.0
SEMENTE = 20  # sorteio reproduzível
PASTA_TESTE_US8K = 10
PASTA_TESTE_ESC50 = 5
PERCENTUAL_TESTE_GRUPOS = 20
PICO_MINIMO = 33  # cerca de -60 dBFS em 16 bits: abaixo disso o clipe é considerado mudo
LICENCA_US8K = "CC-BY-NC"
LICENCA_ESC50 = "CC-BY-NC"


@dataclass(frozen=True)
class Clipe:
    rotulo: str
    fonte: str
    identificador: str
    caminho: Path
    particao: str  # train ou test
    licenca: str
    grupo: str  # autor no Freesound, ou a gravação se ele for desconhecido: nunca em treino e teste


def carregar_categorias(caminho: Path = RAIZ / "classes" / "sound_classes.json") -> list[dict]:
    categorias = json.loads(caminho.read_text(encoding="utf-8"))["categorias"]
    return [c for c in categorias if c.get("ativa", True)]


def categoria_fsd(rotulos_clipe: set[str], categorias: list[dict]) -> str | None:
    """Categoria de um clipe do FSD50K, ou None se for ambíguo ou de fora da lista.

    Os rótulos do FSD50K incluem os ancestrais na ontologia (Siren traz Alarm; Vehicle
    horn traz Car e Vehicle). Por isso os específicos decidem, e os genéricos só valem
    sozinhos. Dois específicos de categorias diferentes indicam sons misturados.
    """
    especificas, genericas = [], []
    for categoria in categorias:
        fontes = categoria["fontes"]
        comuns = rotulos_clipe & set(fontes["fsd50k"])
        if comuns - set(fontes["fsd50k_genericos"]):
            especificas.append(categoria["rotulo"])
        elif comuns:
            genericas.append(categoria["rotulo"])
    if len(especificas) == 1:
        return especificas[0]
    if not especificas and len(genericas) == 1:
        return genericas[0]
    return None


def particao_por_grupo(grupo: str) -> str:
    """Sorteio estável por grupo, para a mesma gravação cair sempre na mesma partição."""
    return "test" if zlib.crc32(grupo.encode()) % 100 < PERCENTUAL_TESTE_GRUPOS else "train"


def normalizar_licenca(url: str) -> str:
    u = url.lower()
    if "publicdomain/zero" in u:
        return "CC0"
    if "sampling+" in u or "sampling" in u:
        return "CC-Sampling+"
    if "by-nc" in u:
        return "CC-BY-NC"
    if "/by/" in u:
        return "CC-BY"
    return "desconhecida"


def ler_autores(fsd50k: Path, urbansound8k: Path) -> dict[str, str]:
    """Autor de cada som do Freesound, pelos metadados do FSD50K e pelos créditos do UrbanSound8K."""
    autores = {}
    creditos = (urbansound8k / "FREESOUNDCREDITS.txt").read_text(encoding="utf-8", errors="replace")
    for linha in creditos.splitlines():
        if casamento := re.fullmatch(r"(\d+) by (.+?)\s*", linha):
            autores[casamento[1]] = casamento[2].lower()
    for parte in ("dev", "eval"):
        info = json.loads((fsd50k / "FSD50K.metadata" / f"{parte}_clips_info_FSD50K.json").read_text(encoding="utf-8"))
        autores |= {som: dados["uploader"].lower() for som, dados in info.items() if dados.get("uploader")}
    return autores


def grupo_freesound(som: str, autores: dict[str, str]) -> str:
    """Grupo comum às três bases: uma gravação sem autor conhecido ainda se une pelo próprio som."""
    autor = autores.get(som)
    return f"autor:{autor}" if autor else f"gravacao:{som}"


def clipes_fsd50k(raiz: Path, categorias: list[dict], autores: dict[str, str]) -> list[Clipe]:
    info = {
        "dev": json.loads((raiz / "FSD50K.metadata" / "dev_clips_info_FSD50K.json").read_text(encoding="utf-8")),
        "eval": json.loads((raiz / "FSD50K.metadata" / "eval_clips_info_FSD50K.json").read_text(encoding="utf-8")),
    }
    clipes = []
    for parte, particao in (("dev", "train"), ("eval", "test")):
        with (raiz / "FSD50K.ground_truth" / f"{parte}.csv").open(encoding="utf-8", newline="") as arquivo:
            for linha in csv.DictReader(arquivo):
                rotulo = categoria_fsd(set(linha["labels"].split(",")), categorias)
                if rotulo is None:
                    continue
                dados = info[parte].get(linha["fname"], {})
                clipes.append(
                    Clipe(
                        rotulo,
                        "fsd50k",
                        linha["fname"],
                        raiz / f"FSD50K.{parte}_audio" / f"{linha['fname']}.wav",
                        particao,
                        normalizar_licenca(dados.get("license", "")),
                        grupo_freesound(linha["fname"], autores),
                    )
                )
    return clipes


def clipes_urbansound8k(raiz: Path, categorias: list[dict], autores: dict[str, str]) -> list[Clipe]:
    mapa = {nome: c["rotulo"] for c in categorias for nome in c["fontes"]["urbansound8k"]}
    clipes = []
    with (raiz / "metadata" / "UrbanSound8K.csv").open(encoding="utf-8", newline="") as arquivo:
        for linha in csv.DictReader(arquivo):
            rotulo = mapa.get(linha["class"])
            if rotulo is None:
                continue
            pasta = int(linha["fold"])
            clipes.append(
                Clipe(
                    rotulo,
                    "urbansound8k",
                    Path(linha["slice_file_name"]).stem,
                    raiz / "audio" / f"fold{pasta}" / linha["slice_file_name"],
                    "test" if pasta == PASTA_TESTE_US8K else "train",
                    LICENCA_US8K,
                    grupo_freesound(linha["fsID"], autores),
                )
            )
    return clipes


def clipes_esc50(raiz: Path, categorias: list[dict], autores: dict[str, str]) -> list[Clipe]:
    mapa = {nome: c["rotulo"] for c in categorias for nome in c["fontes"]["esc50"]}
    clipes = []
    with (raiz / "meta" / "esc50.csv").open(encoding="utf-8", newline="") as arquivo:
        for linha in csv.DictReader(arquivo):
            rotulo = mapa.get(linha["category"])
            if rotulo is None:
                continue
            clipes.append(
                Clipe(
                    rotulo,
                    "esc50",
                    Path(linha["filename"]).stem,
                    raiz / "audio" / linha["filename"],
                    "test" if int(linha["fold"]) == PASTA_TESTE_ESC50 else "train",
                    LICENCA_ESC50,
                    grupo_freesound(linha["src_file"], autores),
                )
            )
    return clipes


def separar_grupos_do_teste(clipes: list[Clipe]) -> list[Clipe]:
    """Descarta do treino qualquer clipe cujo grupo esteja no teste."""
    no_teste = {c.grupo for c in clipes if c.particao == "test"}
    return [c for c in clipes if c.particao == "test" or c.grupo not in no_teste]


def duracao_s(caminho: Path) -> float:
    try:
        with wave.open(str(caminho), "rb") as arquivo:
            return arquivo.getnframes() / arquivo.getframerate()
    except wave.Error:  # WAV de ponto flutuante ou extensível: o módulo wave não lê
        saida = subprocess.run(  # noqa: S603  (argumentos em lista, sem shell)
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(caminho)],  # noqa: S607
            check=True,
            capture_output=True,
            text=True,
        )
        return float(saida.stdout.strip())


def selecionar(clipes: list[Clipe], limite_s: float, duracao=duracao_s) -> list[tuple[Clipe, float]]:
    """Sorteia clipes até o limite, alternando as fontes para os complementos não sumirem."""
    filas: dict[str, list[Clipe]] = {}
    for clipe in sorted(clipes, key=lambda c: (c.fonte, c.identificador)):
        filas.setdefault(clipe.fonte, []).append(clipe)
    # Um sorteio por fonte: a ordem de uma fonte não muda quando outra entra ou sai
    for fonte, fila in filas.items():
        random.Random(f"{SEMENTE}:{fonte}").shuffle(fila)  # noqa: S311  (amostragem, não é criptografia)
    escolhidos, total = [], 0.0
    while total < limite_s and any(filas.values()):
        for fila in filas.values():
            if fila and total < limite_s:
                clipe = fila.pop()
                segundos = min(duracao(clipe.caminho), MAX_CLIPE_S)
                escolhidos.append((clipe, segundos))
                total += segundos
    return escolhidos


def selecionar_particoes(clipes: list[Clipe], categorias: list[dict], duracao=duracao_s) -> list[tuple[Clipe, float]]:
    """Sorteia o teste e depois o treino, que só perde os grupos que de fato caíram no teste."""
    por_categoria = [[c for c in clipes if c.rotulo == cat["rotulo"]] for cat in categorias]
    teste: list[tuple[Clipe, float]] = []
    for clipes_categoria in por_categoria:
        candidatos = [c for c in clipes_categoria if c.particao == "test"]
        teste += selecionar(candidatos, LIMITE_TESTE_S, duracao)
    no_teste = [c for c, _ in teste]
    livres = separar_grupos_do_teste(no_teste + [c for c in clipes if c.particao == "train"])
    treino: list[tuple[Clipe, float]] = []
    for categoria in categorias:
        candidatos = [c for c in livres if c.particao == "train" and c.rotulo == categoria["rotulo"]]
        treino += selecionar(candidatos, LIMITE_TREINO_S, duracao)
    return treino + teste


def converter(origem: Path, destino: Path) -> None:
    subprocess.run(  # noqa: S603  (argumentos em lista, sem shell)
        [  # noqa: S607
            "ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(origem),
            "-t", str(MAX_CLIPE_S), "-ac", "1", "-ar", str(TAXA), "-c:a", "pcm_s16le", str(destino),
        ],
        check=True,
    )  # fmt: skip


def clipe_mudo(caminho: Path) -> bool:
    """Lê o WAV de 16 bits convertido e diz se o pico fica abaixo de PICO_MINIMO."""
    with wave.open(str(caminho), "rb") as arquivo:
        amostras = array.array("h", arquivo.readframes(arquivo.getnframes()))
    return max((abs(a) for a in amostras), default=0) < PICO_MINIMO


def relatorio(selecionados: list[tuple[Clipe, float]], categorias: list[dict]) -> dict:
    saida = {}
    for categoria in categorias:
        itens = [(c, s) for c, s in selecionados if c.rotulo == categoria["rotulo"]]
        por_fonte: dict[str, int] = {}
        por_licenca: dict[str, int] = {}
        for clipe, _ in itens:
            por_fonte[clipe.fonte] = por_fonte.get(clipe.fonte, 0) + 1
            por_licenca[clipe.licenca] = por_licenca.get(clipe.licenca, 0) + 1
        saida[categoria["rotulo"]] = {
            "urgencia": categoria["urgencia"],
            "clipes_treino": sum(c.particao == "train" for c, _ in itens),
            "clipes_teste": sum(c.particao == "test" for c, _ in itens),
            "minutos_treino": round(sum(s for c, s in itens if c.particao == "train") / 60, 1),
            "minutos_teste": round(sum(s for c, s in itens if c.particao == "test") / 60, 1),
            "por_fonte": por_fonte,
            "por_licenca": por_licenca,
        }
    return saida


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fsd50k", type=Path, required=True)
    parser.add_argument("--urbansound8k", type=Path, required=True)
    parser.add_argument("--esc50", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--no-nc", action="store_true", help="usa só licenças que permitem uso comercial")
    parser.add_argument("--report-only", action="store_true", help="não converte os áudios")
    args = parser.parse_args()

    categorias = carregar_categorias()
    autores = ler_autores(args.fsd50k, args.urbansound8k)
    clipes = (
        clipes_fsd50k(args.fsd50k, categorias, autores)
        + clipes_urbansound8k(args.urbansound8k, categorias, autores)
        + clipes_esc50(args.esc50, categorias, autores)
    )
    clipes = [c for c in clipes if c.licenca != "desconhecida"]
    if args.no_nc:
        clipes = [c for c in clipes if c.licenca in ("CC0", "CC-BY")]

    selecionados = selecionar_particoes(clipes, categorias)

    args.output.mkdir(parents=True, exist_ok=True)
    mantidos: list[tuple[Clipe, float]] = []
    with (args.output / "manifest.csv").open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.writer(arquivo)
        escritor.writerow(["arquivo", "rotulo", "particao", "fonte", "id", "licenca", "grupo", "segundos"])
        for clipe, segundos in selecionados:
            nome = f"{clipe.rotulo}.{clipe.fonte}_{clipe.identificador}.wav"
            if not args.report_only:
                pasta = args.output / clipe.particao
                pasta.mkdir(exist_ok=True)
                converter(clipe.caminho, pasta / nome)
                if clipe_mudo(pasta / nome):
                    (pasta / nome).unlink()
                    print(f"descartado (mudo): {nome}")
                    continue
            escritor.writerow(
                [nome, clipe.rotulo, clipe.particao, clipe.fonte, clipe.identificador,
                 clipe.licenca, clipe.grupo, round(segundos, 2)]
            )  # fmt: skip
            mantidos.append((clipe, segundos))

    dados = relatorio(mantidos, categorias)
    (args.output / "report.json").write_text(json.dumps(dados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for rotulo, item in dados.items():
        minutos = f"treino {item['minutos_treino']:5} min  teste {item['minutos_teste']:5} min"
        print(f"{rotulo:15} {minutos}  {item['por_fonte']}")


if __name__ == "__main__":
    main()
