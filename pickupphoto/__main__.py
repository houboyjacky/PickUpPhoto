"""
PickUpPhoto 入口點
執行方式：python -m pickupphoto
"""

from __future__ import annotations

import sys


def main() -> None:
    """應用程式主入口。"""
    # 延遲 import，避免未安裝 dearpygui 時在 import 階段崩潰
    try:
        from pickupphoto.ui.app import PickUpPhotoApp
    except ImportError as exc:
        print(f"[PickUpPhoto] 無法載入 UI 模組：{exc}", file=sys.stderr)
        print("請確認已安裝所有依賴：pip install -e '.'", file=sys.stderr)
        sys.exit(1)

    app = PickUpPhotoApp()
    app.run()


if __name__ == "__main__":
    main()
