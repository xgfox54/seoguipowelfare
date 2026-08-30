from __future__ import annotations

import ctypes
import json
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request

import uvicorn
import webview

from welfare_runtime import knowledge_base_root
from welfare_web import create_app

HOST = "127.0.0.1"
PORT = 8765
BASE_URL = f"http://{HOST}:{PORT}"


class DesktopApi:
    def __init__(self, server: uvicorn.Server) -> None:
        self.server = server
        self.window: webview.Window | None = None

    def close_app(self) -> bool:
        self.server.should_exit = True
        if self.window is not None:
            self.window.destroy()
        return True


def _message_box(message: str, title: str = "복지업무 비서") -> None:
    ctypes.windll.user32.MessageBoxW(None, message, title, 0x40)


def _app_is_running() -> bool:
    try:
        with urllib.request.urlopen(f"{BASE_URL}/api/status", timeout=1.5) as response:
            if response.status != 200:
                return False
            payload = json.loads(response.read().decode("utf-8"))
            return "source_documents" in payload and "search_sections" in payload
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return False


def _port_is_busy() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((HOST, PORT)) == 0


def _ollama_is_running() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=1.5) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError):
        return False


def _try_start_ollama() -> None:
    if _ollama_is_running():
        return
    ollama = shutil.which("ollama")
    if not ollama:
        return
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.Popen(
            [ollama, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
    except OSError:
        return
    for _ in range(20):
        if _ollama_is_running():
            return
        time.sleep(0.25)


def _show_app_window(server: uvicorn.Server) -> None:
    api = DesktopApi(server)
    window = webview.create_window(
        "개인용 복지업무 비서",
        BASE_URL,
        width=1280,
        height=900,
        min_size=(960, 700),
        text_select=True,
        js_api=api,
    )
    api.window = window

    def close_server() -> None:
        server.should_exit = True

    window.events.closed += close_server
    webview.start(gui="edgechromium", private_mode=True)


def main() -> int:
    if _app_is_running():
        _message_box("복지업무 비서가 이미 실행 중입니다.")
        return 0
    if _port_is_busy():
        _message_box(
            f"포트 {PORT}을 다른 프로그램이 사용 중입니다.\n"
            "해당 프로그램을 종료한 뒤 다시 실행해 주세요."
        )
        return 1

    _try_start_ollama()
    server_ref: dict[str, uvicorn.Server] = {}

    def request_shutdown() -> None:
        server = server_ref.get("server")
        if server is not None:
            server.should_exit = True

    app = create_app(knowledge_base_root(), shutdowner=request_shutdown)
    config = uvicorn.Config(
        app,
        host=HOST,
        port=PORT,
        log_level="warning",
        access_log=False,
        log_config=None,
    )
    server = uvicorn.Server(config)
    server_ref["server"] = server
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()
    for _ in range(100):
        if _app_is_running():
            break
        if not server_thread.is_alive():
            _message_box("로컬 서버를 시작하지 못했습니다.")
            return 1
        time.sleep(0.1)
    else:
        server.should_exit = True
        _message_box("로컬 서버 시작 시간이 초과되었습니다.")
        return 1

    _show_app_window(server)
    server.should_exit = True
    server_thread.join(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
