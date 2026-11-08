#!/usr/bin/env bash
# Imprime a seção do CHANGELOG.md de uma versão (sem o título "## [X.Y.Z]").
# Falha se a seção não existir ou estiver vazia: toda release precisa dela.
#
#   bash scripts/changelog-section.sh v1.2.0 [CHANGELOG.md]
set -euo pipefail

tag="${1:?uso: changelog-section.sh <tag> [arquivo]}"
arquivo="${2:-CHANGELOG.md}"
versao="${tag#v}"

if ! [[ "$versao" =~ ^[0-9]+\.[0-9]+\.[0-9]+([-+][0-9A-Za-z.-]+)?$ ]]; then
  echo "::error ::tag fora do padrão vX.Y.Z: ${tag}" >&2
  exit 1
fi

secao=$(awk -v v="$versao" '
  index($0, "## [" v "]") == 1 { dentro = 1; next }
  dentro && /^## \[/ { exit }
  dentro && /^\[[^]]+\]: / { exit }
  dentro { print }
' "$arquivo")

if [ -z "$(printf '%s' "$secao" | tr -d '[:space:]')" ]; then
  echo "::error ::${arquivo} não tem a seção \"## [${versao}]\": escreva as mudanças da release antes da tag." >&2
  exit 1
fi

printf '%s\n' "$secao" | sed -e '/./,$!d'
