"""Testes da lista de categorias de som e da seleção do dataset."""

import array
import importlib.util
import json
import wave
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
LISTA = json.loads((RAIZ / "classes" / "sound_classes.json").read_text(encoding="utf-8"))
ESPEC = importlib.util.spec_from_file_location("prepare_dataset", RAIZ / "training" / "prepare_dataset.py")
preparar = importlib.util.module_from_spec(ESPEC)
ESPEC.loader.exec_module(preparar)
CATEGORIAS = LISTA["categorias"]


def test_silencio_fica_inativa_ate_haver_gravacoes():
    ativas = [c["rotulo"] for c in preparar.carregar_categorias()]
    assert len(ativas) == 14
    assert "silencio" not in ativas


def test_clipe_mudo_e_detectado(tmp_path):
    def gravar(nome, valor):
        caminho = tmp_path / nome
        with wave.open(str(caminho), "wb") as arquivo:
            arquivo.setnchannels(1)
            arquivo.setsampwidth(2)
            arquivo.setframerate(16000)
            arquivo.writeframes(array.array("h", [valor] * 160).tobytes())
        return caminho

    assert preparar.clipe_mudo(gravar("mudo.wav", 3))
    assert not preparar.clipe_mudo(gravar("som.wav", 1000))


def test_lista_tem_as_15_categorias_e_urgencias_validas():
    assert len(CATEGORIAS) == 15
    assert len({c["rotulo"] for c in CATEGORIAS}) == 15
    assert all(c["urgencia"] in (0, 1, 2, 3) for c in CATEGORIAS)


def test_toda_classe_do_audioset_aparece_uma_vez():
    mids = [a["mid"] for c in CATEGORIAS for a in c["audioset"]] + [r["mid"] for r in LISTA["removidas"]]
    assert len(mids) == 67
    assert len(set(mids)) == 67


def test_genericos_pertencem_a_categoria():
    for categoria in CATEGORIAS:
        fontes = categoria["fontes"]
        assert set(fontes["fsd50k_genericos"]) <= set(fontes["fsd50k"])


def test_ancestrais_nao_tiram_o_clipe_da_categoria_especifica():
    assert preparar.categoria_fsd({"Siren", "Alarm"}, CATEGORIAS) == "sirene"
    assert preparar.categoria_fsd({"Vehicle_horn_and_car_horn_and_honking", "Car", "Vehicle"}, CATEGORIAS) == "buzina"
    assert preparar.categoria_fsd({"Gunshot_and_gunfire", "Explosion"}, CATEGORIAS) == "tiro_explosao"


def test_generico_sozinho_define_a_categoria():
    assert preparar.categoria_fsd({"Alarm"}, CATEGORIAS) == "alarme"
    assert preparar.categoria_fsd({"Vehicle"}, CATEGORIAS) == "veiculo"


def test_sons_misturados_ou_de_fora_sao_descartados():
    assert preparar.categoria_fsd({"Speech", "Siren", "Alarm"}, CATEGORIAS) is None
    assert preparar.categoria_fsd({"Piano"}, CATEGORIAS) is None


def test_gravacao_do_teste_nao_fica_no_treino():
    def clipe(identificador, particao, grupo):
        return preparar.Clipe("sirene", "us8k", identificador, Path("x.wav"), particao, "CC0", grupo)

    clipes = [clipe("a", "test", "g1"), clipe("b", "train", "g1"), clipe("c", "train", "g2")]
    assert [c.identificador for c in preparar.separar_grupos_do_teste(clipes)] == ["a", "c"]


def test_mesmo_autor_une_as_tres_bases_e_autor_desconhecido_usa_a_gravacao():
    autores = {"100": "ana", "200": "ana"}
    assert preparar.grupo_freesound("100", autores) == preparar.grupo_freesound("200", autores) == "autor:ana"
    assert preparar.grupo_freesound("300", autores) == "gravacao:300"


def test_autores_vem_dos_creditos_e_dos_metadados(tmp_path):
    creditos = "[soundid] by [username]\n\n10 by Ana\n11 by jo silva\n"
    (tmp_path / "FREESOUNDCREDITS.txt").write_text(creditos, encoding="utf-8")
    meta = tmp_path / "FSD50K.metadata"
    meta.mkdir()
    (meta / "dev_clips_info_FSD50K.json").write_text(json.dumps({"20": {"uploader": "ANA"}}), encoding="utf-8")
    (meta / "eval_clips_info_FSD50K.json").write_text(json.dumps({"21": {}}), encoding="utf-8")
    assert preparar.ler_autores(tmp_path, tmp_path) == {"10": "ana", "11": "jo silva", "20": "ana"}


def test_autor_sorteado_no_teste_sai_do_treino_em_todas_as_bases(monkeypatch):
    def clipe(identificador, fonte, particao, grupo, rotulo="sirene"):
        return preparar.Clipe(rotulo, fonte, identificador, Path("x.wav"), particao, "CC0", grupo)

    monkeypatch.setattr(preparar, "LIMITE_TESTE_S", 10.0)
    clipes = [
        clipe("t", "fsd50k", "test", "autor:ana"),
        clipe("a", "urbansound8k", "train", "autor:ana"),
        clipe("b", "esc50", "train", "autor:ana", rotulo="buzina"),
        clipe("c", "esc50", "train", "autor:bia"),
    ]
    escolhidos = preparar.selecionar_particoes(clipes, [{"rotulo": "sirene"}, {"rotulo": "buzina"}], lambda _c: 10.0)
    assert sorted(c.identificador for c, _ in escolhidos) == ["c", "t"]


def test_candidato_nao_sorteado_para_o_teste_nao_custa_treino(monkeypatch):
    def clipe(identificador, particao, grupo):
        return preparar.Clipe("sirene", "fsd50k", identificador, Path("x.wav"), particao, "CC0", grupo)

    monkeypatch.setattr(preparar, "LIMITE_TESTE_S", 10.0)
    clipes = [clipe("t1", "test", "autor:ana"), clipe("t2", "test", "autor:bia"),
              clipe("a", "train", "autor:ana"), clipe("b", "train", "autor:bia")]  # fmt: skip
    escolhidos = preparar.selecionar_particoes(clipes, [{"rotulo": "sirene"}], lambda _c: 10.0)
    no_teste = {c.grupo for c, _ in escolhidos if c.particao == "test"}
    no_treino = {c.grupo for c, _ in escolhidos if c.particao == "train"}
    assert len(no_teste) == len(no_treino) == 1
    assert no_teste.isdisjoint(no_treino)


def test_licencas_normalizadas():
    assert preparar.normalizar_licenca("http://creativecommons.org/publicdomain/zero/1.0/") == "CC0"
    assert preparar.normalizar_licenca("http://creativecommons.org/licenses/by/3.0/") == "CC-BY"
    assert preparar.normalizar_licenca("http://creativecommons.org/licenses/by-nc/3.0/") == "CC-BY-NC"
    assert preparar.normalizar_licenca("") == "desconhecida"


def test_selecao_respeita_limite_e_mantem_as_duas_fontes():
    clipes = [
        preparar.Clipe("sirene", fonte, str(i), Path("x.wav"), "train", "CC0", f"{fonte}{i}")
        for fonte in ("fsd50k", "esc50")
        for i in range(50)
    ]
    escolhidos = preparar.selecionar(clipes, 100.0, duracao=lambda _caminho: 10.0)
    assert sum(s for _, s in escolhidos) == 100.0
    assert {c.fonte for c, _ in escolhidos} == {"fsd50k", "esc50"}
