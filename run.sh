#!/usr/bin/env bash
# Start the LG webOS controller on loopback.
#
# Usage: ./run.sh [-p PORT] [-o]
#   -p PORT  port to listen on (default: 8080, or $LGTV_PORT)
#   -o       open the controller in a browser once it is up
set -euo pipefail

cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"

port="${LGTV_PORT:-8080}"
open_browser=false

usage() {
    sed -n '4,6p' "$0" | sed 's/^# \{0,1\}//'
}

while getopts ":p:oh" opt; do
    case "$opt" in
        p) port="$OPTARG" ;;
        o) open_browser=true ;;
        h) usage; exit 0 ;;
        :) echo "error: -$OPTARG needs a value" >&2; usage >&2; exit 2 ;;
        *) echo "error: unknown option -$OPTARG" >&2; usage >&2; exit 2 ;;
    esac
done

if ! [[ "$port" =~ ^[0-9]+$ ]] || ((port < 1 || port > 65535)); then
    echo "error: invalid port '$port'" >&2
    exit 2
fi

if ! command -v uv >/dev/null 2>&1; then
    echo "error: uv is not installed (https://docs.astral.sh/uv/)" >&2
    exit 1
fi

if [[ ! -f .env ]]; then
    echo "error: .env not found; run 'cp env.example .env' and fill in your TV's details" >&2
    exit 1
fi

uv sync --locked --quiet

url="http://127.0.0.1:${port}"
echo "LG webOS controller: ${url}  (Ctrl+C to stop)"

if $open_browser && command -v xdg-open >/dev/null 2>&1; then
    (sleep 2 && xdg-open "$url" >/dev/null 2>&1) &
fi

# Always bind to loopback: the app is not safe to expose on the LAN.
exec uv run --env-file .env flasgo run lgtv_controller.app:app --host 127.0.0.1 --port "$port"
