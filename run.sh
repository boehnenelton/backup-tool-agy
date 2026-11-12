#!/data/data/com.termux/files/usr/bin/env bash
# Name:          run.sh
# Description:   Universal dispatcher for backup, chamber, and Flask web server
# Version:       10400
# Date Created:  2026-11-12
# Author Credit: Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
# License:       PolyForm Noncommercial License 1.0.0 (PolyForm-Noncommercial-1.0.0)
# RELATIONAL_ID: ed36bda3-5342-4636-bca1-30c58a7c08c8

SCRIPT_DIR="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"

if [ "$1" = "web" ] || [ "$1" = "server" ]; then
    shift
    exec python3 "${SCRIPT_DIR}/server_manager.py" "$@"
elif [ "$1" = "chamber" ] || [ "$1" = "slot" ] || [ "$1" = "slots" ]; then
    shift
    exec python3 "${SCRIPT_DIR}/universal_snapshot_engine.py" "$@"
else
    exec python3 "${SCRIPT_DIR}/backup_tool_agy.py" "$@"
fi
