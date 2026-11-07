# -*- mode: python ; coding: utf-8 -*-
# Empacota o instalador num executável único (Windows, macOS e Linux) com os arquivos
# da stack embutidos. Build, a partir da raiz do repositório:
#   uvx --from "pyinstaller>=6.11" --with "textual==8.2.8" pyinstaller installer/elex_installer.spec --noconfirm
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

pasta_do_spec = Path(SPECPATH)  # noqa: F821 (definido pelo PyInstaller)
raiz = pasta_do_spec.parent
sys.path.insert(0, str(pasta_do_spec))
import elex_installer  # noqa: E402


def arquivos_embutidos():
    for relativo in elex_installer.ARQUIVOS_DO_PROJETO:
        fonte = raiz / relativo
        if not fonte.exists():
            raise SystemExit(f"arquivo do projeto ausente: {relativo}")
        candidatos = [fonte] if fonte.is_file() else sorted(p for p in fonte.rglob("*") if p.is_file())
        for arquivo in candidatos:
            if "__pycache__" in arquivo.parts:
                continue
            destino = arquivo.relative_to(raiz).parent
            yield (str(arquivo), str(destino))


a = Analysis(  # noqa: F821
    [str(pasta_do_spec / "elex_installer.py")],
    pathex=[str(pasta_do_spec)],
    datas=[*arquivos_embutidos(), (str(pasta_do_spec / "version.txt"), "."), *collect_data_files("textual")],
    # O Textual e o Rich importam módulos sob demanda, e a análise estática não os enxerga
    hiddenimports=["elex_tui", *collect_submodules("textual"), *collect_submodules("rich")],
    excludes=["tkinter", "unittest", "pydoc", "test"],
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="elex-installer",
    console=True,
    upx=False,
)
