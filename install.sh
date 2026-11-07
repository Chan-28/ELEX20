#!/bin/sh
# Atalho para quem clonou o repositório (Linux e macOS). Instala a biblioteca da interface em um
# ambiente isolado; se não conseguir, o instalador segue com perguntas em texto simples.
cd "$(dirname "$0")" || exit 1
TEXTUAL="textual==8.2.8"
VENV=.installer-venv
for py in python3 python; do
  command -v "$py" >/dev/null 2>&1 || continue
  if [ -x "$VENV/bin/python" ] || "$py" -m venv "$VENV" >/dev/null 2>&1; then
    if "$VENV/bin/python" -m pip install --quiet --disable-pip-version-check "$TEXTUAL" >/dev/null 2>&1; then
      exec "$VENV/bin/python" installer/elex_installer.py "$@"
    fi
  fi
  echo "Could not set up the full-screen interface; using plain text prompts." >&2
  exec "$py" installer/elex_installer.py "$@"
done
echo "Python 3 not found. Install it from https://www.python.org/downloads/ or use the executable from the Releases page." >&2
exit 1
