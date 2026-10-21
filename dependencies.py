#!/usr/bin/env python3
"""
Script inteligente de gerenciamento de dependências otimizado para UV
- Limpa arquivos temporários e cache
- Detecta bibliotecas necessárias
- Instala dependências faltantes usando UV (super rápido!)
- Verifica integridade do ambiente
- Suporta pyproject.toml
"""

import os
import sys
import subprocess
import json
import shutil
import importlib.util
from pathlib import Path
from datetime import datetime
import re
import tomllib  # Python 3.11+

# Cores para terminal
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

class UVDependencyManager:
    def __init__(self):
        self.log_file = Path("dependency_manager_uv.log")
        self.project_root = Path.cwd()
        self.venv_path = self.project_root / ".venv"
        self.pyproject_file = self.project_root / "pyproject.toml"
        self.requirements_file = self.project_root / "requirements.txt"
        self.uv_available = self.check_uv_installed()
        self.installed_packages = {}
        
    def log(self, message, level="INFO"):
        """Registra mensagens no console e em arquivo"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_message = f"[{timestamp}] [{level}] {message}"
        print(log_message)
        
        with open(self.log_file, "a") as f:
            f.write(log_message + "\n")
    
    def print_section(self, title):
        """Imprime seção formatada"""
        print(f"\n{Colors.BOLD}{Colors.MAGENTA}{'='*60}")
        print(f"  {title}")
        print(f"{'='*60}{Colors.RESET}\n")
    
    def check_uv_installed(self):
        """Verifica se UV está instalado"""
        try:
            result = subprocess.run(
                ["uv", "--version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return True
        except FileNotFoundError:
            pass
        return False
    
    def clean_environment(self):
        """Limpa arquivos temporários e cache do UV"""
        self.print_section("🧹 LIMPEZA DO AMBIENTE")
        
        directories_to_clean = [
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
            "*.pyc",
            "*.pyo",
            ".eggs",
            "*.egg-info",
            "dist",
            "build",
            ".coverage",
            "htmlcov",
            ".uv_cache"
        ]
        
        cleaned_count = 0
        
        for pattern in directories_to_clean:
            if "*" in pattern:
                # Padrão com wildcard
                for item in self.project_root.rglob(pattern):
                    try:
                        if item.is_file():
                            item.unlink()
                            cleaned_count += 1
                        elif item.is_dir() and item.parent != self.venv_path:
                            shutil.rmtree(item)
                            cleaned_count += 1
                    except Exception as e:
                        self.log(f"Erro ao limpar {item}: {e}", "WARNING")
            else:
                # Diretório específico
                path = self.project_root / pattern
                if path.exists() and path != self.venv_path:
                    try:
                        if path.is_dir():
                            shutil.rmtree(path)
                            self.log(f"✓ Removido: {pattern}", "INFO")
                            cleaned_count += 1
                    except Exception as e:
                        self.log(f"Erro ao limpar {pattern}: {e}", "WARNING")
        
        # Limpa cache do UV
        try:
            subprocess.run(["uv", "cache", "clean"], capture_output=True, timeout=30)
            print(f"{Colors.GREEN}✓ Cache do UV limpo{Colors.RESET}")
        except Exception:
            pass
        
        print(f"{Colors.GREEN}✓ Limpeza concluída: {cleaned_count} itens removidos{Colors.RESET}")
        self.log(f"Limpeza concluída: {cleaned_count} itens", "INFO")
    
    def get_installed_packages(self):
        """Obtém lista de pacotes instalados usando UV"""
        try:
            result = subprocess.run(
                ["uv", "pip", "list", "--format=json"],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                packages = json.loads(result.stdout)
                self.installed_packages = {pkg['name'].lower(): pkg['version'] for pkg in packages}
                return True
        except Exception as e:
            self.log(f"Erro ao obter pacotes instalados: {e}", "WARNING")
        return False
    
    def detect_python_files(self):
        """Detecta imports em arquivos Python do projeto"""
        self.print_section("🔍 DETECÇÃO DE DEPENDÊNCIAS")
        
        imports = set()
        standard_libs = set()
        
        # Lista de bibliotecas padrão do Python
        stdlib_modules = {
            'os', 'sys', 'json', 'csv', 're', 'math', 'random', 'datetime',
            'collections', 'itertools', 'functools', 'operator', 'pathlib',
            'subprocess', 'shutil', 'tempfile', 'glob', 'io', 'time', 'calendar',
            'hashlib', 'hmac', 'secrets', 'struct', 'codecs', 'string', 'difflib',
            'textwrap', 'unicodedata', 'locale', 'gettext', 'ftplib', 'poplib',
            'imaplib', 'smtplib', 'urllib', 'http', 'socketserver', 'socket',
            'ssl', 'select', 'asyncio', 'threading', 'multiprocessing', 'logging',
            'getpass', 'curses', 'platform', 'traceback', 'warnings', 'inspect',
            'runpy', 'pkgutil', 'importlib', 'zipimport', 'ast', 'symtable',
            'token', 'keyword', 'tokenize', 'tabnanny', 'copy', 'pprint', 'enum',
            'types', 'graphlib', 'numbers', 'cmath', 'decimal', 'statistics',
            'sqlite3', 'pickle', 'shelve', 'dbm', 'zlib', 'gzip', 'bz2', 'lzma',
            'zipfile', 'tarfile', 'configparser', 'netrc', 'plistlib', 'email',
            'mailbox', 'mimetypes', 'base64', 'binhex', 'binascii', 'quopri',
            'uu', 'html', 'xml', 'webbrowser', 'tomllib', 'toml', 'unittest',
            'doctest', 'pdb', 'cProfile', 'timeit', 'trace', 'gc', 'atexit',
            'abc', 'rlcompleter', 'cmd', 'shlex', 'argparse', 'optparse'
        }
        
        # Procura por arquivos Python
        python_files = list(self.project_root.rglob("*.py"))
        
        if not python_files:
            print(f"{Colors.YELLOW}⚠ Nenhum arquivo Python encontrado no projeto{Colors.RESET}")
            return imports, standard_libs
        
        print(f"Analisando {len(python_files)} arquivo(s) Python...\n")
        
        for py_file in python_files:
            # Ignora arquivos em .venv
            if ".venv" in py_file.parts or "venv" in py_file.parts:
                continue
            
            try:
                with open(py_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    
                    # Detecta: from xxx import yyy
                    from_imports = re.findall(r'from\s+([a-zA-Z_][a-zA-Z0-9_.]*)', content)
                    # Detecta: import xxx
                    direct_imports = re.findall(r'import\s+([a-zA-Z_][a-zA-Z0-9_.,\s]*)', content)
                    
                    for imp in from_imports + direct_imports:
                        # Pega apenas o pacote raiz
                        root_module = imp.split('.')[0].split(',')[0].strip()
                        
                        if root_module in stdlib_modules:
                            standard_libs.add(root_module)
                        elif root_module and not root_module.startswith('_'):
                            imports.add(root_module)
            except Exception as e:
                self.log(f"Erro ao ler {py_file}: {e}", "WARNING")
        
        return imports, standard_libs
    
    def read_pyproject_toml(self):
        """Lê dependências do pyproject.toml"""
        dependencies = set()
        
        if not self.pyproject_file.exists():
            return dependencies
        
        try:
            with open(self.pyproject_file, 'rb') as f:
                data = tomllib.load(f)
                
            # Tenta diferentes formatos
            if 'project' in data and 'dependencies' in data['project']:
                for dep in data['project']['dependencies']:
                    pkg = re.split(r'[<>=!]', dep)[0].strip()
                    if pkg:
                        dependencies.add(pkg)
            
            # Tenta opcional dependencies
            if 'project' in data and 'optional-dependencies' in data['project']:
                for group_deps in data['project']['optional-dependencies'].values():
                    for dep in group_deps:
                        pkg = re.split(r'[<>=!]', dep)[0].strip()
                        if pkg:
                            dependencies.add(pkg)
            
            print(f"✓ Encontradas {len(dependencies)} dependências em pyproject.toml")
            
        except Exception as e:
            self.log(f"Erro ao ler pyproject.toml: {e}", "WARNING")
        
        return dependencies
    
    def check_requirements_file(self):
        """Lê requirements.txt se existir"""
        requirements = set()
        
        if self.requirements_file.exists():
            try:
                with open(self.requirements_file, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            # Remove versões e extras
                            pkg = re.split(r'[<>=!]', line)[0].strip()
                            if pkg:
                                requirements.add(pkg)
            except Exception as e:
                self.log(f"Erro ao ler requirements.txt: {e}", "WARNING")
        
        return requirements
    
    def map_import_to_package(self, import_name):
        """Mapeia nome de importação para nome de pacote pip"""
        mapping = {
            'cv2': 'opencv-python',
            'PIL': 'pillow',
            'sklearn': 'scikit-learn',
            'yaml': 'pyyaml',
            'bs4': 'beautifulsoup4',
            'dotenv': 'python-dotenv',
            'jose': 'python-jose',
            'jwt': 'pyjwt',
            'magic': 'python-magic',
            'MySQLdb': 'mysqlclient',
            'psycopg2': 'psycopg2-binary',
            'lxml': 'lxml',
        }
        return mapping.get(import_name, import_name)
    
    def check_missing_packages(self, detected_imports):
        """Verifica quais pacotes estão faltando"""
        self.print_section("📦 VERIFICAÇÃO DE DEPENDÊNCIAS")
        
        missing = []
        installed = []
        
        for imp in sorted(detected_imports):
            pip_name = self.map_import_to_package(imp)
            
            # Verifica se está instalado
            if pip_name.lower() in self.installed_packages:
                version = self.installed_packages[pip_name.lower()]
                print(f"{Colors.GREEN}✓{Colors.RESET} {pip_name} ({version})")
                installed.append(pip_name)
            else:
                print(f"{Colors.YELLOW}✗{Colors.RESET} {pip_name} - FALTANDO")
                missing.append(pip_name)
        
        return missing, installed
    
    def install_packages_uv(self, packages):
        """Instala pacotes usando UV (muito mais rápido!)"""
        if not packages:
            print(f"\n{Colors.GREEN}✓ Todas as dependências já estão instaladas!{Colors.RESET}")
            return True
        
        self.print_section("⚡ INSTALAÇÃO COM UV (RÁPIDO!)")
        
        print(f"Instalando {len(packages)} pacote(s)...\n")
        
        try:
            # UV instala múltiplos pacotes de uma vez
            cmd = ["uv", "pip", "install"] + packages
            
            result = subprocess.run(
                cmd,
                capture_output=False,
                text=True,
                timeout=300
            )
            
            if result.returncode == 0:
                print(f"\n{Colors.GREEN}✓ Pacotes instalados com sucesso!{Colors.RESET}")
                self.log(f"Pacotes instalados: {', '.join(packages)}", "INFO")
                return True
            else:
                print(f"\n{Colors.RED}✗ Erro durante instalação{Colors.RESET}")
                self.log("Erro durante instalação com UV", "ERROR")
                return False
                
        except Exception as e:
            self.log(f"Erro durante instalação: {e}", "ERROR")
            print(f"{Colors.RED}✗ Erro durante instalação: {e}{Colors.RESET}")
            return False
    
    def install_packages_fallback(self, packages):
        """Fallback para pip se UV não estiver disponível"""
        if not packages:
            return True
        
        self.print_section("📥 INSTALAÇÃO COM PIP (FALLBACK)")
        
        print(f"Instalando {len(packages)} pacote(s) com pip...\n")
        
        try:
            for package in packages:
                print(f"Instalando {Colors.BOLD}{package}{Colors.RESET}...")
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", package, "-q"],
                    capture_output=True,
                    text=True,
                    timeout=120
                )
                
                if result.returncode == 0:
                    print(f"{Colors.GREEN}✓ {package} instalado{Colors.RESET}")
                else:
                    print(f"{Colors.RED}✗ Erro ao instalar {package}{Colors.RESET}")
                    self.log(f"Erro ao instalar {package}", "ERROR")
            
            return True
        except Exception as e:
            self.log(f"Erro durante instalação: {e}", "ERROR")
            return False
    
    def generate_pyproject_toml(self, packages):
        """Gera ou atualiza pyproject.toml"""
        if self.pyproject_file.exists():
            print(f"{Colors.YELLOW}⚠ pyproject.toml já existe, não sobrescrevendo{Colors.RESET}")
            return True
        
        try:
            content = f"""[project]
name = "my-project"
version = "0.1.0"
description = "Meu projeto Python"
requires-python = ">=3.11"
dependencies = [
"""
            
            for package in sorted(packages):
                if package.lower() in self.installed_packages:
                    version = self.installed_packages[package.lower()]
                    content += f'    "{package}=={version}",\n'
                else:
                    content += f'    "{package}",\n'
            
            content += """]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.uv]
dev-dependencies = [
    "pytest>=7.0",
    "black>=23.0",
    "ruff>=0.1.0",
]
"""
            
            with open(self.pyproject_file, 'w') as f:
                f.write(content)
            
            print(f"{Colors.GREEN}✓ pyproject.toml criado{Colors.RESET}")
            self.log("pyproject.toml gerado", "INFO")
            return True
        except Exception as e:
            self.log(f"Erro ao gerar pyproject.toml: {e}", "ERROR")
            return False
    
    def generate_requirements_file(self, packages):
        """Gera requirements.txt com os pacotes detectados"""
        try:
            with open(self.requirements_file, 'w') as f:
                f.write("# Dependências do projeto\n")
                f.write("# Gerado automaticamente com UV\n\n")
                
                for package in sorted(packages):
                    if package.lower() in self.installed_packages:
                        version = self.installed_packages[package.lower()]
                        f.write(f"{package}=={version}\n")
                    else:
                        f.write(f"{package}\n")
            
            print(f"{Colors.GREEN}✓ requirements.txt atualizado{Colors.RESET}")
            self.log("requirements.txt gerado", "INFO")
            return True
        except Exception as e:
            self.log(f"Erro ao gerar requirements.txt: {e}", "ERROR")
            return False
    
    def verify_environment(self):
        """Verifica a integridade do ambiente"""
        self.print_section("✅ VERIFICAÇÃO DO AMBIENTE")
        
        checks = {
            "Python": sys.version.split()[0],
            "UV": self.get_uv_version() if self.uv_available else "NÃO INSTALADO",
            "Pip": self.get_pip_version(),
            "Sistema": sys.platform,
            "Diretório do projeto": str(self.project_root),
        }
        
        for name, value in checks.items():
            status = Colors.GREEN if value != "NÃO INSTALADO" else Colors.YELLOW
            print(f"{Colors.BOLD}{name}:{Colors.RESET} {status}{value}{Colors.RESET}")
        
        if not self.uv_available:
            print(f"\n{Colors.YELLOW}⚠ UV não encontrado. Instale com: pip install uv{Colors.RESET}")
            print(f"{Colors.YELLOW}  Ou: curl -LsSf https://astral.sh/uv/install.sh | sh{Colors.RESET}")
        
        return True
    
    def get_uv_version(self):
        """Obtém versão do UV"""
        try:
            result = subprocess.run(
                ["uv", "--version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.stdout.split()[1] if result.returncode == 0 else "desconhecida"
        except Exception:
            return "desconhecida"

    def get_pip_version(self):
        """Obtém versão do pip"""
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "--version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.stdout.split()[1] if result.returncode == 0 else "desconhecida"
        except Exception:
            return "desconhecida"
    
    def run(self, auto_install=True):
        """Executa o pipeline completo"""
        print(f"\n{Colors.BOLD}{Colors.MAGENTA}🚀 GERENCIADOR DE DEPENDÊNCIAS COM UV{Colors.RESET}\n")
        
        # 1. Verifica ambiente
        self.verify_environment()
        
        # 2. Limpa ambiente
        self.clean_environment()
        
        # 3. Obtém pacotes instalados
        print(f"\n{Colors.BOLD}Obtendo lista de pacotes instalados...{Colors.RESET}")
        self.get_installed_packages()
        
        # 4. Detecta imports
        detected_imports, stdlib = self.detect_python_files()
        print(f"\nBibliotecas padrão encontradas: {len(stdlib)}")
        print(f"Pacotes externos detectados: {len(detected_imports)}")
        
        if detected_imports:
            print(f"\nPacotes detectados: {', '.join(sorted(detected_imports)[:10])}")
            if len(detected_imports) > 10:
                print(f"... e mais {len(detected_imports) - 10}")
        
        # 5. Verifica pyproject.toml
        pyproject_packages = self.read_pyproject_toml()
        if pyproject_packages:
            detected_imports.update(pyproject_packages)
        
        # 6. Verifica requirements.txt
        req_packages = self.check_requirements_file()
        if req_packages:
            print(f"\n{Colors.BLUE}Pacotes em requirements.txt: {len(req_packages)}{Colors.RESET}")
            detected_imports.update(req_packages)
        
        # 7. Verifica faltantes
        missing, installed = self.check_missing_packages(detected_imports)
        
        # 8. Instala faltantes
        if missing and auto_install:
            if self.uv_available:
                self.install_packages_uv(missing)
            else:
                self.install_packages_fallback(missing)
            
            # Atualiza lista de pacotes
            self.get_installed_packages()
        elif missing:
            print(f"\n{Colors.YELLOW}⚠ {len(missing)} pacote(s) faltando. Execute com --install para instalar.{Colors.RESET}")
        
        # 9. Gera arquivos
        if self.pyproject_file.exists():
            print(f"\n{Colors.BLUE}pyproject.toml já existe, atualizando requirements.txt{Colors.RESET}")
            self.generate_requirements_file(detected_imports)
        else:
            choice = input(f"\n{Colors.BOLD}Gerar pyproject.toml ou requirements.txt? (p/r/n): {Colors.RESET}").lower()
            if choice == 'p':
                self.generate_pyproject_toml(detected_imports)
            elif choice == 'r':
                self.generate_requirements_file(detected_imports)
        
        # 10. Resumo final
        self.print_section("📊 RESUMO")
        print(f"Total de pacotes: {len(detected_imports)}")
        print(f"Instalados: {len(installed)}")
        print(f"Faltavam: {len(missing)}")
        print(f"Log salvo em: {self.log_file}\n")
        
        print(f"{Colors.GREEN}✓ Processo concluído com sucesso!{Colors.RESET}\n")


def main():
    """Função principal"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Gerenciador inteligente de dependências com UV"
    )
    parser.add_argument(
        "--no-install",
        action="store_true",
        help="Apenas detecta, não instala"
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Mostra versão do UV"
    )
    
    args = parser.parse_args()
    
    if args.version:
        manager = UVDependencyManager()
        if manager.uv_available:
            print(f"UV versão: {manager.get_uv_version()}")
        else:
            print("UV não instalado")
        return
    
    manager = UVDependencyManager()
    manager.run(auto_install=not args.no_install)


if __name__ == "__main__":
    main()