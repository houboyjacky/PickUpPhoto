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
TAG_SCORE_SHARP = "score_sharpness"
TAG_SCORE_EXPOSURE = "score_exposure"
TAG_SCORE_BLUR = "score_motion_blur"
TAG_SCORE_EYE = "score_eye_focus"
TAG_BURST_INFO = "burst_info_text"
TAG_AI_BEST_TEXT = "ai_best_text"
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

        with dpg.child_window(
            tag=TAG_PANEL_WINDOW,
            parent=parent,
            border=True,
            width=280,
            height=vp_h,
            pos=(dpg.get_viewport_client_width() - 290, 42),
        ):
            dpg.add_text("AI 分析", color=(180, 200, 255, 255))
            dpg.add_separator()
            dpg.add_spacer(height=4)

            # 各分析分數
            for label, tag, tip in [
                ("🔭 對焦清晰", TAG_SCORE_SHARP, "Laplacian variance"),
                ("☀️ 曝光正常", TAG_SCORE_EXPOSURE, "直方圖分析"),
                ("🏃 無運動模糊", TAG_SCORE_BLUR, "方向性邊緣"),
                ("👁 眼睛對焦", TAG_SCORE_EYE, "MediaPipe FaceMesh"),
            ]:
                dpg.add_text(label, color=(160, 175, 210, 255))
                dpg.add_progress_bar(
                    tag=tag,
                    default_value=0.0,
                    width=-1,
                    overlay="—",
                )
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
            dpg.add_text("⭐ 星等", color=(160, 175, 210, 255))
            dpg.add_text(tag=TAG_PANEL_STARS, default_value="☆☆☆☆☆", color=(255, 200, 50, 255))
            dpg.add_spacer(height=4)

            # 未分析提示
            dpg.add_text(
                tag=TAG_NO_AI_TEXT,
                default_value="尚未分析\n請按「🤖 掃描 AI」",
                color=(140, 140, 160, 200),
                wrap=260,
            )

        self._built = True

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

        # 眼睛對焦（可選）
        if scores and self._state.ai_use_eye_focus:
            ef = scores.get("eye_focus")
            has_face = scores.get("has_face")
            if ef is not None:
                dpg.set_value(TAG_SCORE_EYE, float(ef) / 100.0)
                dpg.configure_item(TAG_SCORE_EYE, overlay=f"{float(ef):.0f}%")
            elif has_face == 0:
                dpg.set_value(TAG_SCORE_EYE, 0.0)
                dpg.configure_item(TAG_SCORE_EYE, overlay="無人臉偵測")
            else:
                dpg.set_value(TAG_SCORE_EYE, 0.0)
                dpg.configure_item(TAG_SCORE_EYE, overlay="—")
        else:
            dpg.set_value(TAG_SCORE_EYE, 0.0)
            dpg.configure_item(TAG_SCORE_EYE, overlay="（未啟用）")

        # 連拍群組資訊
        burst = db.get_burst_group(photo.filename)
        if burst:
            gid = burst["group_id"]
            size = burst["group_size"]
            rank = burst["group_rank"]
            dpg.set_value(TAG_BURST_INFO, f"群組 {gid}（{size} 張）  第 {rank} 幀")
            if burst["ai_best"]:
                dpg.set_value(TAG_AI_BEST_TEXT, "🏆 本群組 AI 推薦最佳")
            else:
                dpg.set_value(TAG_AI_BEST_TEXT, "")
        else:
            dpg.set_value(TAG_BURST_INFO, "非連拍群組")
            dpg.set_value(TAG_AI_BEST_TEXT, "")

        # 星等
        stars_str = "★" * photo.stars + "☆" * (5 - photo.stars)
        dpg.set_value(TAG_PANEL_STARS, stars_str)

    def _clear(self) -> None:
        """清空面板。"""
        for tag in [TAG_SCORE_SHARP, TAG_SCORE_EXPOSURE, TAG_SCORE_BLUR, TAG_SCORE_EYE]:
            dpg.set_value(tag, 0.0)
            dpg.configure_item(tag, overlay="—")
        dpg.set_value(TAG_BURST_INFO, "")
        dpg.set_value(TAG_AI_BEST_TEXT, "")
        dpg.set_value(TAG_PANEL_STARS, "☆☆☆☆☆")
        dpg.configure_item(TAG_NO_AI_TEXT, show=True)
