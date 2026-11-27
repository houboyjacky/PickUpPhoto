"""Launch the packaged executable and verify the served application assets."""

import sys
import tempfile
import time
from http.cookiejar import CookieJar
from pathlib import Path
from socket import socket
from subprocess import Popen, TimeoutExpired
from urllib.error import URLError
from urllib.request import HTTPCookieProcessor, build_opener

from pickupphoto import __version__


def verify(binary: Path):
    with socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        port = candidate.getsockname()[1]
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    origin = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryFile() as log:
        app = Popen([str(binary), "--no-browser", "--port", str(port)], stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 45
            while app.poll() is None and time.monotonic() < deadline:
                try:
                    with opener.open(origin, timeout=1) as response:
                        assert b"PickUpPhoto" in response.read()
                    for path in ("/app.js", "/app.css", "/icon.png"):
                        with opener.open(origin + path, timeout=5) as response:
                            assert response.read(), path
                    with opener.open(origin + "/api/library", timeout=1) as response:
                        raise AssertionError(f"API reachable without session: {response.status}")
                except URLError as error:
                    if getattr(error, "code", None) == 403:
                        return
                    if getattr(error, "code", None) is not None:
                        raise
                    time.sleep(0.25)
            raise RuntimeError(f"App startup timed out or exited with status {app.poll()}.")
        except Exception:
            log.seek(0)
            print(log.read().decode(errors="replace"), file=sys.stderr)
            raise
        finally:
            if app.poll() is None:
                app.terminate()
                try:
                    app.wait(timeout=10)
                except TimeoutExpired:
                    app.kill()
                    app.wait()


if __name__ == "__main__":
    app = Path(sys.argv[1]).resolve()
    import plistlib

    with (app / "Contents/Info.plist").open("rb") as plist:
        assert plistlib.load(plist)["CFBundleShortVersionString"] == __version__
    verify(app / "Contents/MacOS/PickUpPhoto")
