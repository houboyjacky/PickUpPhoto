"""
ui/single_view.py — 單張預覽模式

功能：
- 主預覽區 GPU texture 顯示，等比縮放至視窗大小
- 左右鍵切換（由 app.py handler 觸發）
- 「完整解碼」按鈕
- 底欄 EXIF 更新（委由 app.py）
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import dearpygui.dearpygui as dpg
import numpy as np
from PIL import Image

from pickupphoto.core.scanner import PhotoInfo

if TYPE_CHECKING:
    from pickupphoto.ui.app import AppState

TAG_SINGLE_WINDOW = "single_scroll_window"
TAG_SINGLE_DRAW = "single_draw"
TAG_SINGLE_TOOLBAR = "single_toolbar"
TAG_FULL_DECODE_BTN = "btn_full_decode"
TAG_SINGLE_LOADING = "single_loading_text"
TAG_PHOTO_COUNTER = "photo_counter"


class SingleView:
    """單張預覽視圖。"""

    def __init__(self, state: "AppState") -> None:
        self._state = state
        self._current_texture: int | None = None
        self._current_filename: str | None = None
        self._full_decode_texture: int | None = None
        self._is_full_decoded: bool = False
        self._is_visible = False

    def show(self) -> None:
        """顯示單張視圖。"""
        self._build_if_needed()
        if dpg.does_item_exist(TAG_SINGLE_WINDOW):
            dpg.configure_item(TAG_SINGLE_WINDOW, show=True)
        self._is_visible = True
        # 顯示當前照片
        self.show_photo(self._state.preview_index)

    def hide(self) -> None:
        if dpg.does_item_exist(TAG_SINGLE_WINDOW):
            dpg.configure_item(TAG_SINGLE_WINDOW, show=False)
        self._is_visible = False

    def show_photo(self, idx: int) -> None:
        """顯示指定索引的照片。"""
        if not self._is_visible:
            return
        photos = self._state.filtered_photos
        if not photos or not (0 <= idx < len(photos)):
            return

        photo = photos[idx]
        self._state.preview_index = idx
        self._is_full_decoded = False

        # 更新計數器
        if dpg.does_item_exist(TAG_PHOTO_COUNTER):
            dpg.set_value(TAG_PHOTO_COUNTER, f"{idx + 1} / {len(photos)}  {photo.filename}")

        # 更新按鈕狀態
        if dpg.does_item_exist(TAG_FULL_DECODE_BTN):
            dpg.configure_item(TAG_FULL_DECODE_BTN, label="🔍 完整解碼")

        # 若是同一張，不重新載入 texture
        if photo.filename == self._current_filename:
            return

        self._current_filename = photo.filename
        self._load_preview(photo)

    def _load_preview(self, photo: PhotoInfo) -> None:
        """從快取或 embedded preview 載入預覽圖。"""
        import threading
        threading.Thread(
            target=self._load_preview_worker,
            args=(photo,),
            daemon=True,
        ).start()

    def _load_preview_worker(self, photo: PhotoInfo) -> None:
        """背景載入 preview 並更新 texture。"""
        arr = None

        # 優先從快取取較大尺寸（或直接解碼 embedded preview 1920px）
        try:
            from pickupphoto.core.raw_loader import load_embedded_preview
            result = load_embedded_preview(photo.path, max_size=1920)
            arr = result.image
        except Exception:
            pass

        if arr is not None:
            self._update_main_texture(arr)

    def _update_main_texture(self, arr: np.ndarray) -> None:
        """上傳 numpy array 至 GPU texture 並更新畫面。"""
        vp_w = dpg.get_viewport_client_width() - 300  # 留右側面板
        vp_h = dpg.get_viewport_client_height() - 120

        # 計算等比縮放
        h, w = arr.shape[:2]
        scale = min(vp_w / w, vp_h / h, 1.0)
        new_w = int(w * scale)
        new_h = int(h * scale)

        img = Image.fromarray(arr).resize((new_w, new_h), Image.LANCZOS)
        rgba = np.array(img.convert("RGBA"), dtype=np.float32) / 255.0
        flat = rgba.flatten().tolist()

        # 刪除舊 texture
        if self._current_texture and dpg.does_item_exist(self._current_texture):
            dpg.delete_item(self._current_texture)

        self._current_texture = dpg.add_static_texture(
            width=new_w, height=new_h, default_value=flat,
        )

        # 更新繪圖區
        if dpg.does_item_exist(TAG_SINGLE_DRAW):
            dpg.delete_item(TAG_SINGLE_DRAW, children_only=True)
            # 置中顯示
            x_off = max(0, (vp_w - new_w) // 2)
            y_off = max(0, (vp_h - new_h) // 2)
            dpg.draw_image(
                self._current_texture,
                (x_off, y_off),
                (x_off + new_w, y_off + new_h),
                parent=TAG_SINGLE_DRAW,
            )

    def on_full_decode(self) -> None:
        """完整解碼按鈕回呼。"""
        photo = self._state.current_photo
        if photo is None:
            return
        dpg.configure_item(TAG_FULL_DECODE_BTN, label="⏳ 解碼中...")
        import threading
        threading.Thread(
            target=self._full_decode_worker,
            args=(photo,),
            daemon=True,
        ).start()

    def _full_decode_worker(self, photo: PhotoInfo) -> None:
        try:
            from pickupphoto.core.raw_loader import load_full_decode
            result = load_full_decode(photo.path)
            self._is_full_decoded = True
            self._update_main_texture(result.image)
            dpg.configure_item(TAG_FULL_DECODE_BTN, label="✅ 完整解碼")
        except Exception as e:
            dpg.configure_item(TAG_FULL_DECODE_BTN, label="❌ 解碼失敗")

    def _build_if_needed(self) -> None:
        """首次顯示時建立 DPG 元件。"""
        if dpg.does_item_exist(TAG_SINGLE_WINDOW):
            return

        parent = "content_area"
        if not dpg.does_item_exist(parent):
            return

        vp_w = dpg.get_viewport_client_width()
        vp_h = dpg.get_viewport_client_height() - 120

        with dpg.child_window(
            tag=TAG_SINGLE_WINDOW,
            parent=parent,
            border=False,
            width=-1,
            height=-1,
            show=False,
        ):
            # 上方計數器 + 完整解碼按鈕
            with dpg.group(horizontal=True, tag=TAG_SINGLE_TOOLBAR):
                dpg.add_text(tag=TAG_PHOTO_COUNTER, default_value="")
                dpg.add_spacer(width=20)
                dpg.add_button(
                    tag=TAG_FULL_DECODE_BTN,
                    label="🔍 完整解碼",
                    callback=self.on_full_decode,
                    width=120,
                )

            # 主預覽繪圖區
            with dpg.drawlist(
                tag=TAG_SINGLE_DRAW,
                width=vp_w - 310,
                height=vp_h - 40,
            ):
                pass
