#!/usr/bin/env bash
# ============================================================================
# HomeAgent launcher — one command to start the app.
#
#   ./run.sh                 # uses homeagent.toml (next to this script)
#   ./run.sh --config X      # extra args pass through to the app
#
# All runtime settings live in homeagent.toml. No environment variables.
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")"

# Prefer the virtualenvwrapper "chat" env (it has pymongo); fall back to
# the system python3. Override with:  PY=/path/to/python ./run.sh
if [[ -n "${PY:-}" ]]; then
    :
elif [[ -x "$HOME/.virtualenvs/chat/bin/python" ]]; then
    PY="$HOME/.virtualenvs/chat/bin/python"
else
    PY=python3
fi
command -v "$PY" >/dev/null 2>&1 || { echo "error: no suitable python found (set PY=...)" >&2; exit 1; }

# Python 3.11+ required (tomllib is stdlib there).
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || {
    echo "error: Python 3.11+ required (tomllib is stdlib)" >&2; exit 1
}

# pymongo is required for chat/message persistence.
if ! "$PY" -c 'import pymongo' 2>/dev/null; then
    echo "error: pymongo is not installed for: $PY" >&2
    echo "       (activate the 'chat' env:  workon chat   —   or:  $PY -m pip install pymongo)" >&2
    exit 1
fi

# Friendly warning (non-fatal) if Ollama isn't reachable.
# Host is read from the config file, not from the environment.
# Honor --config/-c if the caller passes one.
CFG_PATH="homeagent.toml"
prev=""
for arg in "$@"; do
    if [[ "$prev" == "--config" || "$prev" == "-c" ]]; then CFG_PATH="$arg"; fi
    prev="$arg"
done
OLLAMA_HOST="$("$PY" -c '
import sys, tomllib
with open(sys.argv[1], "rb") as f:
    cfg = tomllib.load(f)
h = cfg["ollama"]["host"]
print(h if h.startswith(("http://", "https://")) else "http://" + h)
' "$CFG_PATH")"
if ! curl -sf --max-time 2 "${OLLAMA_HOST}/api/version" >/dev/null 2>&1; then
    echo "warning: Ollama does not seem to be running at ${OLLAMA_HOST}" >&2
    echo "         (try:  ollama serve)" >&2
    echo >&2
fi

exec "$PY" -m homeagent.main "$@"
