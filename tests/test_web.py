"""Regression coverage for the browser API and its local session boundary."""

import http.client
import json
import threading
import time

from pickupphoto.web.server import LocalApp


def test_library_session_rating_and_export(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    photo = source / "sample.NEF"
    photo.write_bytes(b"sample original contents")
    sidecar = source / ".pickupphoto"
    sidecar.mkdir()
    (sidecar / "ratings.json").write_text('{"sample.NEF": 2}', encoding="utf-8")
    target = tmp_path / "export"

    with LocalApp(initial_folder=source) as app:
        server = threading.Thread(target=app.serve_forever)
        server.start()
        connection = http.client.HTTPConnection("127.0.0.1", app.server_port, timeout=3)
        try:
            def request(path, data=None, **headers):
                if data is None:
                    connection.request("GET", path, headers=headers)
                else:
                    headers.update({"Content-Type": "application/json", "X-PickUpPhoto": "1"})
                    connection.request("POST", path, json.dumps(data), headers)
                response = connection.getresponse()
                return response.status, response.headers, response.read()

            assert request("/api/library")[0] == 403
            assert request("/", Host=f"example.test:{app.server_port}")[0] == 403
            status, headers, _ = request(f"/start/{app.ticket}")
            assert status == 303
            cookie = headers["Set-Cookie"].split(";", 1)[0]
            status, _, body = request("/api/library", Cookie=cookie)
            assert status == 200
            library = json.loads(body)
            assert library["photos"][0]["stars"] == 2

            rating = {"id": library["id"], "photo": 0, "stars": 4}
            assert request("/api/rate", rating, Cookie=cookie, Origin="https://example.test")[0] == 403
            assert request("/api/rate", rating, Cookie=cookie, Origin=app.origin)[0] == 200
            assert json.loads((sidecar / "ratings.json").read_text()) == {"sample.NEF": 4}
            assert request("/api/export", {
                "id": library["id"], "folder": str(target), "stars": 4,
                "mode": ">=", "conflict": "rename",
            }, Cookie=cookie, Origin=app.origin)[0] == 200
            for _ in range(100):
                status, _, body = request("/api/status", Cookie=cookie)
                assert status == 200
                job = json.loads(body)["job"]
                if not job["running"]:
                    break
                time.sleep(0.02)
            assert job["result"]["copied"] == 1
            assert (target / photo.name).read_bytes() == photo.read_bytes()
        finally:
            connection.close()
            app.shutdown()
            server.join()
