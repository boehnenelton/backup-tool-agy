#!/data/data/com.termux/files/usr/bin/env bash
# Runner script for AGY Backup Tool
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "${SCRIPT_DIR}/backup_tool_agy.py" "$@"
