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
TAG_PATH_INPUT = "input_folder_path"

TAG_MENU_BAR = "main_menu_bar"
TAG_MENU_FILE = "menu_file"
TAG_MENU_VIEW = "menu_view"
TAG_MENU_TOOLS = "menu_tools"
TAG_MENU_LANG = "menu_lang"

TAG_MENU_ITEM_OPEN = "menu_item_open"
TAG_MENU_ITEM_CLEAR = "menu_item_clear"
TAG_MENU_ITEM_GRID = "menu_item_grid"
TAG_MENU_ITEM_SINGLE = "menu_item_single"
TAG_MENU_ITEM_SCAN = "menu_item_scan"
TAG_MENU_ITEM_EXPORT = "menu_item_export"
TAG_MENU_ITEM_LANG_ZH = "menu_item_lang_zh"
TAG_MENU_ITEM_LANG_EN = "menu_item_lang_en"
TAG_MENU_RECENT = "menu_recent"

# 視圖模式
VIEW_GRID = "grid"
VIEW_SINGLE = "single"

# 篩選選項
TAG_FILTER_LABEL = "filter_label"



class AppState:
    """應用程式全域狀態（單例）。"""

    def __init__(self) -> None:
        from pickupphoto.core.settings import I18N
        self.i18n = I18N()

        self.folder: Path | None = None
        self.photos: list[PhotoInfo] = []
        self.filtered_photos: list[PhotoInfo] = []  # 當前篩選後的清單
        self.selected_index: int = -1               # 格狀視圖選取索引（filtered 中）
        self.preview_index: int = 0                 # 單張模式當前索引（filtered 中）
        self.view_mode: str = VIEW_GRID
        self.filter_option = self.t("all")

        self.db: Database | None = None
        self.cache: ThumbnailCache | None = None

        # 核心效能與歷史設定
        self.max_workers: int = int(self.i18n.settings.get("max_workers", 4))
        self.recent_folders: list[str] = list(self.i18n.settings.get("recent_folders", []))

        # AI 掃描狀態
        self.ai_scanning: bool = False
        self.ai_use_eye_focus: bool = False

        # 快取進度
        self.cache_progress: int = 0
        self.cache_total: int = 0

    def t(self, key: str, *args: any) -> str:
        """語系翻譯。"""
        return self.i18n.t(key, *args)

    def update_max_workers(self, count: int) -> None:
        """更新背景快取執行緒數並儲存設定。"""
        self.max_workers = count
        self.i18n.settings["max_workers"] = count
        from pickupphoto.core.settings import save_settings
        save_settings(self.i18n.settings)

    def add_recent_folder(self, folder: Path) -> None:
        """記錄最近開啟的資料夾路徑。"""
        path_str = str(folder)
        if path_str in self.recent_folders:
            self.recent_folders.remove(path_str)
        self.recent_folders.insert(0, path_str)
        self.recent_folders = self.recent_folders[:10]  # 限制最多記錄 10 個
        self.i18n.settings["recent_folders"] = self.recent_folders
        from pickupphoto.core.settings import save_settings
        save_settings(self.i18n.settings)

    def clear_recent_history(self) -> None:
        """清除歷史路徑。"""
        self.recent_folders = []
        self.i18n.settings["recent_folders"] = []
        from pickupphoto.core.settings import save_settings
        save_settings(self.i18n.settings)

    @property
    def current_photo(self) -> PhotoInfo | None:
        idx = self.preview_index if self.view_mode == VIEW_SINGLE else self.selected_index
        if 0 <= idx < len(self.filtered_photos):
            return self.filtered_photos[idx]
        return None

    def apply_filter(self) -> None:
        """依 filter_option 重新計算 filtered_photos。"""
        # 取得當前語言的所有篩選文字選項
        t = self.t
        filter_items = [
            t("all"),
            t("stars_gte", 1),
            t("stars_gte", 2),
            t("stars_gte", 3),
            t("stars_gte", 4),
            t("stars_eq", 5),
            t("stars_eq", 4),
            t("stars_eq", 3),
            t("stars_eq", 2),
            t("stars_eq", 1),
        ]

        try:
            idx = filter_items.index(self.filter_option)
        except ValueError:
            idx = 0

        if idx == 0:
            self.filtered_photos = list(self.photos)
        elif 1 <= idx <= 4:
            n = idx  # 1, 2, 3, 4
            self.filtered_photos = [p for p in self.photos if p.stars >= n]
        elif 5 <= idx <= 9:
            n = 10 - idx  # 5, 4, 3, 2, 1
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
        dpg.add_texture_registry(tag="global_texture_registry")
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
        dpg.set_viewport_resize_callback(self._on_viewport_resize)
        dpg.show_viewport()
        dpg.set_primary_window(TAG_MAIN_WINDOW, True)

        # 改用自訂主迴圈，以支援虛擬滾動 (Virtual Scroll) 捲動時的即時重新整理
        while dpg.is_dearpygui_running():
            if self._grid_view and self._grid_view._is_visible:
                self._grid_view._draw_visible()
            # 每 frame 輪詢鍵盤（比 handler_registry 更可靠，不受 DPG 焦點影響）
            self._poll_keyboard()
            dpg.render_dearpygui_frame()

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
                    pass
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
            self._build_menu_bar()
            self._build_toolbar()
            self._build_content_area()
            self._build_status_bar()

        self._grid_view = GridView(self.state)
        self._single_view = SingleView(self.state)
        self._analysis_panel = AnalysisPanel(self.state)
        self._update_recent_menu()

    def _build_menu_bar(self) -> None:
        """頂部選單列。"""
        t = self.state.t
        with dpg.menu_bar(tag=TAG_MENU_BAR):
            with dpg.menu(tag=TAG_MENU_FILE, label=t("file_menu")):
                dpg.add_menu_item(tag=TAG_MENU_ITEM_OPEN, label=t("open_folder"), callback=self._on_open_folder)
                with dpg.menu(tag=TAG_MENU_RECENT, label=t("recent_folders")):
                    pass
                dpg.add_menu_item(tag=TAG_MENU_ITEM_CLEAR, label=t("clear_cache"), callback=self._on_clear_cache)

            with dpg.menu(tag=TAG_MENU_VIEW, label=t("view_menu")):
                dpg.add_menu_item(tag=TAG_MENU_ITEM_GRID, label=t("view_grid"), callback=lambda: self._switch_view(VIEW_GRID))
                dpg.add_menu_item(tag=TAG_MENU_ITEM_SINGLE, label=t("view_single"), callback=lambda: self._switch_view(VIEW_SINGLE))

            with dpg.menu(tag=TAG_MENU_TOOLS, label=t("tools_menu")):
                dpg.add_menu_item(tag=TAG_MENU_ITEM_SCAN, label=t("scan_ai"), callback=self._on_ai_scan)
                dpg.add_menu_item(tag=TAG_MENU_ITEM_EXPORT, label=t("export"), callback=self._on_export)
                dpg.add_separator()
                import os
                max_cpu = os.cpu_count() or 8
                dpg.add_slider_int(
                    tag="menu_item_cores",
                    label=t("cores_label"),
                    default_value=self.state.max_workers,
                    min_value=1,
                    max_value=max_cpu,
                    callback=self._on_cores_change,
                    width=120,
                )

            with dpg.menu(tag=TAG_MENU_LANG, label=t("lang_menu")):
                dpg.add_menu_item(tag=TAG_MENU_ITEM_LANG_ZH, label="繁體中文", callback=lambda: self._on_lang_menu_select("zh-Hant"))
                dpg.add_menu_item(tag=TAG_MENU_ITEM_LANG_EN, label="English", callback=lambda: self._on_lang_menu_select("en"))

    def _build_toolbar(self) -> None:
        """頂部工具列。"""
        t = self.state.t
        # 建立預設翻譯的篩選選項
        filter_items = self._get_filter_items()

        with dpg.group(tag=TAG_TOOLBAR, horizontal=True):
            dpg.add_input_text(
                tag=TAG_PATH_INPUT,
                hint=t("path_hint"),
                width=500,
                on_enter=True,
                callback=self._on_path_entered,
            )
            dpg.add_spacer(width=20)
            dpg.add_text(t("filter"), tag=TAG_FILTER_LABEL)
            dpg.add_combo(
                tag=TAG_FILTER_COMBO,
                items=filter_items,
                default_value=self.state.filter_option,
                width=110,
                callback=self._on_filter_change,
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
            dpg.add_text(tag=TAG_EXIF_BAR, default_value=self.state.t("exif_empty"))
            dpg.add_spacer(width=-1)
            dpg.add_text(tag=TAG_STATUS_BAR, default_value="")

    # ─── 鍵盤 Handler ────────────────────────────────────────

    def _register_keyboard_handler(self) -> None:
        """註冊全域滑鼠事件（鍵盤改用主迴圈輪詢）。"""
        with dpg.handler_registry():
            # 滑鼠左鍵點擊（格狀視圖選取 / 雙擊進入單張模式）
            dpg.add_mouse_click_handler(button=0, callback=self._on_grid_click)

    # 記錄上一幀已按下的鍵，防止 is_key_pressed 重複觸發
    _prev_keys: set[int] = set()

    def _poll_keyboard(self) -> None:
        """每 frame 輪詢鍵盤狀態，不受 DPG 焦點影響。"""
        # 評星數字鍵：支援主鍵盤 0-5 以及右側數字鍵盤 (Numpad) 0-5
        rating_mappings = [
            (0, [dpg.mvKey_0, dpg.mvKey_NumPad0]),
            (1, [dpg.mvKey_1, dpg.mvKey_NumPad1]),
            (2, [dpg.mvKey_2, dpg.mvKey_NumPad2]),
            (3, [dpg.mvKey_3, dpg.mvKey_NumPad3]),
            (4, [dpg.mvKey_4, dpg.mvKey_NumPad4]),
            (5, [dpg.mvKey_5, dpg.mvKey_NumPad5]),
        ]
        current_pressed: set[int] = set()

        for stars, keys in rating_mappings:
            for key in keys:
                if dpg.is_key_down(key):
                    current_pressed.add(key)
                    if key not in self._prev_keys:
                        # 新按下（不是長按重複）
                        photo = self.state.current_photo
                        if photo and self.state.db:
                            photo.stars = stars
                            self.state.db.set_rating(photo.filename, stars)
                            self._update_exif_bar()
                            if self._grid_view:
                                self._grid_view.refresh_badges(photo.filename)
                            if self._analysis_panel:
                                self._analysis_panel.refresh()

        # 左右方向鍵（單張模式切換）
        for key in (dpg.mvKey_Left, dpg.mvKey_Right):
            if dpg.is_key_down(key):
                current_pressed.add(key)
                if key not in self._prev_keys:
                    if key == dpg.mvKey_Left:
                        self._on_key_left()
                    else:
                        self._on_key_right()

        self._prev_keys = current_pressed

    def _on_grid_click(self) -> None:
        """處理格狀視圖的滑鼠點擊。"""
        if self._grid_view is None or not self._grid_view._is_visible:
            return
        mx, my = dpg.get_mouse_pos(local=False)
        idx = self._grid_view.hit_test(mx, my)
        if idx >= 0:
            self._grid_view.on_click(idx)

    def _on_key_left(self) -> None:
        if self.state.view_mode == VIEW_SINGLE and self.state.preview_index > 0:
            self.state.preview_index -= 1
            self._refresh_single_view()

    def _on_key_right(self) -> None:
        if self.state.view_mode == VIEW_SINGLE:
            if self.state.preview_index < len(self.state.filtered_photos) - 1:
                self.state.preview_index += 1
                self._refresh_single_view()

    def _on_rate(self, sender, app_data, user_data) -> None:
        """評星（輪詢模式下不再使用，保留以相容）。"""
        stars = user_data
        if stars is None:
            return
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

    def _on_viewport_resize(self) -> None:
        """當視區大小改變時呼叫。"""
        if self._grid_view:
            self._grid_view.on_resize()
        if self._single_view:
            self._single_view.on_resize()
        if self._analysis_panel:
            self._analysis_panel.on_resize()

    # ─── 事件回呼 ────────────────────────────────────────────

    def _on_open_folder(self) -> None:
        """開啟資料夾選擇器。"""
        dpg.add_file_dialog(
            label=self.state.t("open_folder"),
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
        dpg.set_value(TAG_PATH_INPUT, str(folder))
        self._load_folder(folder)

    def _on_path_entered(self, sender, app_data: str) -> None:
        """手動輸入路徑按下 Enter 回呼。"""
        path_str = app_data.strip()
        if not path_str:
            return
        folder = Path(path_str)
        if folder.is_dir():
            self._load_folder(folder)
        else:
            dpg.set_value(
                TAG_EXIF_BAR,
                "路徑不存在或不是資料夾" if self.state.i18n.lang == "zh-Hant" else "Path does not exist or is not a directory"
            )

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

        # 紀錄與更新歷史選單
        self.state.add_recent_folder(folder)
        self._update_recent_menu()

        dpg.set_value(TAG_EXIF_BAR, f"{self.state.t('scanning_files')} {folder.name}...")

        # 背景掃描
        threading.Thread(target=self._scan_worker, args=(folder,), daemon=True).start()

    def _scan_worker(self, folder: Path) -> None:
        try:
            photos = scan_folder(folder)

            if not photos:
                dpg.set_value(TAG_EXIF_BAR, self.state.t("no_files_found"))
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
                dpg.set_value(TAG_EXIF_BAR, self.state.t("cache_expired"))

            # 啟動背景快取建立
            cache.start_build(
                on_progress=self._on_cache_progress,
                on_done=self._on_cache_done,
                max_workers=self.state.max_workers,
            )

            dpg.set_value(TAG_STATUS_BAR, f"{len(photos)} files" if self.state.i18n.lang == "en" else f"{len(photos)} 張")
            if self._grid_view:
                self._grid_view.load(photos)
        except Exception as e:
            import traceback
            traceback.print_exc()
            dpg.set_value(TAG_EXIF_BAR, f"Failed: {e}" if self.state.i18n.lang == "en" else f"掃描失敗：{e}")

    def _on_cache_progress(self, completed: int, total: int, filename: str) -> None:
        self.state.cache_progress = completed
        progress = completed / total if total > 0 else 0.0
        dpg.set_value(TAG_PROGRESS_BAR, progress)
        overlay_text = f"Cache {completed}/{total}" if self.state.i18n.lang == "en" else f"快取 {completed}/{total}"
        dpg.configure_item(TAG_PROGRESS_BAR, overlay=overlay_text)
        if self._grid_view:
            self._grid_view.on_thumbnail_ready(filename)

    def _on_cache_done(self) -> None:
        dpg.set_value(TAG_PROGRESS_BAR, 1.0)
        dpg.configure_item(TAG_PROGRESS_BAR, overlay="Cache Done" if self.state.i18n.lang == "en" else "快取完成")
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
        dpg.configure_item(TAG_MENU_ITEM_SCAN, label="Scanning..." if self.state.i18n.lang == "en" else "掃描中...")
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
        from concurrent.futures import ThreadPoolExecutor, as_completed

        db = self.state.db
        if not db:
            self.state.ai_scanning = False
            return
        photos = self.state.photos
        total = len(photos)

        all_scores: dict[str, dict] = {}
        scores_lock = threading.Lock()
        completed = 0
        completed_lock = threading.Lock()

        # 每個任務處理單張照片並寫入 DB
        def process_photo_ai(photo: PhotoInfo) -> tuple[str, dict[str, Any]]:
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
                
                scores = {
                    "sharpness": sharpness,
                    "exposure": exposure,
                    "motion_blur": motion_blur,
                    "eye_focus": eye_focus,
                    "has_face": has_face,
                }
                return photo.filename, scores
            except Exception:
                return photo.filename, {}

        # 啟動平行處理
        t = self.state.t
        max_workers = self.state.max_workers
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(process_photo_ai, photo): photo for photo in photos}
            for future in as_completed(futures):
                filename, scores = future.result()
                if scores:
                    with scores_lock:
                        all_scores[filename] = scores
                
                with completed_lock:
                    completed += 1
                progress = completed / total
                dpg.set_value(TAG_PROGRESS_BAR, progress)
                dpg.configure_item(TAG_PROGRESS_BAR, overlay=f"AI {completed}/{total}")

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
        dpg.configure_item(TAG_MENU_ITEM_SCAN, label=t("scan_ai"))
        dpg.set_value(TAG_PROGRESS_BAR, 1.0)
        dpg.configure_item(TAG_PROGRESS_BAR, overlay="AI Done" if self.state.i18n.lang == "en" else "AI 分析完成")

        if self._grid_view:
            self._grid_view.refresh_all()

    def _on_export(self) -> None:
        """開啟輸出對話。"""
        from pickupphoto.ui.export_dialog import show_export_dialog
        show_export_dialog(self.state)

    # ─── 語言切換與更新 ────────────────────────────────────────

    def _get_filter_items(self) -> list[str]:
        t = self.state.t
        return [
            t("all"),
            t("stars_gte", 1),
            t("stars_gte", 2),
            t("stars_gte", 3),
            t("stars_gte", 4),
            t("stars_eq", 5),
            t("stars_eq", 4),
            t("stars_eq", 3),
            t("stars_eq", 2),
            t("stars_eq", 1),
        ]

    def _on_lang_menu_select(self, lang_code: str) -> None:
        """從選單切換介面語言。"""
        if self.state.i18n.set_language(lang_code):
            self._update_ui_text()

    def _on_clear_cache(self) -> None:
        """清除當前開啟資料夾的快取並重新載入。"""
        if not self.state.folder:
            return
        if self.state.db:
            self.state.db.close()
            self.state.db = None
        from pickupphoto.core.thumbnail_cache import delete_cache
        delete_cache(self.state.folder)
        self._load_folder(self.state.folder)

    def _on_cores_change(self, sender, app_data: int) -> None:
        """調整執行緒核心數。"""
        self.state.update_max_workers(app_data)

    def _update_ui_text(self) -> None:
        """更新所有 UI 標籤與選單文字。"""
        t = self.state.t
        dpg.configure_item(TAG_PATH_INPUT, hint=t("path_hint"))
        dpg.configure_item(TAG_FILTER_LABEL, default_value=t("filter"))

        # 更新選單列文字
        dpg.configure_item(TAG_MENU_FILE, label=t("file_menu"))
        dpg.configure_item(TAG_MENU_VIEW, label=t("view_menu"))
        dpg.configure_item(TAG_MENU_TOOLS, label=t("tools_menu"))
        dpg.configure_item(TAG_MENU_LANG, label=t("lang_menu"))

        dpg.configure_item(TAG_MENU_ITEM_OPEN, label=t("open_folder"))
        dpg.configure_item(TAG_MENU_ITEM_CLEAR, label=t("clear_cache"))
        dpg.configure_item(TAG_MENU_ITEM_GRID, label=t("view_grid"))
        dpg.configure_item(TAG_MENU_ITEM_SINGLE, label=t("view_single"))
        dpg.configure_item(TAG_MENU_ITEM_SCAN, label=t("scan_ai"))
        dpg.configure_item(TAG_MENU_ITEM_EXPORT, label=t("export"))
        dpg.configure_item("menu_item_cores", label=t("cores_label"))
        dpg.configure_item(TAG_MENU_RECENT, label=t("recent_folders"))
        self._update_recent_menu()

    def _update_recent_menu(self) -> None:
        """動態更新最近開啟資料夾選單的項目。"""
        if not dpg.does_item_exist(TAG_MENU_RECENT):
            return
        dpg.delete_item(TAG_MENU_RECENT, children_only=True)

        recent = self.state.recent_folders
        if not recent:
            label = "無歷史紀錄" if self.state.i18n.lang == "zh-Hant" else "No recent folders"
            dpg.add_menu_item(label=label, parent=TAG_MENU_RECENT, enabled=False)
            return

        for path_str in recent:
            dpg.add_menu_item(
                label=path_str,
                parent=TAG_MENU_RECENT,
                callback=self._on_recent_folder_click,
                user_data=path_str,
            )
        dpg.add_separator(parent=TAG_MENU_RECENT)
        label_clear = "清除歷史紀錄" if self.state.i18n.lang == "zh-Hant" else "Clear History"
        dpg.add_menu_item(
            label=label_clear,
            parent=TAG_MENU_RECENT,
            callback=self._on_clear_recent_history,
        )

    def _on_recent_folder_click(self, sender, app_data, user_data) -> None:
        """選取歷史路徑時的回呼。"""
        path_str = user_data
        if not path_str:
            return
        folder = Path(path_str)
        if folder.is_dir():
            dpg.set_value(TAG_PATH_INPUT, path_str)
            self._load_folder(folder)
        else:
            msg = "歷史路徑已不存在" if self.state.i18n.lang == "zh-Hant" else "Recent path no longer exists"
            dpg.set_value(TAG_EXIF_BAR, msg)

    def _on_clear_recent_history(self) -> None:
        """清除最近開啟紀錄。"""
        self.state.clear_recent_history()
        self._update_recent_menu()

        # 更新篩選下拉清單內容
        items = self._get_filter_items()
        dpg.configure_item(TAG_FILTER_COMBO, items=items)

        # 重置當前篩選選擇（對應新語言）
        if self.state.filter_option not in items:
            self.state.filter_option = items[0]
            dpg.set_value(TAG_FILTER_COMBO, items[0])
            self.state.apply_filter()

        # 底部狀態列與快取進度條
        if not self.state.folder:
            dpg.set_value(TAG_EXIF_BAR, t("exif_empty"))
        else:
            dpg.set_value(TAG_STATUS_BAR, f"{len(self.state.photos)} files" if self.state.i18n.lang == "en" else f"{len(self.state.photos)} 張")
            self._update_exif_bar()

        # 刷新右側 AI 面板
        if self._analysis_panel:
            self._analysis_panel.refresh()

        # 刷新格狀縮圖 Badge 字樣
        if self._grid_view:
            self._grid_view.refresh_all()

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
