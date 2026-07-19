"""
ui/app.py — Dear PyGui 主視窗與應用程式狀態

職責：
- 初始化 DPG 視窗
- 全域鍵盤 handler（數字鍵 0-5、← →）
- 視圖切換（格狀 / 單張）
- 協調 scanner、cache、database、AI 分析
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING

import dearpygui.dearpygui as dpg

from pickupphoto.core.database import Database
from pickupphoto.core.scanner import PhotoInfo, scan_folder
from pickupphoto.core.thumbnail_cache import ThumbnailCache, delete_cache, get_cache_info

if TYPE_CHECKING:
    pass

# ─── UI Tag 常數 ───────────────────────────────────────────────
TAG_MAIN_WINDOW = "main_window"
TAG_TOOLBAR = "toolbar"
TAG_CONTENT_AREA = "content_area"
TAG_GRID_VIEW = "grid_view"
TAG_SINGLE_VIEW = "single_view"
TAG_EXIF_BAR = "exif_bar"
TAG_STATUS_BAR = "status_bar"
TAG_PROGRESS_BAR = "progress_bar"
TAG_FOLDER_BTN = "btn_open_folder"
TAG_VIEW_GRID_BTN = "btn_view_grid"
TAG_VIEW_SINGLE_BTN = "btn_view_single"
TAG_FILTER_COMBO = "filter_combo"
TAG_AI_SCAN_BTN = "btn_ai_scan"
TAG_EXPORT_BTN = "btn_export"

# 視圖模式
VIEW_GRID = "grid"
VIEW_SINGLE = "single"

# 篩選選項
FILTER_OPTIONS = ["全部", "≥1★", "≥2★", "≥3★", "≥4★", "=5★", "=4★", "=3★", "=2★", "=1★"]


class AppState:
    """應用程式全域狀態（單例）。"""

    def __init__(self) -> None:
        self.folder: Path | None = None
        self.photos: list[PhotoInfo] = []
        self.filtered_photos: list[PhotoInfo] = []  # 當前篩選後的清單
        self.selected_index: int = -1               # 格狀視圖選取索引（filtered 中）
        self.preview_index: int = 0                 # 單張模式當前索引（filtered 中）
        self.view_mode: str = VIEW_GRID
        self.filter_option: str = "全部"

        self.db: Database | None = None
        self.cache: ThumbnailCache | None = None

        # AI 掃描狀態
        self.ai_scanning: bool = False
        self.ai_use_eye_focus: bool = False

        # 快取進度
        self.cache_progress: int = 0
        self.cache_total: int = 0

    @property
    def current_photo(self) -> PhotoInfo | None:
        idx = self.preview_index if self.view_mode == VIEW_SINGLE else self.selected_index
        if 0 <= idx < len(self.filtered_photos):
            return self.filtered_photos[idx]
        return None

    def apply_filter(self) -> None:
        """依 filter_option 重新計算 filtered_photos。"""
        opt = self.filter_option
        if opt == "全部":
            self.filtered_photos = list(self.photos)
        elif opt.startswith("≥"):
            n = int(opt[1])
            self.filtered_photos = [p for p in self.photos if p.stars >= n]
        elif opt.startswith("="):
            n = int(opt[1])
            self.filtered_photos = [p for p in self.photos if p.stars == n]
        else:
            self.filtered_photos = list(self.photos)

        # 確保索引不越界
        if self.selected_index >= len(self.filtered_photos):
            self.selected_index = max(0, len(self.filtered_photos) - 1)
        if self.preview_index >= len(self.filtered_photos):
            self.preview_index = 0


class PickUpPhotoApp:
    """主應用程式類別。"""

    def __init__(self) -> None:
        self.state = AppState()
        self._grid_view = None
        self._single_view = None
        self._analysis_panel = None

    def run(self) -> None:
        """啟動 Dear PyGui 主迴圈。"""
        dpg.create_context()
        self._setup_font()
        self._setup_theme()
        self._build_ui()
        self._register_keyboard_handler()

        dpg.create_viewport(
            title="PickUpPhoto",
            width=1400,
            height=900,
            min_width=900,
            min_height=600,
        )
        dpg.setup_dearpygui()
        dpg.show_viewport()
        dpg.set_primary_window(TAG_MAIN_WINDOW, True)

        dpg.start_dearpygui()

        # 關閉時處理快取對話
        self._on_close()
        dpg.destroy_context()

    # ─── 主題與字型設定 ────────────────────────────────────────

    def _setup_font(self) -> None:
        """載入系統中文字型，防止中文顯示為問號。"""
        import os
        font_paths = [
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Light.ttc",
            "/System/Library/Fonts/STHeiti Medium.ttc",
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
            "/Library/Fonts/Arial Unicode.ttf",
        ]
        font_path = None
        for path in font_paths:
            if os.path.exists(path):
                font_path = path
                break

        if font_path:
            with dpg.font_registry():
                with dpg.font(font_path, 16) as default_font:
                    dpg.add_font_range_hint(dpg.mvFontRangeHint_Default)
                    dpg.add_font_range_hint(dpg.mvFontRangeHint_Chinese_Full)
                dpg.bind_font(default_font)

    def _setup_theme(self) -> None:
        """設定深色主題。"""
        with dpg.theme() as global_theme:
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_color(dpg.mvThemeCol_WindowBg, (22, 22, 30, 255))
                dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (28, 28, 38, 255))
                dpg.add_theme_color(dpg.mvThemeCol_FrameBg, (40, 40, 55, 255))
                dpg.add_theme_color(dpg.mvThemeCol_Button, (55, 90, 160, 255))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (70, 110, 200, 255))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (45, 75, 140, 255))
                dpg.add_theme_color(dpg.mvThemeCol_Header, (55, 90, 160, 120))
                dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, (70, 110, 200, 150))
                dpg.add_theme_color(dpg.mvThemeCol_Text, (220, 220, 230, 255))
                dpg.add_theme_color(dpg.mvThemeCol_Border, (60, 60, 80, 255))
                dpg.add_theme_style(dpg.mvStyleVar_WindowRounding, 6)
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 4)
                dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 8, 6)
                dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 10, 8)
        dpg.bind_theme(global_theme)

    # ─── UI 建構 ──────────────────────────────────────────────

    def _build_ui(self) -> None:
        """建立主視窗 UI 結構。"""
        from pickupphoto.ui.grid_view import GridView
        from pickupphoto.ui.single_view import SingleView
        from pickupphoto.ui.analysis_panel import AnalysisPanel

        with dpg.window(tag=TAG_MAIN_WINDOW, no_title_bar=True, no_move=True,
                        no_resize=True, no_scrollbar=True):
            self._build_toolbar()
            self._build_content_area()
            self._build_status_bar()

        self._grid_view = GridView(self.state)
        self._single_view = SingleView(self.state)
        self._analysis_panel = AnalysisPanel(self.state)

    def _build_toolbar(self) -> None:
        """頂部工具列。"""
        with dpg.group(tag=TAG_TOOLBAR, horizontal=True):
            dpg.add_button(
                tag=TAG_FOLDER_BTN,
                label="📂 開啟資料夾",
                callback=self._on_open_folder,
                width=130,
            )
            dpg.add_spacer(width=10)
            dpg.add_button(
                tag=TAG_VIEW_GRID_BTN,
                label="⊞ 格狀",
                callback=lambda: self._switch_view(VIEW_GRID),
                width=80,
            )
            dpg.add_button(
                tag=TAG_VIEW_SINGLE_BTN,
                label="▣ 單張",
                callback=lambda: self._switch_view(VIEW_SINGLE),
                width=80,
            )
            dpg.add_spacer(width=20)
            dpg.add_text("篩選：")
            dpg.add_combo(
                tag=TAG_FILTER_COMBO,
                items=FILTER_OPTIONS,
                default_value="全部",
                width=90,
                callback=self._on_filter_change,
            )
            dpg.add_spacer(width=20)
            dpg.add_button(
                tag=TAG_AI_SCAN_BTN,
                label="🤖 掃描 AI",
                callback=self._on_ai_scan,
                width=100,
            )
            dpg.add_spacer(width=10)
            dpg.add_button(
                tag=TAG_EXPORT_BTN,
                label="📤 輸出",
                callback=self._on_export,
                width=80,
            )
            # 進度條（右側）
            dpg.add_spacer(width=20)
            dpg.add_progress_bar(
                tag=TAG_PROGRESS_BAR,
                default_value=0.0,
                width=200,
                overlay="",
            )

    def _build_content_area(self) -> None:
        """主內容區（格狀 / 單張視圖會在此繪製）。"""
        dpg.add_child_window(
            tag=TAG_CONTENT_AREA,
            border=False,
            height=-50,  # 留出底部 EXIF 欄
        )

    def _build_status_bar(self) -> None:
        """底部 EXIF 資訊列。"""
        with dpg.group(horizontal=True):
            dpg.add_text(tag=TAG_EXIF_BAR, default_value="請開啟資料夾以開始")
            dpg.add_spacer(width=-1)
            dpg.add_text(tag=TAG_STATUS_BAR, default_value="")

    # ─── 鍵盤 Handler ────────────────────────────────────────

    def _register_keyboard_handler(self) -> None:
        """註冊全域鍵盤事件。"""
        with dpg.handler_registry():
            dpg.add_key_press_handler(key=dpg.mvKey_Left, callback=self._on_key_left)
            dpg.add_key_press_handler(key=dpg.mvKey_Right, callback=self._on_key_right)
            # 數字鍵 0-5
            for key, stars in [
                (dpg.mvKey_0, 0), (dpg.mvKey_1, 1), (dpg.mvKey_2, 2),
                (dpg.mvKey_3, 3), (dpg.mvKey_4, 4), (dpg.mvKey_5, 5),
            ]:
                dpg.add_key_press_handler(
                    key=key,
                    callback=lambda _, __, s=stars: self._on_rate(s),
                )

    def _on_key_left(self) -> None:
        if self.state.view_mode == VIEW_SINGLE and self.state.preview_index > 0:
            self.state.preview_index -= 1
            self._refresh_single_view()

    def _on_key_right(self) -> None:
        if self.state.view_mode == VIEW_SINGLE:
            if self.state.preview_index < len(self.state.filtered_photos) - 1:
                self.state.preview_index += 1
                self._refresh_single_view()

    def _on_rate(self, stars: int) -> None:
        """數字鍵評星。"""
        photo = self.state.current_photo
        if photo is None or self.state.db is None:
            return
        photo.stars = stars
        self.state.db.set_rating(photo.filename, stars)
        self._update_exif_bar()
        if self._grid_view:
            self._grid_view.refresh_badges(photo.filename)
        if self._analysis_panel:
            self._analysis_panel.refresh()

    # ─── 事件回呼 ────────────────────────────────────────────

    def _on_open_folder(self) -> None:
        """開啟資料夾選擇器。"""
        dpg.add_file_dialog(
            label="選擇照片資料夾",
            directory_selector=True,
            show=True,
            callback=self._on_folder_selected,
            width=700,
            height=400,
        )

    def _on_folder_selected(self, sender, app_data: dict) -> None:
        """資料夾選擇完成。"""
        selections = app_data.get("selections", {})
        if not selections:
            return
        folder = Path(list(selections.values())[0])
        self._load_folder(folder)

    def _load_folder(self, folder: Path) -> None:
        """載入資料夾：掃描 → 開啟 DB → 建立快取。"""
        # 關閉舊 DB
        if self.state.db:
            self.state.db.close()

        self.state.folder = folder
        self.state.photos = []
        self.state.filtered_photos = []
        self.state.selected_index = -1
        self.state.preview_index = 0

        dpg.set_value(TAG_EXIF_BAR, f"掃描中：{folder.name}...")

        # 背景掃描
        threading.Thread(target=self._scan_worker, args=(folder,), daemon=True).start()

    def _scan_worker(self, folder: Path) -> None:
        try:
            photos = scan_folder(folder)
        except Exception as e:
            dpg.set_value(TAG_EXIF_BAR, f"掃描失敗：{e}")
            return

        if not photos:
            dpg.set_value(TAG_EXIF_BAR, "此資料夾未找到支援的 RAW 檔案（NEF / RAF）")
            return

        db = Database(folder)
        db.open()
        db.load_ratings_from_json()

        # 從 DB 恢復評分與 AI 結果
        all_ratings = db.get_all_ratings()
        all_ai = db.get_all_ai_scores()
        all_burst = db.get_all_burst_groups()
        for p in photos:
            p.stars = all_ratings.get(p.filename, 0)
            p.has_ai_scores = p.filename in all_ai
            burst_info = all_burst.get(p.filename)
            if burst_info:
                p.ai_best = bool(burst_info["ai_best"])
                p.burst_group_id = burst_info["group_id"]
                p.burst_group_rank = burst_info["group_rank"]

        self.state.photos = photos
        self.state.db = db
        self.state.cache_total = len(photos)
        self.state.cache_progress = 0
        self.state.apply_filter()

        cache = ThumbnailCache(db, photos)
        self.state.cache = cache

        # 檢查 TTL
        if cache.check_ttl():
            dpg.set_value(TAG_EXIF_BAR, "快取已過期，正在重建...")

        # 啟動背景快取建立
        cache.start_build(
            on_progress=self._on_cache_progress,
            on_done=self._on_cache_done,
        )

        dpg.set_value(TAG_STATUS_BAR, f"{len(photos)} 張")
        if self._grid_view:
            self._grid_view.load(photos)

    def _on_cache_progress(self, completed: int, total: int, filename: str) -> None:
        self.state.cache_progress = completed
        progress = completed / total if total > 0 else 0.0
        dpg.set_value(TAG_PROGRESS_BAR, progress)
        dpg.configure_item(TAG_PROGRESS_BAR, overlay=f"快取 {completed}/{total}")
        if self._grid_view:
            self._grid_view.on_thumbnail_ready(filename)

    def _on_cache_done(self) -> None:
        dpg.set_value(TAG_PROGRESS_BAR, 1.0)
        dpg.configure_item(TAG_PROGRESS_BAR, overlay="快取完成")
        if self._grid_view:
            self._grid_view.refresh_all()

    def _on_filter_change(self, sender, app_data: str) -> None:
        self.state.filter_option = app_data
        self.state.apply_filter()
        if self._grid_view:
            self._grid_view.load(self.state.filtered_photos)

    def _on_ai_scan(self) -> None:
        """觸發 AI 掃描（背景執行緒）。"""
        if self.state.ai_scanning or not self.state.photos:
            return
        self.state.ai_scanning = True
        dpg.configure_item(TAG_AI_SCAN_BTN, label="🔄 掃描中...")
        threading.Thread(target=self._ai_scan_worker, daemon=True).start()

    def _ai_scan_worker(self) -> None:
        from pickupphoto.analysis.sharpness import compute_sharpness
        from pickupphoto.analysis.exposure import compute_exposure
        from pickupphoto.analysis.motion_blur import compute_motion_blur
        from pickupphoto.analysis.face_focus import compute_eye_focus, is_available as face_available
        from pickupphoto.analysis.burst_grouper import (
            group_burst_photos, select_best_in_groups, apply_group_metadata
        )
        from pickupphoto.core.raw_loader import load_embedded_preview

        db = self.state.db
        photos = self.state.photos
        total = len(photos)

        all_scores: dict[str, dict] = {}

        for i, photo in enumerate(photos):
            try:
                result = load_embedded_preview(photo.path, max_size=512)
                img = result.image

                sharpness = compute_sharpness(img)
                exposure = compute_exposure(img)
                motion_blur = compute_motion_blur(img)

                eye_focus = None
                has_face = None
                if self.state.ai_use_eye_focus and face_available():
                    ef_score, hf = compute_eye_focus(img)
                    eye_focus = ef_score
                    has_face = hf

                db.save_ai_scores(
                    photo.filename,
                    sharpness=sharpness,
                    exposure=exposure,
                    motion_blur=motion_blur,
                    eye_focus=eye_focus,
                    has_face=has_face,
                )
                photo.has_ai_scores = True
                all_scores[photo.filename] = {
                    "sharpness": sharpness,
                    "exposure": exposure,
                    "motion_blur": motion_blur,
                    "eye_focus": eye_focus,
                    "has_face": has_face,
                }
            except Exception:
                pass

            progress = (i + 1) / total
            dpg.set_value(TAG_PROGRESS_BAR, progress)
            dpg.configure_item(TAG_PROGRESS_BAR, overlay=f"AI {i+1}/{total}")

        # 連拍分組
        db.clear_burst_groups()
        groups = group_burst_photos(photos)
        groups = select_best_in_groups(groups, all_scores, self.state.ai_use_eye_focus)
        photos_by_name = {p.filename: p for p in photos}
        apply_group_metadata(groups, photos_by_name)

        for group in groups:
            for rank, photo in enumerate(group.photos, start=1):
                db.save_burst_group(
                    filename=photo.filename,
                    group_id=group.group_id,
                    group_size=len(group.photos),
                    group_rank=rank,
                    ai_best=photo.ai_best,
                    composite_score=group.scores.get(photo.filename),
                )

        self.state.ai_scanning = False
        dpg.configure_item(TAG_AI_SCAN_BTN, label="🤖 掃描 AI")
        dpg.set_value(TAG_PROGRESS_BAR, 1.0)
        dpg.configure_item(TAG_PROGRESS_BAR, overlay="AI 分析完成")

        if self._grid_view:
            self._grid_view.refresh_all()

    def _on_export(self) -> None:
        """開啟輸出對話。"""
        from pickupphoto.ui.export_dialog import show_export_dialog
        show_export_dialog(self.state)

    # ─── 視圖切換 ────────────────────────────────────────────

    def _switch_view(self, mode: str) -> None:
        self.state.view_mode = mode
        if mode == VIEW_GRID:
            if self._grid_view:
                self._grid_view.show()
            if self._single_view:
                self._single_view.hide()
        else:
            if self._single_view:
                self._single_view.show()
            if self._grid_view:
                self._grid_view.hide()
        self._update_exif_bar()

    def _refresh_single_view(self) -> None:
        if self._single_view:
            self._single_view.show_photo(self.state.preview_index)
        self._update_exif_bar()
        if self._analysis_panel:
            self._analysis_panel.refresh()

    def navigate_to(self, index: int) -> None:
        """從格狀視圖跳至單張模式指定索引。"""
        self.state.preview_index = index
        self._switch_view(VIEW_SINGLE)
        self._refresh_single_view()

    # ─── EXIF 底欄更新 ───────────────────────────────────────

    def _update_exif_bar(self) -> None:
        photo = self.state.current_photo
        if photo:
            stars_str = "★" * photo.stars + "☆" * (5 - photo.stars)
            dpg.set_value(TAG_EXIF_BAR, f"{photo.exif_summary}  │  {stars_str}")
        else:
            dpg.set_value(TAG_EXIF_BAR, "—")

    # ─── 關閉處理 ────────────────────────────────────────────

    def _on_close(self) -> None:
        """應用程式關閉時處理快取管理。"""
        if self.state.db:
            self.state.db.close()

        if self.state.folder:
            info = get_cache_info(self.state.folder)
            if info:
                # 簡化版：直接關閉（完整對話框在 DPG 主迴圈結束後無法顯示）
                # 快取保留，依 TTL 自然過期
                pass
