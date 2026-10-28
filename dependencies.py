#!/usr/bin/env python3
"""
Gerenciador de dependências do projeto ELEX20 — UV exclusivo.

Responsabilidades:
  - Limpar cache e artefatos temporários
  - Detectar imports nos arquivos Python do projeto
  - Verificar e instalar dependências faltantes via `uv sync`
  - Auditar o lockfile (uv.lock) contra pyproject.toml

Fonte única de verdade: pyproject.toml + uv.lock
Não lê nem gera requirements.txt.
"""

import os
import re
import shutil
import subprocess
import sys
import tomllib
from datetime import datetime
from pathlib import Path


class Colors:
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


class UVDependencyManager:
    def __init__(self):
        self.project_root = Path.cwd()
        self.venv_path = self.project_root / ".venv"
        self.pyproject_file = self.project_root / "pyproject.toml"
        self.log_file = self.project_root / "dependency_manager.log"
        self.uv_available = self._check_uv()
        self.installed_packages: dict[str, str] = {}

    # ──────────────────────────────── utilidades ────────────────────────────

    def _check_uv(self) -> bool:
        try:
            r = subprocess.run(["uv", "--version"], capture_output=True, timeout=10)
            return r.returncode == 0
        except FileNotFoundError:
            return False

    def _uv_version(self) -> str:
        try:
            r = subprocess.run(
                ["uv", "--version"], capture_output=True, text=True, timeout=10
            )
            return r.stdout.split()[1] if r.returncode == 0 else "desconhecida"
        except Exception:
            return "desconhecida"

    def _log(self, message: str, level: str = "INFO") -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] [{level}] {message}"
        print(line)
        with open(self.log_file, "a") as f:
            f.write(line + "\n")

    def _section(self, title: str) -> None:
        print(f"\n{Colors.BOLD}{Colors.MAGENTA}{'='*60}")
        print(f"  {title}")
        print(f"{'='*60}{Colors.RESET}\n")

    # ──────────────────────────────── verificação ────────────────────────────

    def verify_environment(self) -> None:
        self._section("✅ VERIFICAÇÃO DO AMBIENTE")

        checks = {
            "Python": sys.version.split()[0],
            "UV": self._uv_version() if self.uv_available else "NÃO INSTALADO",
            "Sistema": sys.platform,
            "Raiz do projeto": str(self.project_root),
            "pyproject.toml": "encontrado" if self.pyproject_file.exists() else "AUSENTE",
        }

        for name, value in checks.items():
            ok = value not in ("NÃO INSTALADO", "AUSENTE")
            color = Colors.GREEN if ok else Colors.YELLOW
            print(f"{Colors.BOLD}{name}:{Colors.RESET} {color}{value}{Colors.RESET}")

        if not self.uv_available:
            print(
                f"\n{Colors.YELLOW}⚠ UV não encontrado. Instale em: https://docs.astral.sh/uv/{Colors.RESET}"
            )

        if not self.pyproject_file.exists():
            print(f"\n{Colors.RED}✗ pyproject.toml ausente — execute na raiz do projeto.{Colors.RESET}")
            sys.exit(1)

    # ──────────────────────────────── limpeza ────────────────────────────────

    def clean_environment(self) -> None:
        self._section("🧹 LIMPEZA DO AMBIENTE")

        patterns_glob = ["**/__pycache__", "**/*.pyc", "**/*.pyo", "**/*.egg-info"]
        dirs_direct = [
            ".pytest_cache", ".mypy_cache", ".ruff_cache",
            ".eggs", "dist", "build", "htmlcov", ".uv_cache",
        ]

        removed = 0
        for pattern in patterns_glob:
            for item in self.project_root.glob(pattern):
                if ".venv" in item.parts:
                    continue
                try:
                    if item.is_file():
                        item.unlink()
                    else:
                        shutil.rmtree(item)
                    removed += 1
                except Exception as e:
                    self._log(f"Erro ao limpar {item}: {e}", "WARNING")

        for name in dirs_direct:
            path = self.project_root / name
            if path.exists() and path != self.venv_path:
                try:
                    shutil.rmtree(path)
                    self._log(f"✓ Removido: {name}")
                    removed += 1
                except Exception as e:
                    self._log(f"Erro ao limpar {name}: {e}", "WARNING")

        try:
            subprocess.run(["uv", "cache", "clean"], capture_output=True, timeout=30)
            print(f"{Colors.GREEN}✓ Cache UV limpo{Colors.RESET}")
        except Exception:
            pass

        print(f"{Colors.GREEN}✓ Limpeza: {removed} itens removidos{Colors.RESET}")

    # ──────────────────────────────── pacotes ────────────────────────────────

    def get_installed_packages(self) -> bool:
        """Popula self.installed_packages via `uv pip list`."""
        import json

        try:
            r = subprocess.run(
                ["uv", "pip", "list", "--format=json"],
                capture_output=True, text=True, timeout=30,
            )
            if r.returncode == 0:
                pkgs = json.loads(r.stdout)
                self.installed_packages = {p["name"].lower(): p["version"] for p in pkgs}
                return True
        except Exception as e:
            self._log(f"Erro ao listar pacotes: {e}", "WARNING")
        return False

    def read_pyproject_toml(self) -> set[str]:
        """Retorna o conjunto de nomes de pacotes declarados em pyproject.toml."""
        deps: set[str] = set()
        try:
            with open(self.pyproject_file, "rb") as f:
                data = tomllib.load(f)
            for dep in data.get("project", {}).get("dependencies", []):
                pkg = re.split(r"[<>=!;]", dep)[0].strip()
                if pkg:
                    deps.add(pkg)
            print(f"✓ {len(deps)} dependências em pyproject.toml")
        except Exception as e:
            self._log(f"Erro ao ler pyproject.toml: {e}", "WARNING")
        return deps

    def detect_python_files(self) -> tuple[set[str], set[str]]:
        """Detecta imports externos nos arquivos .py do projeto."""
        self._section("🔍 DETECÇÃO DE IMPORTS")

        stdlib = {
            "os", "sys", "json", "csv", "re", "math", "random", "datetime",
            "collections", "itertools", "functools", "operator", "pathlib",
            "subprocess", "shutil", "tempfile", "glob", "io", "time",
            "hashlib", "hmac", "secrets", "struct", "codecs", "string",
            "urllib", "http", "socket", "ssl", "asyncio", "threading",
            "multiprocessing", "logging", "traceback", "warnings", "inspect",
            "copy", "pprint", "enum", "types", "numbers", "decimal",
            "statistics", "sqlite3", "pickle", "zipfile", "tarfile",
            "configparser", "email", "mimetypes", "base64", "binascii",
            "html", "xml", "unittest", "doctest", "pdb", "gc", "abc",
            "argparse", "tomllib", "toml", "typing",
        }

        imports: set[str] = set()
        std: set[str] = set()

        py_files = [
            p for p in self.project_root.rglob("*.py")
            if ".venv" not in p.parts and "venv" not in p.parts
        ]

        if not py_files:
            print(f"{Colors.YELLOW}⚠ Nenhum arquivo Python encontrado{Colors.RESET}")
            return imports, std

        print(f"Analisando {len(py_files)} arquivo(s)…\n")

        for py_file in py_files:
            try:
                content = py_file.read_text(encoding="utf-8", errors="ignore")
                found = re.findall(r"from\s+([a-zA-Z_][a-zA-Z0-9_.]*)", content)
                found += re.findall(r"import\s+([a-zA-Z_][a-zA-Z0-9_.,\s]*)", content)
                for imp in found:
                    root = imp.split(".")[0].split(",")[0].strip()
                    if not root or root.startswith("_"):
                        continue
                    (std if root in stdlib else imports).add(root)
            except Exception as e:
                self._log(f"Erro ao ler {py_file}: {e}", "WARNING")

        return imports, std

    _IMPORT_MAP = {
        "cv2": "opencv-python",
        "PIL": "pillow",
        "sklearn": "scikit-learn",
        "yaml": "pyyaml",
        "bs4": "beautifulsoup4",
        "dotenv": "python-dotenv",
        "jose": "python-jose",
        "jwt": "pyjwt",
        "psycopg2": "psycopg2-binary",
    }

    def _pkg_name(self, import_name: str) -> str:
        return self._IMPORT_MAP.get(import_name, import_name)

    def check_missing_packages(self, imports: set[str]) -> tuple[list[str], list[str]]:
        self._section("📦 VERIFICAÇÃO DE DEPENDÊNCIAS")
        missing, installed = [], []
        for imp in sorted(imports):
            pkg = self._pkg_name(imp)
            if pkg.lower() in self.installed_packages:
                ver = self.installed_packages[pkg.lower()]
                print(f"{Colors.GREEN}✓{Colors.RESET} {pkg} ({ver})")
                installed.append(pkg)
            else:
                print(f"{Colors.YELLOW}✗{Colors.RESET} {pkg} — faltando")
                missing.append(pkg)
        return missing, installed

    # ──────────────────────────────── instalação ─────────────────────────────

    def sync(self) -> bool:
        """Sincroniza o ambiente via `uv sync --frozen` (usa uv.lock)."""
        self._section("⚡ SINCRONIZAÇÃO COM UV")
        if not self.uv_available:
            print(f"{Colors.RED}✗ UV não disponível.{Colors.RESET}")
            return False
        r = subprocess.run(["uv", "sync", "--frozen"], timeout=300)
        ok = r.returncode == 0
        msg = "✓ Ambiente sincronizado." if ok else "✗ Falha na sincronização."
        print(f"\n{Colors.GREEN if ok else Colors.RED}{msg}{Colors.RESET}")
        self._log(msg, "INFO" if ok else "ERROR")
        return ok

    def install_packages(self, packages: list[str]) -> bool:
        """Instala pacotes avulsos via `uv pip install` (sem alterar pyproject.toml)."""
        if not packages:
            print(f"{Colors.GREEN}✓ Nenhum pacote a instalar.{Colors.RESET}")
            return True
        if not self.uv_available:
            print(f"{Colors.RED}✗ UV não disponível — instale em https://docs.astral.sh/uv/{Colors.RESET}")
            return False
        self._section("⚡ INSTALAÇÃO COM UV")
        r = subprocess.run(["uv", "pip", "install"] + packages, timeout=300)
        ok = r.returncode == 0
        self._log(f"Instalados: {packages}" if ok else "Falha na instalação", "INFO" if ok else "ERROR")
        return ok

    def check_lock(self) -> bool:
        """Verifica se uv.lock está consistente com pyproject.toml."""
        self._section("🔒 VERIFICAÇÃO DO LOCKFILE")
        r = subprocess.run(["uv", "lock", "--check"], capture_output=True, text=True, timeout=30)
        ok = r.returncode == 0
        if ok:
            print(f"{Colors.GREEN}✓ uv.lock está atualizado.{Colors.RESET}")
        else:
            print(f"{Colors.YELLOW}⚠ uv.lock desatualizado — execute `uv lock` para atualizar.{Colors.RESET}")
        return ok

    # ──────────────────────────────── pipeline ───────────────────────────────

    def run(self, auto_install: bool = True) -> None:
        print(f"\n{Colors.BOLD}{Colors.MAGENTA}🚀 GERENCIADOR DE DEPENDÊNCIAS — UV{Colors.RESET}\n")

        self.verify_environment()
        self.clean_environment()
        self.get_installed_packages()

        detected, stdlib = self.detect_python_files()
        print(f"\nBibliotecas padrão: {len(stdlib)} | Pacotes externos: {len(detected)}")

        pyproject_pkgs = self.read_pyproject_toml()
        detected.update(pyproject_pkgs)

        missing, installed = self.check_missing_packages(detected)

        if missing and auto_install:
            self.install_packages(missing)
            self.get_installed_packages()
        elif missing:
            print(f"\n{Colors.YELLOW}⚠ {len(missing)} pacote(s) faltando. Rode `uv sync` para instalar.{Colors.RESET}")

        self.check_lock()

        self._section("📊 RESUMO")
        print(f"Total detectado : {len(detected)}")
        print(f"Instalados      : {len(installed)}")
        print(f"Faltavam        : {len(missing)}")
        print(f"Log             : {self.log_file}\n")
        print(f"{Colors.GREEN}✓ Concluído.{Colors.RESET}\n")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Gerenciador de dependências UV — ELEX20")
    parser.add_argument("--no-install", action="store_true", help="Detecta sem instalar")
    parser.add_argument("--version", action="store_true", help="Exibe versão do UV")
    parser.add_argument("--sync", action="store_true", help="Executa apenas uv sync --frozen")
    parser.add_argument("--lock-check", action="store_true", help="Verifica consistência do uv.lock")
    args = parser.parse_args()

    mgr = UVDependencyManager()

    if args.version:
        if mgr.uv_available:
            print(f"UV versão: {mgr._uv_version()}")
        else:
            print("UV não instalado")
        return

    if args.sync:
        sys.exit(0 if mgr.sync() else 1)

    if args.lock_check:
        sys.exit(0 if mgr.check_lock() else 1)

    mgr.run(auto_install=not args.no_install)


if __name__ == "__main__":
    main()
