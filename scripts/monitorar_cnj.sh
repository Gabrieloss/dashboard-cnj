#!/usr/bin/env bash
# Pode ser chamado pelo Agendador de Tarefas do Windows via wsl.exe.
set -euo pipefail
CNJ_PROJETO="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$CNJ_PROJETO/logs"
if [[ -x "$CNJ_PROJETO/.venv/bin/python" ]]; then
    CNJ_PYTHON="$CNJ_PROJETO/.venv/bin/python"
else
    CNJ_PYTHON="$(command -v python3)"
fi
exec "$CNJ_PYTHON" "$CNJ_PROJETO/atualizar_cnj.py" --aplicar >> "$CNJ_PROJETO/logs/atualizacao_cnj.log" 2>&1
