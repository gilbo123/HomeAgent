#!/usr/bin/env bash
# ============================================================================
# HomeAgent launcher — one command to start the app.
#
#   ./run.sh                # starts the app
#   ./run.sh <extra-args>   # extra args pass through to the app
#
# Dependencies are managed by uv (pyproject.toml + uv.lock); the first run
# creates .venv automatically. All runtime settings are read by
# homeagent/config.py from the tracked .env template and the untracked
# prod.env secrets file (see README).
#
# Without uv, point PY at a Python 3.11+ that has pymongo:
#   PY=/path/to/python ./run.sh
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")"

# systemd and cron start with a minimal PATH that lacks the per-user install
# locations, so look there too.
UV="$(command -v uv 2>/dev/null || true)"
for candidate in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv" /usr/local/bin/uv \
                 /opt/homebrew/bin/uv /snap/bin/uv; do
    [[ -z "$UV" && -x "$candidate" ]] && UV="$candidate"
done

if [[ -n "${PY:-}" ]]; then
    RUN=("$PY")
elif [[ -n "$UV" ]]; then
    RUN=("$UV" run --quiet python)
else
    echo "error: uv not found (PATH=$PATH) — install it (https://docs.astral.sh/uv/) or set PY=..." >&2
    exit 1
fi

"${RUN[@]}" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || {
    echo "error: Python 3.11+ required" >&2; exit 1
}
"${RUN[@]}" -c 'import pymongo' 2>/dev/null || {
    echo "error: pymongo is not installed (run: uv sync)" >&2; exit 1
}

# Friendly warning (non-fatal) if Ollama isn't reachable.
OLLAMA_HOST="$("${RUN[@]}" -c '
from homeagent.config import CONFIG
print(CONFIG.ollama_host)
')" || {
    echo "warning: could not import homeagent.config — skipping Ollama check" >&2
    OLLAMA_HOST=""
}

if [[ -n "${OLLAMA_HOST:-}" ]] && ! curl -sf --max-time 2 "${OLLAMA_HOST}/api/version" >/dev/null 2>&1; then
    echo "warning: Ollama does not seem to be running at ${OLLAMA_HOST}" >&2
    echo "         (try:  ollama serve)" >&2
    echo >&2
fi

exec "${RUN[@]}" -m homeagent.main "$@"
