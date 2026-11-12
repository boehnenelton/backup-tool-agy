#!/data/data/com.termux/files/usr/bin/env python3
"""
# Name:          server_manager.py
# Description:   Async background server lifecycle manager for Loaded Chamber Flask Web App
# Version:       10400
# Date Created:  2026-11-12
# Author Credit: Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
# License:       PolyForm Noncommercial License 1.0.0 (PolyForm-Noncommercial-1.0.0)
# RELATIONAL_ID: ed36bda3-5342-4636-bca1-30c58a7c08c8
"""

from __future__ import annotations
import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_PATH: Path = Path(__file__).resolve()
APP_DIR: Path = SCRIPT_PATH.parent
APP_PY: Path = APP_DIR / "app.py"
PID_FILE: Path = APP_DIR / ".server.pid"
LOG_FILE: Path = APP_DIR / "server.log"

PYTHON: str = sys.executable

DEFAULT_PORT: int = 5080
DEFAULT_HOST: str = "127.0.0.1"

# ANSI palette (49-character mobile portrait ceiling)
RED = "\033[38;5;196m"
WHITE = "\033[1;37m"
DIM = "\033[90m"
GREEN = "\033[1;32m"
CYAN = "\033[36m"
RESET = "\033[0m"
DIV = "=" * 49
SUB = "-" * 49


def print_ok(msg: str) -> None:
    print(f"{WHITE}[✓] {msg.upper()}{RESET}")


def print_fail(msg: str) -> None:
    print(f"{RED}[X] {msg.lower()}{RESET}", file=sys.stderr)


def read_pid() -> int | None:
    if PID_FILE.exists():
        try:
            return int(PID_FILE.read_text().strip())
        except ValueError:
            pass
    return None


def is_running(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def start_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> bool:
    pid = read_pid()
    if is_running(pid):
        print_fail(f"server already running on pid {pid}")
        return True

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log_fh = open(LOG_FILE, "a", encoding="utf-8")

    proc = subprocess.Popen(
        [PYTHON, str(APP_PY), "--host", host, "--port", str(port)],
        stdout=log_fh,
        stderr=log_fh,
        start_new_session=True,
    )
    PID_FILE.write_text(str(proc.pid))
    time.sleep(1.2)

    url = f"http://localhost:{port}"
    print_ok(f"SERVER STARTED (PID {proc.pid})")
    print(f" {WHITE}URL:{RESET} {CYAN}{url}{RESET}")

    # Copy URL to Termux clipboard
    try:
        subprocess.run(
            ["termux-clipboard-set", url],
            timeout=3, check=False, capture_output=True,
        )
        print_ok("URL COPIED TO CLIPBOARD")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Launch Chrome directly via Android Activity Manager
    try:
        subprocess.run(
            ["am", "start", "-n",
             "com.android.chrome/com.google.android.apps.chrome.Main",
             "-d", url],
            timeout=4, check=False, capture_output=True,
        )
        print_ok("CHROME LAUNCHED VIA ACTIVITY MANAGER")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        try:
            subprocess.run(["termux-open-url", url], timeout=4, check=False, capture_output=True)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            try:
                subprocess.run(["xdg-open", url], timeout=4, check=False, capture_output=True)
            except Exception:
                pass
    return True


def stop_server() -> bool:
    pid = read_pid()
    if not is_running(pid):
        print_fail("no server running")
        PID_FILE.unlink(missing_ok=True)
        return True
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
        time.sleep(0.6)
        if is_running(pid):
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        PID_FILE.unlink(missing_ok=True)
        print_ok("SERVER STOPPED")
        return True
    except Exception as exc:
        print_fail(f"stop failed: {exc}")
        return False


def restart_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> bool:
    stop_server()
    time.sleep(0.5)
    return start_server(host, port)


def status_banner(port: int = DEFAULT_PORT) -> None:
    pid = read_pid()
    running = is_running(pid)
    state = f"{GREEN}ONLINE{RESET}" if running else f"{RED}STOPPED{RESET}"
    pid_str = str(pid) if running else "—"
    url = f"http://localhost:{port}" if running else "—"
    print(f"{DIM}{DIV}{RESET}")
    title = "LOADED CHAMBER WEB SERVER"
    pad = max(0, (49 - len(title)) // 2)
    print(f"{' ' * pad}{RED}{title}{RESET}")
    print(f"{DIM}{SUB}{RESET}")
    print(f" {WHITE}Status:{RESET}  {state}")
    print(f" {WHITE}PID:{RESET}     {CYAN}{pid_str}{RESET}")
    print(f" {WHITE}URL:{RESET}     {CYAN}{url}{RESET}")
    print(f" {WHITE}Log:{RESET}     {DIM}{LOG_FILE.name}{RESET}")
    print(f"{DIM}{DIV}{RESET}")


def tail_log(lines: int = 30) -> None:
    if not LOG_FILE.exists():
        print_fail("no server.log found")
        return
    all_lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    print(f"{DIM}{SUB}{RESET}")
    print(f" {RED}SERVER LOG TAIL (LAST {min(lines, len(all_lines))} LINES):{RESET}")
    print(f"{DIM}{SUB}{RESET}")
    for line in all_lines[-lines:]:
        print(f" {DIM}{line[:47]}{RESET}")
    print(f"{DIM}{SUB}{RESET}")


def tui_menu(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> int:
    while True:
        sys.stdout.write("\033[2J\033[H")
        status_banner(port)
        print(f" {RED}[1]{RESET} {WHITE}Start Server & Launch Chrome{RESET}")
        print(f" {RED}[2]{RESET} {WHITE}Stop Server{RESET}")
        print(f" {RED}[3]{RESET} {WHITE}Restart Server{RESET}")
        print(f" {RED}[4]{RESET} {WHITE}Tail Server Log{RESET}")
        print(f" {RED}[5]{RESET} {WHITE}Open Browser URL{RESET}")
        print(f" {RED}[Q]{RESET} {WHITE}Exit Server Manager{RESET}")
        print(f"{DIM}{DIV}{RESET}")

        try:
            choice = input(f" {RED}Action (Enter choice) > {RESET}").strip().upper()
        except (KeyboardInterrupt, EOFError):
            print("\n")
            return 0

        if choice == "Q":
            return 0
        elif choice == "1":
            start_server(host, port)
            input(f"\n {DIM}Press [Enter] to continue...{RESET}")
        elif choice == "2":
            stop_server()
            input(f"\n {DIM}Press [Enter] to continue...{RESET}")
        elif choice == "3":
            restart_server(host, port)
            input(f"\n {DIM}Press [Enter] to continue...{RESET}")
        elif choice == "4":
            tail_log(35)
            input(f"\n {DIM}Press [Enter] to continue...{RESET}")
        elif choice == "5":
            url = f"http://localhost:{port}"
            subprocess.run(
                ["am", "start", "-n", "com.android.chrome/com.google.android.apps.chrome.Main", "-d", url],
                timeout=4, check=False, capture_output=True,
            )
            print_ok("OPENED CHROME")
            input(f"\n {DIM}Press [Enter] to continue...{RESET}")
        else:
            print_fail(f"unknown command: '{choice}'")
            input(f"\n {DIM}Press [Enter] to continue...{RESET}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Loaded Chamber Flask Server Manager")
    parser.add_argument("action", nargs="?", choices=["start", "stop", "restart", "status", "log", "menu"], default="menu")
    parser.add_argument("--host", type=str, default=DEFAULT_HOST, help="Host to bind")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to listen on")
    args = parser.parse_args()

    if args.action == "start":
        start_server(args.host, args.port)
        return 0
    elif args.action == "stop":
        stop_server()
        return 0
    elif args.action == "restart":
        restart_server(args.host, args.port)
        return 0
    elif args.action == "status":
        status_banner(args.port)
        return 0
    elif args.action == "log":
        tail_log(40)
        return 0
    else:
        return tui_menu(args.host, args.port)


if __name__ == "__main__":
    sys.exit(main())
