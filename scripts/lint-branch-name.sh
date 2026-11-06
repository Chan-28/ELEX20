#!/bin/sh
# Confere o nome da branch: <tipo>/<descricao-em-kebab-case>, com os tipos do commitlint.
# Uso: sh scripts/lint-branch-name.sh [branch]; sem argumento, confere a branch atual.
# Valem também main, as branches do Dependabot e claude/, criadas pelo app.
nome="${1:-$(git symbolic-ref --quiet --short HEAD)}"
[ -n "$nome" ] || exit 0 # HEAD destacado: não há branch para conferir

tipos='feat|fix|docs|refactor|test|chore|ci|build|perf|style|revert|claude'
if printf '%s\n' "$nome" | grep -Eq "^(main|dependabot/.+|($tipos)/[a-z0-9]+(-[a-z0-9]+)*)$"; then
    exit 0
fi

echo "Nome de branch inválido: $nome" >&2
echo "Use <tipo>/<descricao-em-kebab-case>, por exemplo fix/dataset-author-split." >&2
echo "Tipos: $(printf "%s" "$tipos" | tr "|" " ")" >&2
exit 1
