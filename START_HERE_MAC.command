#!/bin/bash
cd "$(dirname "$0")" || exit 1
printf 'STREETWISE · NYC\nOpen http://127.0.0.1:8080 in your browser.\nKeep this Terminal window open; press Control-C to stop.\n'
python3 server.py
