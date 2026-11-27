"""Launch PickUpPhoto as a local browser app."""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="PickUpPhoto 本機 RAW 照片瀏覽器")
    parser.add_argument("folder", nargs="?", type=Path, help="啟動時開啟的資料夾")
    parser.add_argument("--port", type=int, default=0, help="本機連接埠，預設由系統分配")
    display = parser.add_mutually_exclusive_group()
    display.add_argument("--browser", action="store_true", help="以預設瀏覽器開啟介面")
    display.add_argument("--no-browser", action="store_true", help="只啟動服務並顯示網址")
    parser.add_argument("--legacy", action="store_true", help="使用原本的 Dear PyGui 介面")
    args = parser.parse_args()

    if args.legacy:
        if getattr(sys, "frozen", False):
            parser.error("舊版介面僅支援從原始碼執行。")
        from importlib import import_module

        import_module("pickupphoto.ui.app").PickUpPhotoApp().run()
        return

    from pickupphoto.web.server import LocalApp

    folder = args.folder.expanduser().resolve() if args.folder else None
    with LocalApp(args.port, folder) as app:
        url = f"{app.origin}/start/{app.ticket}"
        if not getattr(sys, "frozen", False):
            print(f"PickUpPhoto  {url}", flush=True)
        if sys.platform == "darwin":
            from pickupphoto.web.macos import run_window

            if not (args.browser or args.no_browser):
                run_window(app, url)
                return
        if not args.no_browser:
            webbrowser.open(url)
        try:
            app.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
