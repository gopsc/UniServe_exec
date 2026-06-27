#!/bin/bash
cd "$(dirname "$0")" || exit
source ./venv/bin/activate
echo "server on :5004"
exec python main.py 1>/dev/null
