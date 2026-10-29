"""
Testes unitários para dependencies.py
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Adiciona a raiz do projeto ao path para importar dependencies
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dependencies import UVDependencyManager


@pytest.fixture
def mgr(tmp_path, monkeypatch):
    """Manager apontando para um diretório temporário sem UV real."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test"\nversion = "0.1.0"\n'
        'requires-python = ">=3.11"\ndependencies = ["numpy>=1.0", "pandas>=1.0"]\n',
        encoding="utf-8",
    )
    m = UVDependencyManager()
    m.uv_available = True
    return m


# ── _check_uv ────────────────────────────────────────────────────────────────

def test_check_uv_returns_true_when_present():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        mgr = UVDependencyManager.__new__(UVDependencyManager)
        assert mgr._check_uv() is True


def test_check_uv_returns_false_when_absent():
    with patch("subprocess.run", side_effect=FileNotFoundError):
        mgr = UVDependencyManager.__new__(UVDependencyManager)
        assert mgr._check_uv() is False


def test_check_uv_returns_false_on_nonzero():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1)
        mgr = UVDependencyManager.__new__(UVDependencyManager)
        assert mgr._check_uv() is False


# ── read_pyproject_toml ───────────────────────────────────────────────────────

def test_read_pyproject_toml_returns_dependencies(mgr):
    deps = mgr.read_pyproject_toml()
    assert "numpy" in deps
    assert "pandas" in deps


def test_read_pyproject_toml_empty_when_no_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    m = UVDependencyManager.__new__(UVDependencyManager)
    m.project_root = tmp_path
    m.pyproject_file = tmp_path / "pyproject.toml"
    m.log_file = tmp_path / "dep.log"
    m.installed_packages = {}
    deps = m.read_pyproject_toml()
    assert deps == set()


def test_read_pyproject_toml_strips_version_specifiers(mgr):
    deps = mgr.read_pyproject_toml()
    for dep in deps:
        assert ">=" not in dep
        assert "==" not in dep
        assert "<" not in dep


def test_read_pyproject_toml_ignores_platform_markers(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "t"\nversion = "0.1.0"\n'
        'dependencies = ["uvloop>=0.20; sys_platform != \'win32\'"]\n',
        encoding="utf-8",
    )
    m = UVDependencyManager()
    m.uv_available = True
    deps = m.read_pyproject_toml()
    assert "uvloop" in deps


# ── _pkg_name (mapeamento de imports) ────────────────────────────────────────

def test_pkg_name_maps_cv2():
    m = UVDependencyManager.__new__(UVDependencyManager)
    assert m._pkg_name("cv2") == "opencv-python"


def test_pkg_name_maps_pil():
    m = UVDependencyManager.__new__(UVDependencyManager)
    assert m._pkg_name("PIL") == "pillow"


def test_pkg_name_passthrough_unknown():
    m = UVDependencyManager.__new__(UVDependencyManager)
    assert m._pkg_name("numpy") == "numpy"


# ── check_missing_packages ────────────────────────────────────────────────────

def test_check_missing_packages_installed(mgr):
    mgr.installed_packages = {"numpy": "1.26.0", "pandas": "2.0.0"}
    missing, installed = mgr.check_missing_packages({"numpy", "pandas"})
    assert missing == []
    assert set(installed) == {"numpy", "pandas"}


def test_check_missing_packages_missing(mgr):
    mgr.installed_packages = {}
    missing, installed = mgr.check_missing_packages({"numpy"})
    assert "numpy" in missing
    assert installed == []


def test_check_missing_packages_partial(mgr):
    mgr.installed_packages = {"numpy": "1.0"}
    missing, installed = mgr.check_missing_packages({"numpy", "pandas"})
    assert "pandas" in missing
    assert "numpy" in installed


# ── detect_python_files ───────────────────────────────────────────────────────

def test_detect_python_files_finds_imports(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "t"\nversion = "0.1.0"\ndependencies = []\n',
        encoding="utf-8",
    )
    (tmp_path / "script.py").write_text("import numpy\nfrom pandas import DataFrame\n")
    m = UVDependencyManager()
    m.uv_available = True
    imports, _ = m.detect_python_files()
    assert "numpy" in imports
    assert "pandas" in imports


def test_detect_python_files_excludes_stdlib(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "t"\nversion = "0.1.0"\ndependencies = []\n',
        encoding="utf-8",
    )
    (tmp_path / "s.py").write_text("import os\nimport sys\n")
    m = UVDependencyManager()
    m.uv_available = True
    imports, stdlib = m.detect_python_files()
    assert "os" not in imports
    assert "sys" not in imports


def test_detect_python_files_excludes_venv(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "t"\nversion = "0.1.0"\ndependencies = []\n',
        encoding="utf-8",
    )
    venv_pkg = tmp_path / ".venv" / "lib"
    venv_pkg.mkdir(parents=True)
    (venv_pkg / "hidden.py").write_text("import secretlib\n")
    m = UVDependencyManager()
    m.uv_available = True
    imports, _ = m.detect_python_files()
    assert "secretlib" not in imports


# ── get_installed_packages ────────────────────────────────────────────────────

def test_get_installed_packages_parses_json(mgr):
    fake_output = json.dumps([{"name": "numpy", "version": "1.26.0"}])
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=fake_output)
        ok = mgr.get_installed_packages()
    assert ok is True
    assert mgr.installed_packages.get("numpy") == "1.26.0"


def test_get_installed_packages_returns_false_on_error(mgr):
    with patch("subprocess.run", side_effect=Exception("fail")):
        ok = mgr.get_installed_packages()
    assert ok is False


# ── install_packages ──────────────────────────────────────────────────────────

def test_install_packages_calls_uv(mgr):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        ok = mgr.install_packages(["numpy"])
    assert ok is True
    called_cmd = mock_run.call_args[0][0]
    assert "uv" in called_cmd
    assert "numpy" in called_cmd


def test_install_packages_empty_list(mgr):
    with patch("subprocess.run") as mock_run:
        ok = mgr.install_packages([])
    assert ok is True
    mock_run.assert_not_called()


def test_install_packages_fails_without_uv(mgr):
    mgr.uv_available = False
    ok = mgr.install_packages(["numpy"])
    assert ok is False


# ── check_lock ────────────────────────────────────────────────────────────────

def test_check_lock_returns_true_when_consistent(mgr):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        ok = mgr.check_lock()
    assert ok is True


def test_check_lock_returns_false_when_stale(mgr):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="outdated")
        ok = mgr.check_lock()
    assert ok is False


# ── sync ──────────────────────────────────────────────────────────────────────

def test_sync_calls_uv_sync_frozen(mgr):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        ok = mgr.sync()
    assert ok is True
    called_cmd = mock_run.call_args[0][0]
    assert called_cmd == ["uv", "sync", "--frozen"]


def test_sync_fails_without_uv(mgr):
    mgr.uv_available = False
    ok = mgr.sync()
    assert ok is False
