"""
ui/analysis_panel.py — 右側 AI 分析面板（單張模式）

顯示：
- 各項 AI 分數（進度條形式）
- 連拍群組資訊
- 🏆 AI 推薦標記
- 星等顯示
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import dearpygui.dearpygui as dpg

if TYPE_CHECKING:
    from pickupphoto.ui.app import AppState

TAG_PANEL_WINDOW = "analysis_panel_window"
TAG_PANEL_TITLE = "analysis_panel_title"
TAG_LABEL_SHARP = "analysis_label_sharpness"
TAG_LABEL_EXPOSURE = "analysis_label_exposure"
TAG_LABEL_BLUR = "analysis_label_blur"
TAG_LABEL_EYE = "analysis_label_eye"
TAG_SCORE_SHARP = "score_sharpness"
TAG_SCORE_EXPOSURE = "score_exposure"
TAG_SCORE_BLUR = "score_motion_blur"
TAG_SCORE_EYE = "score_eye_focus"
TAG_BURST_INFO = "burst_info_text"
TAG_AI_BEST_TEXT = "ai_best_text"
TAG_LABEL_STARS = "analysis_label_stars"
TAG_PANEL_STARS = "panel_stars_text"
TAG_NO_AI_TEXT = "no_ai_text"


class AnalysisPanel:
    """右側 AI 分析面板。"""

    def __init__(self, state: "AppState") -> None:
        self._state = state
        self._built = False

    def _build(self) -> None:
        """建立面板 DPG 元件（固定在右側）。"""
        if self._built:
            return

        parent = "main_window"
        if not dpg.does_item_exist(parent):
            return

        vp_h = dpg.get_viewport_client_height() - 50
        t = self._state.t

        with dpg.child_window(
            tag=TAG_PANEL_WINDOW,
            parent=parent,
            border=True,
            width=280,
            height=vp_h,
            pos=(dpg.get_viewport_client_width() - 290, 42),
        ):
            dpg.add_text(t("ai_analysis"), tag=TAG_PANEL_TITLE, color=(180, 200, 255, 255))
            dpg.add_separator()
            dpg.add_spacer(height=4)

            # 各分析分數
            dpg.add_text(t("sharpness"), tag=TAG_LABEL_SHARP, color=(160, 175, 210, 255))
            dpg.add_progress_bar(tag=TAG_SCORE_SHARP, default_value=0.0, width=-1, overlay="—")
            dpg.add_spacer(height=2)

            dpg.add_text(t("exposure"), tag=TAG_LABEL_EXPOSURE, color=(160, 175, 210, 255))
            dpg.add_progress_bar(tag=TAG_SCORE_EXPOSURE, default_value=0.0, width=-1, overlay="—")
            dpg.add_spacer(height=2)

            dpg.add_text(t("motion_blur"), tag=TAG_LABEL_BLUR, color=(160, 175, 210, 255))
            dpg.add_progress_bar(tag=TAG_SCORE_BLUR, default_value=0.0, width=-1, overlay="—")
            dpg.add_spacer(height=2)

            dpg.add_text(t("eye_focus"), tag=TAG_LABEL_EYE, color=(160, 175, 210, 255))
            dpg.add_progress_bar(tag=TAG_SCORE_EYE, default_value=0.0, width=-1, overlay="—")
            dpg.add_spacer(height=2)

            dpg.add_separator()
            dpg.add_spacer(height=4)

            # 連拍群組資訊
            dpg.add_text(tag=TAG_BURST_INFO, default_value="", wrap=260)
            dpg.add_text(tag=TAG_AI_BEST_TEXT, default_value="", color=(255, 215, 0, 255))
            dpg.add_spacer(height=4)
            dpg.add_separator()
            dpg.add_spacer(height=4)

            # 星等
            dpg.add_text(t("stars_label"), tag=TAG_LABEL_STARS, color=(160, 175, 210, 255))
            dpg.add_text(tag=TAG_PANEL_STARS, default_value="☆ ☆ ☆ ☆ ☆", color=(255, 200, 50, 255))
            # 取得 app 實作的 large_font 並綁定
            app = self._state
            large_font = getattr(app, "large_font", None)
            if large_font and dpg.does_item_exist(TAG_PANEL_STARS):
                dpg.bind_item_font(TAG_PANEL_STARS, large_font)
            dpg.add_spacer(height=4)

            # 未分析提示
            dpg.add_text(
                tag=TAG_NO_AI_TEXT,
                default_value=t("no_ai"),
                color=(140, 140, 160, 200),
                wrap=260,
            )

        self._built = True

    def on_resize(self) -> None:
        """視窗縮放時重新計算面板位置與高度，使其保持貼右對齊。"""
        if not self._built or not dpg.does_item_exist(TAG_PANEL_WINDOW):
            return
        vp_w = dpg.get_viewport_client_width()
        vp_h = dpg.get_viewport_client_height()
        new_x = vp_w - 290
        new_h = vp_h - 50
        dpg.configure_item(TAG_PANEL_WINDOW, pos=(new_x, 42), height=new_h)

    def refresh(self) -> None:
        """更新面板顯示，依當前照片狀態填入資料。"""
        if not self._built:
            self._build()
        if not self._built:
            return

        photo = self._state.current_photo
        if photo is None:
            self._clear()
            return

        db = self._state.db
        if db is None:
            self._clear()
            return

        # AI 分數
        scores = db.get_ai_scores(photo.filename)
        has_scores = scores is not None

        dpg.configure_item(TAG_NO_AI_TEXT, show=not has_scores)

        for score_val, tag in [
            (scores.get("sharpness") if scores else None, TAG_SCORE_SHARP),
            (scores.get("exposure") if scores else None, TAG_SCORE_EXPOSURE),
            (scores.get("motion_blur") if scores else None, TAG_SCORE_BLUR),
        ]:
            if score_val is not None:
                val = float(score_val) / 100.0
                pct = f"{float(score_val):.0f}%"
                dpg.set_value(tag, val)
                dpg.configure_item(tag, overlay=pct)
            else:
                dpg.set_value(tag, 0.0)
                dpg.configure_item(tag, overlay="—")

        t = self._state.t

        # 眼睛對焦（可選）
        if scores and self._state.ai_use_eye_focus:
            ef = scores.get("eye_focus")
            has_face = scores.get("has_face")
            if ef is not None:
                dpg.set_value(TAG_SCORE_EYE, float(ef) / 100.0)
                dpg.configure_item(TAG_SCORE_EYE, overlay=f"{float(ef):.0f}%")
            elif has_face == 0:
                dpg.set_value(TAG_SCORE_EYE, 0.0)
                dpg.configure_item(TAG_SCORE_EYE, overlay="No face detected" if self._state.i18n.lang == "en" else "無人臉偵測")
            else:
                dpg.set_value(TAG_SCORE_EYE, 0.0)
                dpg.configure_item(TAG_SCORE_EYE, overlay="—")
        else:
            dpg.set_value(TAG_SCORE_EYE, 0.0)
            dpg.configure_item(TAG_SCORE_EYE, overlay="Disabled" if self._state.i18n.lang == "en" else "（未啟用）")

        # 連拍群組資訊
        burst = db.get_burst_group(photo.filename)
        if burst:
            gid = burst["group_id"]
            size = burst["group_size"]
            rank = burst["group_rank"]
            dpg.set_value(TAG_BURST_INFO, t("burst_info", gid, size, rank))
            if burst["ai_best"]:
                dpg.set_value(TAG_AI_BEST_TEXT, t("ai_best_desc"))
            else:
                dpg.set_value(TAG_AI_BEST_TEXT, "")
        else:
            dpg.set_value(TAG_BURST_INFO, t("burst_single"))
            dpg.set_value(TAG_AI_BEST_TEXT, "")

        # 更新面板標題與靜態標籤字型（支援動態切換語言）
        dpg.configure_item(TAG_PANEL_TITLE, default_value=t("ai_analysis"))
        dpg.configure_item(TAG_LABEL_SHARP, default_value=t("sharpness"))
        dpg.configure_item(TAG_LABEL_EXPOSURE, default_value=t("exposure"))
        dpg.configure_item(TAG_LABEL_BLUR, default_value=t("motion_blur"))
        dpg.configure_item(TAG_LABEL_EYE, default_value=t("eye_focus"))
        dpg.configure_item(TAG_LABEL_STARS, default_value=t("stars_label"))
        dpg.configure_item(TAG_NO_AI_TEXT, default_value=t("no_ai"))

        # 星等
        stars_list = ["★"] * photo.stars + ["☆"] * (5 - photo.stars)
        stars_str = " ".join(stars_list)
        dpg.set_value(TAG_PANEL_STARS, stars_str)

    def _clear(self) -> None:
        """清空面板。"""
        for tag in [TAG_SCORE_SHARP, TAG_SCORE_EXPOSURE, TAG_SCORE_BLUR, TAG_SCORE_EYE]:
            dpg.set_value(tag, 0.0)
            dpg.configure_item(tag, overlay="—")
        dpg.set_value(TAG_BURST_INFO, "")
        dpg.set_value(TAG_AI_BEST_TEXT, "")
        dpg.set_value(TAG_PANEL_STARS, "☆ ☆ ☆ ☆ ☆")
        dpg.configure_item(TAG_NO_AI_TEXT, show=True)
