"""Testes da opção do instalador que coloca um modelo do Edge Impulse no firmware."""

import shutil
import zipfile
from pathlib import Path

import elex_installer as inst
import pytest

RAIZ = Path(__file__).resolve().parent.parent
VARIAVEIS = 'const char* ei_classifier_inferencing_categories_1_2[] = { "sirene", "siren", "dog" };\n'


class SaidaMuda(inst.Saida):
    def __init__(self):
        self.linhas = []

    def etapa(self, _chave, texto):
        self.linhas.append(texto)

    def info(self, texto):
        self.linhas.append(texto)

    aviso = erro = detalhe = info


def exportacao(pasta: Path, nome="Novo_Projeto_inferencing", frequencia=16000) -> Path:
    """Estrutura mínima de Deployment → Arduino library."""
    raiz = pasta / nome
    (raiz / "src" / "model-parameters").mkdir(parents=True)
    (raiz / "library.properties").write_text(f"name={nome}\n", encoding="utf-8")
    (raiz / "src" / f"{nome}.h").write_text("// modelo\n", encoding="utf-8")
    (raiz / "src" / "model-parameters" / "model_metadata.h").write_text(
        f"#define EI_CLASSIFIER_FREQUENCY                  {frequencia}\n", encoding="utf-8"
    )
    (raiz / "src" / "model-parameters" / "model_variables.h").write_text(VARIAVEIS, encoding="utf-8")
    return raiz


def zipar(raiz: Path, destino: Path) -> Path:
    with zipfile.ZipFile(destino, "w") as arquivo:
        for item in raiz.rglob("*"):
            arquivo.write(item, item.relative_to(raiz.parent).as_posix())
    return destino


def checkout(pasta: Path) -> Path:
    """Cópia com firmware e lista de classes, como um clone do repositório."""
    for relativo in ("firmware/platformio.ini", "firmware/src/main.cpp", "classes/sound_classes.json"):
        (pasta / relativo).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(RAIZ / relativo, pasta / relativo)
    antigo = pasta / "firmware" / "lib" / "ei-model" / "ELEX20_Categorias_inferencing"
    antigo.mkdir(parents=True)
    (antigo / "velho.h").write_text("", encoding="utf-8")
    return pasta


def instalar(pasta: Path, modelo: Path):
    saida = SaidaMuda()
    respostas = inst.Respostas(destino=pasta, modelo_ei=modelo)
    return inst.Instalador(RAIZ, respostas, True, saida).incluir_modelo_ei(), saida


def test_acha_a_biblioteca_na_raiz_ou_na_primeira_pasta():
    assert inst.achar_biblioteca_ei(["library.properties", "src/A_inferencing.h"]) == ("", "A_inferencing")
    assert inst.achar_biblioteca_ei(["x/library.properties", "x/src/B_inferencing.h", "x/src/outro.h"]) == (
        "x/",
        "B_inferencing",
    )
    assert inst.achar_biblioteca_ei(["src/A_inferencing.h"]) is None
    assert inst.achar_biblioteca_ei(["library.properties", "src/main.h"]) is None


def test_validar_modelo(tmp_path):
    assert inst.validar_modelo_ei("") is not None
    assert "does not exist" in inst.validar_modelo_ei(str(tmp_path / "nada.zip"))
    texto = tmp_path / "x.txt"
    texto.write_text("x", encoding="utf-8")
    assert ".zip" in inst.validar_modelo_ei(str(texto))
    assert "not an Edge Impulse" in inst.validar_modelo_ei(str(tmp_path))
    raiz = exportacao(tmp_path / "exp")
    assert inst.validar_modelo_ei(str(raiz)) is None
    assert inst.validar_modelo_ei(str(zipar(raiz, tmp_path / "m.zip"))) is None


def test_rotulos_do_modelo_e_desconhecidos():
    rotulos = inst.rotulos_do_modelo_ei(VARIAVEIS)
    assert rotulos == ["sirene", "siren", "dog"]
    categorias = [{"rotulo": "siren", "rotulo_legado": "sirene"}, {"rotulo": "animal"}]
    assert inst.rotulos_desconhecidos(rotulos, categorias) == ["dog"]


def test_trocar_nome_do_modelo():
    texto = '-DEI_MODEL_HEADER=\\"ELEX20_Categorias_inferencing.h\\"\nsymlink://lib/ei-model/ELEX20_Categorias_inferencing\n'
    novo = inst.trocar_nome_do_modelo_ei(texto, "Outro_inferencing")
    assert "ELEX20_Categorias" not in novo
    assert novo.count("Outro_inferencing") == 2


@pytest.mark.parametrize("como_zip", [True, False])
def test_inclui_o_modelo_e_aponta_o_build_para_ele(tmp_path, como_zip):
    pasta = checkout(tmp_path / "repo")
    raiz = exportacao(tmp_path / "exp")
    ok, saida = instalar(pasta, zipar(raiz, tmp_path / "m.zip") if como_zip else raiz)
    assert ok
    modelos = pasta / "firmware" / "lib" / "ei-model"
    assert [p.name for p in modelos.iterdir()] == ["Novo_Projeto_inferencing"]
    assert (modelos / "Novo_Projeto_inferencing" / "src" / "Novo_Projeto_inferencing.h").is_file()
    ini = (pasta / "firmware" / "platformio.ini").read_text(encoding="utf-8")
    main = (pasta / "firmware" / "src" / "main.cpp").read_text(encoding="utf-8")
    assert "ELEX20_Categorias" not in ini + main
    assert '-DEI_MODEL_HEADER=\\"Novo_Projeto_inferencing.h\\"' in ini
    assert "symlink://lib/ei-model/Novo_Projeto_inferencing" in ini
    assert "#  include <Novo_Projeto_inferencing.h>" in main
    assert any("dog" in linha and "unknown" in linha for linha in saida.linhas)


def test_recusa_modelo_com_outra_taxa_de_amostragem(tmp_path):
    pasta = checkout(tmp_path / "repo")
    ok, saida = instalar(pasta, exportacao(tmp_path / "exp", frequencia=8000))
    assert not ok
    assert any("8000 Hz" in linha for linha in saida.linhas)
    # O modelo anterior continua lá
    assert (pasta / "firmware" / "lib" / "ei-model" / "ELEX20_Categorias_inferencing").is_dir()


def test_recusa_zip_com_caminho_para_fora(tmp_path):
    pasta = checkout(tmp_path / "repo")
    zip_ruim = tmp_path / "ruim.zip"
    with zipfile.ZipFile(zip_ruim, "w") as arquivo:
        arquivo.writestr("library.properties", "")
        arquivo.writestr("src/X_inferencing.h", "")
        arquivo.writestr("../../fora.txt", "")
    ok, _ = instalar(pasta, zip_ruim)
    assert not ok
    assert not (tmp_path / "fora.txt").exists()


def test_etapa_so_aparece_com_modelo(tmp_path):
    sem = inst.Instalador(RAIZ, inst.Respostas(destino=tmp_path), True, SaidaMuda())
    com = inst.Instalador(RAIZ, inst.Respostas(destino=tmp_path, modelo_ei=tmp_path), True, SaidaMuda())
    assert "ei-model" not in dict(sem.etapas())
    assert "ei-model" in dict(com.etapas())


def test_flag_ei_model_recusa_caminho_invalido(tmp_path, capsys):
    with pytest.raises(SystemExit):
        inst.main(["--ei-model", str(tmp_path / "nada.zip"), "--non-interactive", "--dry-run"])
    assert "--ei-model" in capsys.readouterr().err
