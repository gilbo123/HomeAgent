#!/usr/bin/env bash
# ============================================================================
# HomeAgent launcher — one command to start the app.
#
#   ./run.sh                # starts the app
#   ./run.sh <extra-args>   # extra args pass through to the app
#
# All runtime settings are read by homeagent/config.py from the tracked
# .env template and the untracked prod.env secrets file (see README).
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

# Python 3.11+ required (str | None unions used across the package).
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || {
    echo "error: Python 3.11+ required" >&2; exit 1
}

# pymongo is required for chat/message persistence.
if ! "$PY" -c 'import pymongo' 2>/dev/null; then
    echo "error: pymongo is not installed for: $PY" >&2
    echo "       (activate the 'chat' env:  workon chat   —   or:  $PY -m pip install pymongo)" >&2
    exit 1
fi

# Friendly warning (non-fatal) if Ollama isn't reachable.
# Host comes from homeagent/config.py (which itself reads .env / prod.env).
OLLAMA_HOST="$("$PY" -c '
import sys
sys.path.insert(0, ".")
from homeagent.config import CONFIG
h = CONFIG.ollama_host
print(h if h.startswith(("http://", "https://")) else "http://" + h)
')" || {
    echo "warning: could not import homeagent.config — skipping Ollama check" >&2
    OLLAMA_HOST=""
}

if [[ -n "${OLLAMA_HOST:-}" ]] && ! curl -sf --max-time 2 "${OLLAMA_HOST}/api/version" >/dev/null 2>&1; then
    echo "warning: Ollama does not seem to be running at ${OLLAMA_HOST}" >&2
    echo "         (try:  ollama serve)" >&2
    echo >&2
fi

exec "$PY" -m homeagent.main "$@"
