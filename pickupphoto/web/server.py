"""Serve the desktop UI over an authenticated loopback-only connection."""

from __future__ import annotations

import json
import logging
import re
import secrets
import subprocess
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Lock, Thread
from urllib.parse import urlsplit

from pickupphoto import __version__
from pickupphoto.output.exporter import ConflictAction, FilterMode
from pickupphoto.web.library import Library

STATIC = Path(__file__).with_name("static")
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/icon.png": ("icon.png", "image/png"),
}
IMAGE_PATH = re.compile(r"/api/image/([0-9a-f]+)/([0-9]+)/(thumbnail|preview|full)")


class LocalApp(ThreadingHTTPServer):
    def __init__(self, port: int = 0, initial_folder: Path | None = None):
        super().__init__(("127.0.0.1", port), Request)
        self.host = f"127.0.0.1:{self.server_port}"
        self.origin = f"http://{self.host}"
        self.cookie = f"pickupphoto_{self.server_port}"
        self.token = secrets.token_urlsafe(32)
        self.ticket = secrets.token_urlsafe(32)
        self.lock = Lock()
        self.stop = Event()
        self.job = None
        self.worker = None
        self.library = Library(initial_folder) if initial_folder is not None else None
        self.library_id = secrets.token_hex(8)
        self.recent = [str(initial_folder)] if initial_folder is not None else []
        self.folder_picker = choose_folder
        self.readers = 0
        self.retired = []

    def start_job(self, kind, task, library_id=None):
        with self.lock:
            if library_id is not None:
                self.get_library(library_id)
            if self.stop.is_set() or (self.job and self.job["running"]):
                raise RequestError(HTTPStatus.CONFLICT, "已有工作進行中。")
            self.job = {"kind": kind, "running": True, "done": 0, "total": 0}
            self.worker = Thread(target=self._run_job, args=(task,), daemon=True)
            self.worker.start()

    def _run_job(self, task):
        try:
            result = task(self.progress)
        except Exception as error:
            logging.exception("Background job failed")
            result = {"error": str(error)}
        with self.lock:
            self.job.update(running=False, result=result)

    def progress(self, done, total):
        with self.lock:
            self.job.update(done=done, total=total)

    def open_folder(self, folder: Path):
        library = Library(folder)
        with self.lock:
            previous = self.library
            self.library = library
            self.library_id = secrets.token_hex(8)
            path = str(folder)
            self.recent = [path, *[item for item in self.recent if item != path]][:8]
            if previous:
                self.retired.append(previous)
            self._close_retired()

    def _close_retired(self):
        if not self.readers:
            for library in self.retired:
                library.close()
            self.retired.clear()

    def get_library(self, library_id):
        if not self.library or library_id != self.library_id:
            raise RequestError(HTTPStatus.CONFLICT, "資料夾已變更，請重新載入。")
        return self.library

    def server_close(self):
        self.stop.set()
        super().server_close()
        if self.worker:
            self.worker.join()
        with self.lock:
            if self.library:
                self.retired.append(self.library)
                self.library = None
            self._close_retired()


class RequestError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def choose_folder() -> str | None:
    if sys.platform != "darwin":
        raise ValueError("請輸入本機資料夾路徑。")
    result = subprocess.run(
        ["/usr/bin/osascript", "-e", 'POSIX path of (choose folder with prompt "PickUpPhoto")'],
        text=True, capture_output=True, timeout=300,
    )
    if result.returncode:
        if "(-128)" in result.stderr:
            return None
        raise ValueError(result.stderr.strip() or "無法開啟資料夾選擇器。")
    return result.stdout.removesuffix("\n")


def folder_path(value) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("請輸入資料夾路徑。")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError("請輸入完整的資料夾路徑。")
    return path.resolve()


def stars_value(value) -> int:
    if type(value) is not int or not 0 <= value <= 5:
        raise ValueError("星等必須介於 0 至 5。")
    return value


class Request(BaseHTTPRequestHandler):
    server: LocalApp

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, *_args):
        pass

    def send_content(self, status, body=b"", content_type="application/json", headers=()):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, data, status=HTTPStatus.OK):
        self.send_content(status, json.dumps(data, ensure_ascii=False).encode())

    def handle_request(self, write=False):
        try:
            if self.headers.get_all("Host") != [self.server.host]:
                raise RequestError(HTTPStatus.FORBIDDEN, "Invalid host.")
            path = urlsplit(self.path).path
            if not write and path.startswith("/start/"):
                self.start_session(path)
                return
            if not write and path in ASSETS:
                filename, content_type = ASSETS[path]
                self.send_content(HTTPStatus.OK, (STATIC / filename).read_bytes(), content_type)
                return
            cookies = [cookie.strip() for cookie in self.headers.get("Cookie", "").split(";")]
            if (f"{self.server.cookie}={self.server.token}" not in cookies
                    or self.headers.get("Sec-Fetch-Site") == "cross-site"):
                raise RequestError(HTTPStatus.FORBIDDEN, "請從 PickUpPhoto.app 重新開啟介面。")
            if write:
                result = self.write_api(path, self.request_data())
                self.send_json(result)
                if result.get("quitting"):
                    Thread(target=self.server.shutdown, daemon=True).start()
            else:
                self.read_api(path)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except RequestError as error:
            self.send_json({"error": str(error)}, error.status)
        except (ValueError, KeyError, IndexError, OSError, subprocess.TimeoutExpired) as error:
            self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        except Exception as error:
            logging.exception("Local request failed")
            self.send_json({"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_GET(self):
        self.handle_request()

    def do_POST(self):
        self.handle_request(write=True)

    def start_session(self, path):
        if path != f"/start/{self.server.ticket}":
            raise RequestError(HTTPStatus.NOT_FOUND, "找不到頁面。")
        self.send_content(HTTPStatus.SEE_OTHER, headers=[
            ("Location", "/"),
            ("Set-Cookie", f"{self.server.cookie}={self.server.token}; Path=/; HttpOnly; SameSite=Strict"),
        ])

    def request_data(self):
        if (self.headers.get("Origin") != self.server.origin
                or self.headers.get("X-PickUpPhoto") != "1"
                or self.headers.get_content_type() != "application/json"):
            raise RequestError(HTTPStatus.FORBIDDEN, "Invalid request origin.")
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 8192:
            raise ValueError("Invalid request length.")
        data = json.loads(self.rfile.read(length))
        if not isinstance(data, dict):
            raise ValueError("Invalid request body.")
        return data

    def read_api(self, path):
        if path == "/api/status":
            with self.server.lock:
                self.send_json({"job": self.server.job})
        elif path == "/api/library":
            with self.server.lock:
                library = self.server.library
                self.send_json({
                    "version": __version__,
                    "id": self.server.library_id,
                    "folder": str(library.folder) if library else None,
                    "photos": library.listing() if library else [],
                    "recent": self.server.recent,
                })
        elif match := IMAGE_PATH.fullmatch(path):
            library_id, index, kind = match.groups()
            with self.server.lock:
                library = self.server.get_library(library_id)
                self.server.readers += 1
            try:
                image = library.image(int(index), kind)
            finally:
                with self.server.lock:
                    self.server.readers -= 1
                    self.server._close_retired()
            self.send_content(HTTPStatus.OK, image, "image/jpeg")
        else:
            raise RequestError(HTTPStatus.NOT_FOUND, "找不到頁面。")

    def write_api(self, path, data):
        if path == "/api/choose":
            return {"folder": self.server.folder_picker()}
        if path == "/api/open":
            folder = folder_path(data.get("folder"))
            self.server.start_job("open", lambda _progress: self.server.open_folder(folder))
            return {}
        if path == "/api/quit":
            with self.server.lock:
                if self.server.job and self.server.job["running"]:
                    raise RequestError(HTTPStatus.CONFLICT, "請等待目前的工作完成。")
                self.server.stop.set()
            return {"quitting": True}
        with self.server.lock:
            library = self.server.get_library(data.get("id"))
            if path == "/api/rate":
                index = data.get("photo")
                if type(index) is not int or not 0 <= index < len(library.photos):
                    raise ValueError("找不到照片。")
                library.rate(index, stars_value(data.get("stars")))
                return {}
        if path == "/api/analyze":
            self.server.start_job(
                "analyze", lambda progress: library.analyze(progress, self.server.stop), data["id"],
            )
        elif path == "/api/export":
            folder = folder_path(data.get("folder"))
            mode = FilterMode(data.get("mode"))
            stars = stars_value(data.get("stars"))
            conflict = ConflictAction(data.get("conflict"))
            self.server.start_job("export", lambda progress: library.export(
                folder, mode, stars, conflict, progress,
            ), data["id"])
        else:
            raise RequestError(HTTPStatus.NOT_FOUND, "找不到頁面。")
        return {}
