#!/bin/bash
cd "$(dirname "$0")" || exit 1
# server.py needs Python 3.11+ (hashlib.file_digest). macOS's built-in python3 is usually 3.9,
# so use the newest installed python3.x that is new enough.
PY=""
for c in python3.14 python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  printf 'STROLLANE needs Python 3.11 or newer (found: %s).\nInstall it from https://www.python.org/downloads/ or with: brew install python@3.12\nThen run this again.\n' "$(python3 --version 2>&1)"
  read -r -p 'Press Return to close.' _
  exit 1
fi
printf 'STROLLANE · NYC (%s)\nOpen http://127.0.0.1:%s in your browser.\nKeep this Terminal window open; press Control-C to stop.\n' "$("$PY" --version 2>&1)" "${PORT:-8080}"
exec "$PY" server.py
