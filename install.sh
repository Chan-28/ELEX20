#!/bin/sh
# Atalho para quem clonou o repositório (Linux e macOS): roda o instalador com o Python do sistema.
# Sem Python? Baixe o executável pronto na página de Releases.
cd "$(dirname "$0")" || exit 1
for py in python3 python; do
  if command -v "$py" >/dev/null 2>&1; then
    exec "$py" installer/elex_installer.py "$@"
  fi
done
echo "Python 3 não encontrado. Instale em https://www.python.org/downloads/ ou use o executável da página de Releases." >&2
exit 1
