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

    t = state.t

    with dpg.window(
        tag=TAG_EXPORT_DIALOG,
        label=t("export_title"),
        modal=True,
        width=520,
        height=380,
        pos=(200, 150),
        no_resize=True,
    ):
        dpg.add_text(t("target_folder"))
        with dpg.group(horizontal=True):
            dpg.add_input_text(
                tag=TAG_DEST_INPUT,
                default_value=str(Path.home() / "Desktop" / "PickUpPhoto_Export"),
                width=380,
            )
            dpg.add_button(
                label=t("browse"),
                callback=lambda: [
                    dpg.configure_item(TAG_EXPORT_DIALOG, show=False),
                    dpg.add_file_dialog(
                        label=t("target_folder"),
                        directory_selector=True,
                        show=True,
                        callback=_on_dest_selected,
                        cancel_callback=_on_dest_cancel,
                        width=600,
                        height=400,
                    )
                ],
                width=70,
            )

        dpg.add_spacer(height=10)
        dpg.add_separator()
        dpg.add_spacer(height=6)

        dpg.add_text(t("filter_cond"))
        with dpg.group(horizontal=True):
            dpg.add_combo(
                tag=TAG_FILTER_MODE_COMBO,
                items=["≥", "="],
                default_value="≥",
                width=80,
                callback=_update_preview,
                user_data=state,
            )
            dpg.add_combo(
                tag=TAG_FILTER_STARS_COMBO,
                items=["1", "2", "3", "4", "5"],
                default_value="3",
                width=60,
                callback=_update_preview,
                user_data=state,
            )
            dpg.add_spacer(width=10)
            dpg.add_text(tag=TAG_PREVIEW_COUNT, default_value="")

        dpg.add_spacer(height=8)
        dpg.add_text(t("conflict_handling"))
        dpg.add_combo(
            tag=TAG_CONFLICT_COMBO,
            items=[t("conflict_rename"), t("conflict_skip"), t("conflict_overwrite")],
            default_value=t("conflict_rename"),
            width=180,
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
                label=t("start_export"),
                callback=lambda: _start_export(state),
                width=130,
            )
            dpg.add_spacer(width=10)
            dpg.add_button(
                label=t("close"),
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
    # 重新顯示主匯出視窗並刪除已關閉的 file_dialog
    if dpg.does_item_exist(TAG_EXPORT_DIALOG):
        dpg.configure_item(TAG_EXPORT_DIALOG, show=True)
    dpg.delete_item(sender)


def _on_dest_cancel(sender, app_data) -> None:
    # 使用者取消時，也必須還原主匯出視窗
    if dpg.does_item_exist(TAG_EXPORT_DIALOG):
        dpg.configure_item(TAG_EXPORT_DIALOG, show=True)
    dpg.delete_item(sender)


def _update_preview(sender, app_data, state: "AppState") -> None:
    """更新符合數量預覽。"""
    t = state.t
    if not state.photos:
        dpg.set_value(TAG_PREVIEW_COUNT, t("match_count", 0))
        return

    mode = _get_filter_mode()
    stars = _get_filter_stars()
    matched = filter_photos(state.photos, mode, stars)
    dpg.set_value(TAG_PREVIEW_COUNT, t("match_count", len(matched)))

    # 0 張時禁用開始按鈕
    dpg.configure_item(TAG_EXPORT_START_BTN, enabled=len(matched) > 0)


def _start_export(state: "AppState") -> None:
    """開始複製流程（背景執行緒）。"""
    t = state.t
    dest_str = dpg.get_value(TAG_DEST_INPUT).strip()
    if not dest_str:
        dpg.set_value(TAG_EXPORT_STATUS, "Please specify a target folder" if state.i18n.lang == "en" else "請指定目標資料夾")
        return

    mode = _get_filter_mode()
    stars = _get_filter_stars()
    conflict = _get_conflict_action(t)

    matched = filter_photos(state.photos, mode, stars)
    if not matched:
        dpg.set_value(TAG_EXPORT_STATUS, t("match_count", 0))
        return

    config = ExportConfig(
        target_folder=Path(dest_str),
        filter_mode=mode,
        filter_stars=stars,
        conflict_action=conflict,
    )

    dpg.configure_item(TAG_EXPORT_START_BTN, enabled=False)
    dpg.set_value(TAG_EXPORT_STATUS, t("exporting"))
    dpg.set_value(TAG_EXPORT_PROGRESS, 0.0)

    threading.Thread(
        target=_export_worker,
        args=(state, matched, config),
        daemon=True,
    ).start()


def _export_worker(state: "AppState", photos, config: ExportConfig) -> None:
    total = len(photos)
    t = state.t

    def on_progress(completed: int, total: int, filename: str) -> None:
        dpg.set_value(TAG_EXPORT_PROGRESS, completed / total)
        dpg.configure_item(TAG_EXPORT_PROGRESS, overlay=f"{completed}/{total}")

    result = export_photos(photos, config, on_progress=on_progress)

    dpg.set_value(TAG_EXPORT_PROGRESS, 1.0)
    summary = t("export_success", len(result.copied))
    if result.skipped:
        summary += t("export_skipped", len(result.skipped))
    if result.errors:
        summary += t("export_failed", len(result.errors))
    dpg.set_value(TAG_EXPORT_STATUS, summary)
    dpg.configure_item(TAG_EXPORT_START_BTN, enabled=True)


def _get_filter_mode() -> FilterMode:
    val = dpg.get_value(TAG_FILTER_MODE_COMBO)
    return FilterMode.GTE if val == "≥" else FilterMode.EQ


def _get_filter_stars() -> int:
    val = dpg.get_value(TAG_FILTER_STARS_COMBO)
    return int(val)


def _get_conflict_action(t) -> ConflictAction:
    val = dpg.get_value(TAG_CONFLICT_COMBO)
    if val == t("conflict_skip"):
        return ConflictAction.SKIP
    elif val == t("conflict_overwrite"):
        return ConflictAction.OVERWRITE
    return ConflictAction.RENAME
