"""
ui/export_dialog.py — 輸出設定對話框

功能：
- 選擇目標資料夾
- 設定星等篩選條件（≥N 或 =N）
- 顯示符合數量預覽
- 執行複製並顯示進度
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING

import dearpygui.dearpygui as dpg

from pickupphoto.output.exporter import (
    ConflictAction,
    ExportConfig,
    FilterMode,
    export_photos,
    filter_photos,
)

if TYPE_CHECKING:
    from pickupphoto.ui.app import AppState

TAG_EXPORT_DIALOG = "export_dialog"
TAG_DEST_INPUT = "export_dest_input"
TAG_FILTER_MODE_COMBO = "export_filter_mode"
TAG_FILTER_STARS_COMBO = "export_filter_stars"
TAG_PREVIEW_COUNT = "export_preview_count"
TAG_EXPORT_PROGRESS = "export_progress_bar"
TAG_EXPORT_START_BTN = "export_start_btn"
TAG_EXPORT_STATUS = "export_status_text"
TAG_CONFLICT_COMBO = "export_conflict_combo"


def show_export_dialog(state: "AppState") -> None:
    """顯示輸出對話框。"""
    if dpg.does_item_exist(TAG_EXPORT_DIALOG):
        dpg.delete_item(TAG_EXPORT_DIALOG)

    with dpg.window(
        tag=TAG_EXPORT_DIALOG,
        label="📤 輸出設定",
        modal=True,
        width=520,
        height=380,
        pos=(200, 150),
        no_resize=True,
    ):
        dpg.add_text("目標資料夾：")
        with dpg.group(horizontal=True):
            dpg.add_input_text(
                tag=TAG_DEST_INPUT,
                default_value=str(Path.home() / "Desktop" / "PickUpPhoto_Export"),
                width=380,
            )
            dpg.add_button(
                label="瀏覽",
                callback=lambda: dpg.add_file_dialog(
                    label="選擇目標資料夾",
                    directory_selector=True,
                    show=True,
                    callback=_on_dest_selected,
                    width=600,
                    height=400,
                ),
                width=70,
            )

        dpg.add_spacer(height=10)
        dpg.add_separator()
        dpg.add_spacer(height=6)

        dpg.add_text("篩選條件：")
        with dpg.group(horizontal=True):
            dpg.add_combo(
                tag=TAG_FILTER_MODE_COMBO,
                items=["≥（大於等於）", "=（等於）"],
                default_value="≥（大於等於）",
                width=160,
                callback=_update_preview,
                user_data=state,
            )
            dpg.add_combo(
                tag=TAG_FILTER_STARS_COMBO,
                items=["1★", "2★", "3★", "4★", "5★"],
                default_value="3★",
                width=80,
                callback=_update_preview,
                user_data=state,
            )
            dpg.add_spacer(width=10)
            dpg.add_text(tag=TAG_PREVIEW_COUNT, default_value="符合：— 張")

        dpg.add_spacer(height=8)
        dpg.add_text("同名衝突處理：")
        dpg.add_combo(
            tag=TAG_CONFLICT_COMBO,
            items=["自動重命名", "跳過", "覆蓋"],
            default_value="自動重命名",
            width=160,
        )

        dpg.add_spacer(height=10)
        dpg.add_separator()
        dpg.add_spacer(height=6)

        dpg.add_progress_bar(
            tag=TAG_EXPORT_PROGRESS,
            default_value=0.0,
            width=-1,
            overlay="",
        )
        dpg.add_text(tag=TAG_EXPORT_STATUS, default_value="", wrap=480)

        dpg.add_spacer(height=8)
        with dpg.group(horizontal=True):
            dpg.add_button(
                tag=TAG_EXPORT_START_BTN,
                label="▶ 開始複製",
                callback=lambda: _start_export(state),
                width=130,
            )
            dpg.add_spacer(width=10)
            dpg.add_button(
                label="關閉",
                callback=lambda: dpg.delete_item(TAG_EXPORT_DIALOG),
                width=80,
            )

    # 初始化預覽
    _update_preview(None, None, state)


def _on_dest_selected(sender, app_data: dict) -> None:
    selections = app_data.get("selections", {})
    if selections:
        path = list(selections.values())[0]
        dpg.set_value(TAG_DEST_INPUT, path)


def _update_preview(sender, app_data, state: "AppState") -> None:
    """更新符合數量預覽。"""
    if not state.photos:
        dpg.set_value(TAG_PREVIEW_COUNT, "符合：0 張")
        return

    mode = _get_filter_mode()
    stars = _get_filter_stars()
    matched = filter_photos(state.photos, mode, stars)
    dpg.set_value(TAG_PREVIEW_COUNT, f"符合：{len(matched)} 張")

    # 0 張時禁用開始按鈕
    dpg.configure_item(TAG_EXPORT_START_BTN, enabled=len(matched) > 0)


def _start_export(state: "AppState") -> None:
    """開始複製流程（背景執行緒）。"""
    dest_str = dpg.get_value(TAG_DEST_INPUT).strip()
    if not dest_str:
        dpg.set_value(TAG_EXPORT_STATUS, "⚠️ 請指定目標資料夾")
        return

    mode = _get_filter_mode()
    stars = _get_filter_stars()
    conflict = _get_conflict_action()

    matched = filter_photos(state.photos, mode, stars)
    if not matched:
        dpg.set_value(TAG_EXPORT_STATUS, "無符合條件的照片")
        return

    config = ExportConfig(
        target_folder=Path(dest_str),
        filter_mode=mode,
        filter_stars=stars,
        conflict_action=conflict,
    )

    dpg.configure_item(TAG_EXPORT_START_BTN, enabled=False)
    dpg.set_value(TAG_EXPORT_STATUS, "複製中...")
    dpg.set_value(TAG_EXPORT_PROGRESS, 0.0)

    threading.Thread(
        target=_export_worker,
        args=(matched, config),
        daemon=True,
    ).start()


def _export_worker(photos, config: ExportConfig) -> None:
    total = len(photos)

    def on_progress(completed: int, total: int, filename: str) -> None:
        dpg.set_value(TAG_EXPORT_PROGRESS, completed / total)
        dpg.configure_item(TAG_EXPORT_PROGRESS, overlay=f"{completed}/{total}")

    result = export_photos(photos, config, on_progress=on_progress)

    dpg.set_value(TAG_EXPORT_PROGRESS, 1.0)
    summary = f"✅ 完成！已複製 {len(result.copied)} 張"
    if result.skipped:
        summary += f"，跳過 {len(result.skipped)} 張"
    if result.errors:
        summary += f"，{len(result.errors)} 張失敗"
    dpg.set_value(TAG_EXPORT_STATUS, summary)
    dpg.configure_item(TAG_EXPORT_START_BTN, enabled=True)


def _get_filter_mode() -> FilterMode:
    val = dpg.get_value(TAG_FILTER_MODE_COMBO)
    return FilterMode.GTE if val.startswith("≥") else FilterMode.EQ


def _get_filter_stars() -> int:
    val = dpg.get_value(TAG_FILTER_STARS_COMBO)
    return int(val[0])


def _get_conflict_action() -> ConflictAction:
    val = dpg.get_value(TAG_CONFLICT_COMBO)
    if val == "跳過":
        return ConflictAction.SKIP
    elif val == "覆蓋":
        return ConflictAction.OVERWRITE
    return ConflictAction.RENAME
