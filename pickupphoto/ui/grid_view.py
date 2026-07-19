"""
ui/grid_view.py — 格狀縮圖視圖（Virtual Scroll + GPU Texture）

功能：
- 固定格大小縮圖格狀排列，支援垂直虛擬捲動
- 可視範圍才上傳 GPU texture，捲動時動態 load/unload
- 單擊選取（EXIF 底欄更新），雙擊跳單張模式
- 縮圖 badge：🏆（左上）、星等（左下）、⚠️（右下）
- 連拍群組底色區塊（交替淡色背景）
"""

from __future__ import annotations

import io
import time
from typing import TYPE_CHECKING

import dearpygui.dearpygui as dpg
import numpy as np
from PIL import Image

from pickupphoto.core.scanner import PhotoInfo

if TYPE_CHECKING:
    from pickupphoto.ui.app import AppState

# 縮圖格大小（px）
CELL_W = 190
CELL_H = 140
CELL_PAD = 6   # 格子間距
THUMB_W = CELL_W - CELL_PAD * 2
THUMB_H = CELL_H - CELL_PAD * 2 - 20  # 留底部星等文字

# 群組底色（RGBA）：交替使用
GROUP_COLORS = [
    (55, 80, 120, 60),
    (80, 55, 110, 60),
    (55, 100, 80, 60),
    (100, 80, 55, 60),
]

# 選取高亮邊框色
SELECTED_COLOR = (100, 160, 255, 255)
NORMAL_BORDER_COLOR = (60, 60, 80, 180)


class GridView:
    """格狀縮圖視圖。"""

    def __init__(self, state: "AppState") -> None:
        self._state = state
        self._photos: list[PhotoInfo] = []
        self._texture_map: dict[str, int] = {}       # filename → texture tag
        self._group_color_map: dict[str, tuple] = {} # group_id → color
        self._last_click_time: dict[str, float] = {}  # filename → last click time
        self._visible_range: tuple[int, int] = (0, 0)
        self._cols: int = 4

        self._tag_window = "grid_scroll_window"
        self._tag_draw = "grid_draw_area"
        self._is_visible = False
        self._last_scroll_y: float = -1.0

    def load(self, photos: list[PhotoInfo]) -> None:
        """載入（或更新）照片清單，重建格狀視圖。"""
        self._photos = photos
        self._assign_group_colors()
        self._rebuild()

    def _assign_group_colors(self) -> None:
        """為每個連拍群組分配底色。"""
        self._group_color_map.clear()
        idx = 0
        for p in self._photos:
            gid = p.burst_group_id
            if gid and gid not in self._group_color_map:
                self._group_color_map[gid] = GROUP_COLORS[idx % len(GROUP_COLORS)]
                idx += 1

    def _rebuild(self) -> None:
        """重建 DPG 格狀視圖元件。"""
        # 清除舊的 textures
        self._unload_all_textures()

        if dpg.does_item_exist(self._tag_window):
            dpg.delete_item(self._tag_window)

        if not self._photos:
            return

        parent = "content_area"
        if not dpg.does_item_exist(parent):
            return

        vp_w = dpg.get_viewport_client_width()
        self._cols = max(2, (vp_w - 20) // (CELL_W + CELL_PAD))
        rows = (len(self._photos) + self._cols - 1) // self._cols
        total_h = rows * (CELL_H + CELL_PAD) + CELL_PAD

        with dpg.child_window(
            tag=self._tag_window,
            parent=parent,
            border=False,
            width=-1,
            height=-1,
        ):
            with dpg.drawlist(
                tag=self._tag_draw,
                width=vp_w - 20,
                height=total_h,
            ):
                pass  # 實際繪製由 _draw_visible 完成

        # 繪製可見範圍
        self._draw_visible(force=True)
        self._is_visible = True

    def _draw_visible(self, force: bool = False) -> None:
        """僅繪製可視範圍內的縮圖（虛擬捲動核心，優化防抖）。"""
        if not dpg.does_item_exist(self._tag_draw):
            return

        scroll_y = dpg.get_y_scroll(self._tag_window) if dpg.does_item_exist(self._tag_window) else 0
        if not force and abs(scroll_y - self._last_scroll_y) < 1.0:
            return
        self._last_scroll_y = scroll_y

        dpg.delete_item(self._tag_draw, children_only=True)

        vp_h = dpg.get_viewport_client_height()

        row_h = CELL_H + CELL_PAD
        first_row = max(0, int(scroll_y / row_h) - 1)
        last_row = int((scroll_y + vp_h) / row_h) + 2
        first_idx = first_row * self._cols
        last_idx = min(len(self._photos), last_row * self._cols)

        self._visible_range = (first_idx, last_idx)

        # Unload 不可見 textures
        visible_filenames = {self._photos[i].filename for i in range(first_idx, last_idx)}
        for fname in list(self._texture_map.keys()):
            if fname not in visible_filenames:
                self._unload_texture(fname)

        # 繪製可見格子
        for i in range(first_idx, last_idx):
            if i >= len(self._photos):
                break
            self._draw_cell(i)

    def _draw_cell(self, idx: int) -> None:
        """繪製單個縮圖格子。"""
        photo = self._photos[idx]
        col = idx % self._cols
        row = idx // self._cols
        x0 = CELL_PAD + col * (CELL_W + CELL_PAD)
        y0 = CELL_PAD + row * (CELL_H + CELL_PAD)
        x1 = x0 + CELL_W
        y1 = y0 + CELL_H

        draw_parent = self._tag_draw

        # 群組底色
        gid = photo.burst_group_id
        if gid and gid in self._group_color_map:
            bg_color = self._group_color_map[gid]
            dpg.draw_rectangle(
                (x0 - 2, y0 - 2), (x1 + 2, y1 + 2),
                fill=bg_color, color=(0, 0, 0, 0),
                parent=draw_parent,
            )

        # 邊框（選取高亮）
        is_selected = (self._state.selected_index == idx)
        border_color = SELECTED_COLOR if is_selected else NORMAL_BORDER_COLOR
        border_thick = 2 if is_selected else 1
        dpg.draw_rectangle(
            (x0, y0), (x1, y1),
            fill=(35, 35, 48, 255),
            color=border_color,
            thickness=border_thick,
            parent=draw_parent,
        )

        # 縮圖圖像
        tex_tag = self._ensure_texture(photo, x0, y0)
        if tex_tag is not None:
            img_x = x0 + CELL_PAD
            img_y = y0 + CELL_PAD
            dpg.draw_image(
                tex_tag,
                (img_x, img_y),
                (img_x + THUMB_W, img_y + THUMB_H),
                parent=draw_parent,
            )
        else:
            # 佔位符
            dpg.draw_rectangle(
                (x0 + CELL_PAD, y0 + CELL_PAD),
                (x1 - CELL_PAD, y1 - CELL_PAD - 20),
                fill=(45, 45, 60, 255),
                color=(0, 0, 0, 0),
                parent=draw_parent,
            )
            dpg.draw_text(
                (x0 + CELL_W // 2 - 15, y0 + CELL_H // 2 - 10),
                "載入中...",
                color=(120, 120, 140, 200),
                size=12,
                parent=draw_parent,
            )

        t = self._state.t

        # Badge：[AI最佳]（左上）
        if photo.ai_best:
            dpg.draw_text(
                (x0 + 4, y0 + 4),
                t("ai_best_badge"),
                color=(255, 215, 0, 255),
                size=12,
                parent=draw_parent,
            )

        # Badge：星等（左下）
        if photo.stars > 0:
            star_str = "★" * photo.stars
            dpg.draw_text(
                (x0 + 4, y1 - 20),
                star_str,
                color=(255, 200, 50, 230),
                size=13,
                parent=draw_parent,
            )

        # Badge：[!]（右下，AI 問題）
        if photo.has_ai_scores and self._has_warning(photo):
            dpg.draw_text(
                (x1 - 28, y1 - 20),
                t("warning_badge"),
                color=(255, 100, 0, 230),
                size=13,
                parent=draw_parent,
            )

        # 點擊處理（invisible button overlay）
        tag_btn = f"grid_btn_{idx}"
        if not dpg.does_item_exist(tag_btn):
            pass  # DPG drawlist 點擊需透過 mouse_click_handler 實作
            # 實際點擊邏輯由 _setup_click_handler 處理

    def _has_warning(self, photo: PhotoInfo) -> bool:
        """判斷是否顯示 ⚠️ badge。"""
        if self._state.db is None:
            return False
        scores = self._state.db.get_ai_scores(photo.filename)
        if not scores:
            return False
        sharpness = scores.get("sharpness") or 100.0
        exposure = scores.get("exposure") or 100.0
        motion_blur = scores.get("motion_blur") or 100.0
        return sharpness < 40 or exposure < 40 or motion_blur < 30

    def _ensure_texture(self, photo: PhotoInfo, x0: int, y0: int) -> int | None:
        """確保縮圖已上傳至 GPU，回傳 texture tag 或 None。"""
        fname = photo.filename
        if fname in self._texture_map:
            return self._texture_map[fname]

        # 嘗試從快取讀取
        if self._state.cache is None:
            return None
        arr = self._state.cache.get(fname)
        if arr is None:
            return None

        return self._upload_texture(fname, arr)

    def _upload_texture(self, filename: str, arr: np.ndarray) -> int:
        """上傳 numpy array 至 GPU texture，回傳 texture tag。"""
        # 建立黑底背景以維護比例（左右或上下填充黑色）
        background = Image.new("RGBA", (THUMB_W, THUMB_H), (15, 15, 20, 255)) # 與深色主題搭配的深灰黑色
        img = Image.fromarray(arr).convert("RGBA")
        
        # 等比例縮放至不超過 THUMB_W x THUMB_H
        img.thumbnail((THUMB_W, THUMB_H), Image.Resampling.LANCZOS)
        
        # 置中貼上
        x = (THUMB_W - img.width) // 2
        y = (THUMB_H - img.height) // 2
        background.paste(img, (x, y), img)

        rgba = np.array(background, dtype=np.float32) / 255.0
        flat = rgba.flatten().tolist()

        tag = dpg.add_static_texture(
            width=THUMB_W,
            height=THUMB_H,
            default_value=flat,
            parent="global_texture_registry",
        )
        self._texture_map[filename] = tag
        return tag

    def _unload_texture(self, filename: str) -> None:
        """從 GPU VRAM 卸載 texture。"""
        tag = self._texture_map.pop(filename, None)
        if tag and dpg.does_item_exist(tag):
            dpg.delete_item(tag)

    def _unload_all_textures(self) -> None:
        for fname in list(self._texture_map.keys()):
            self._unload_texture(fname)

    # ─── 公開方法 ────────────────────────────────────────────

    def on_thumbnail_ready(self, filename: str) -> None:
        """快取建立完成某張時，若在可視範圍內則重繪。"""
        if self._state.cache is None:
            return
        first, last = self._visible_range
        idx = next((i for i, p in enumerate(self._photos) if p.filename == filename), -1)
        if first <= idx < last:
            self._draw_visible(force=True)

    def refresh_badges(self, filename: str) -> None:
        """評分或 AI 狀態變更時，重繪相關格子。"""
        self._draw_visible(force=True)

    def refresh_all(self) -> None:
        """全部重繪。"""
        self._assign_group_colors()
        self._draw_visible(force=True)

    def on_resize(self) -> None:
        """當視區大小改變時呼叫，自動調整行數並重建格狀結構。"""
        if not self._is_visible or not self._photos:
            return

        vp_w = dpg.get_viewport_client_width()
        new_cols = max(2, (vp_w - 20) // (CELL_W + CELL_PAD))
        
        # 僅當行數改變時才重建，避免不必要的重新排版
        if new_cols != self._cols:
            self._rebuild()

    def hit_test(self, mx: float, my: float) -> int:
        """將視區滑鼠座標轉換為照片索引，未命中時回傳 -1。"""
        if not self._photos or not dpg.does_item_exist(self._tag_window):
            return -1

        # drawlist 在視區的起始座標
        try:
            rect_min = dpg.get_item_rect_min(self._tag_draw)
        except Exception:
            return -1

        draw_x = rect_min[0]
        draw_y = rect_min[1]

        # 相對於 drawlist 的滑鼠座標（加上滾動偏移）
        scroll_y = dpg.get_y_scroll(self._tag_window)
        local_x = mx - draw_x
        local_y = my - draw_y + scroll_y

        if local_x < 0 or local_y < 0:
            return -1

        col = int(local_x // (CELL_W + CELL_PAD))
        row = int(local_y // (CELL_H + CELL_PAD))

        if col < 0 or col >= self._cols:
            return -1

        # 確認點擊在格子內（非 padding 空隙）
        cell_x = local_x - col * (CELL_W + CELL_PAD) - CELL_PAD
        cell_y = local_y - row * (CELL_H + CELL_PAD) - CELL_PAD
        if cell_x < 0 or cell_x > CELL_W or cell_y < 0 or cell_y > CELL_H:
            return -1

        idx = row * self._cols + col
        if idx < 0 or idx >= len(self._photos):
            return -1

        return idx

    def show(self) -> None:
        if dpg.does_item_exist(self._tag_window):
            dpg.configure_item(self._tag_window, show=True)
        self._is_visible = True

    def hide(self) -> None:
        if dpg.does_item_exist(self._tag_window):
            dpg.configure_item(self._tag_window, show=False)
        self._is_visible = False

    def on_click(self, idx: int) -> None:
        """單擊選取，雙擊跳單張模式。"""
        photo = self._photos[idx] if 0 <= idx < len(self._photos) else None
        if photo is None:
            return

        now = time.time()
        last = self._last_click_time.get(photo.filename, 0.0)
        is_double = (now - last) < 0.4
        self._last_click_time[photo.filename] = now

        prev_selected = self._state.selected_index
        self._state.selected_index = idx

        # 更新 EXIF 底欄
        from pickupphoto.ui.app import TAG_EXIF_BAR
        if photo:
            stars_str = "★" * photo.stars + "☆" * (5 - photo.stars)
            dpg.set_value(TAG_EXIF_BAR, f"{photo.exif_summary}  │  {stars_str}")

        if is_double:
            # 雙擊 → 進入單張模式
            app = self._find_app()
            if app:
                app.navigate_to(idx)
        else:
            # 重繪（高亮更新）
            self._draw_visible(force=True)

    def _find_app(self):
        """取得 app 實例（循環引用迴避）。"""
        from pickupphoto.ui.app import PickUpPhotoApp
        import gc
        for obj in gc.get_objects():
            if isinstance(obj, PickUpPhotoApp):
                return obj
        return None
