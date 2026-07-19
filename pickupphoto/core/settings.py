"""
core/settings.py — 使用者設定與多國語言 (i18n) 管理

支援：
- 讀寫 .pickupphoto_settings.json 紀錄使用者喜好 (如語言)
- 繁體中文 (zh-Hant) 與英文 (en) 翻譯字表
"""

from __future__ import annotations

import json
from pathlib import Path

SETTINGS_FILE = Path(".pickupphoto_settings.json")

# 翻譯對照表
TRANSLATIONS = {
    "zh-Hant": {
        "title": "PickUpPhoto - RAW 照片瀏覽與評分工具",
        "open_folder": "開啟資料夾",
        "view_grid": "格狀視圖",
        "view_single": "單張模式",
        "filter": "篩選：",
        "scan_ai": "執行 AI 掃描",
        "export": "匯出照片",
        "all": "全部",
        "stars_gte": "≥{}星",
        "stars_eq": "={}星",
        "exif_empty": "請開啟資料夾以開始",
        "warning_badge": "[!]",
        "ai_best_badge": "[AI最佳]",
        "ai_best_desc": "[AI最佳] 本群組 AI 最佳推薦",
        "stars_label": "星等",
        "no_ai": "尚未分析，請點擊「執行 AI 掃描」",
        "ai_analysis": "AI 分析指標",
        "sharpness": "對焦清晰",
        "exposure": "曝光正常",
        "motion_blur": "無運動模糊",
        "eye_focus": "眼睛對焦",
        "loading": "載入中...",
        "decoding": "完整解碼中...",
        "decode_btn": "完整解碼",
        "decode_success": "已完整解碼",
        "decode_failed": "解碼失敗",
        "burst_group": "連拍群組",
        "burst_single": "非連拍照片",
        "burst_info": "群組 {} (共 {} 張) - 第 {} 幀",
        "export_title": "輸出設定",
        "target_folder": "目標資料夾：",
        "browse": "瀏覽",
        "filter_cond": "篩選條件：",
        "match_count": "符合：{} 張",
        "conflict_handling": "同名衝突處理：",
        "conflict_rename": "自動重新命名",
        "conflict_skip": "跳過",
        "conflict_overwrite": "覆蓋",
        "start_export": "開始複製",
        "close": "關閉",
        "exporting": "正在複製...",
        "export_success": "完成！已複製 {} 張",
        "export_skipped": "，跳過 {} 張",
        "export_failed": "，{} 張失敗",
        "lang_label": "語言/Lang",
        "cache_expired": "快取已過期，正在重建...",
        "scanning_files": "正在掃描資料夾...",
        "no_files_found": "此資料夾未找到支援的 RAW 檔案（NEF / RAF）",
        "path_hint": "或在此輸入/貼上資料夾路徑...",
        "clear_cache": "清除目前快取",
        "file_menu": "檔案",
        "view_menu": "檢視",
        "tools_menu": "工具",
        "lang_menu": "語言",
    },
    "en": {
        "title": "PickUpPhoto - RAW Photo Browser",
        "open_folder": "Open Folder",
        "view_grid": "Grid View",
        "view_single": "Single View",
        "filter": "Filter:",
        "scan_ai": "Scan AI",
        "export": "Export",
        "all": "All",
        "stars_gte": "≥{} Star(s)",
        "stars_eq": "={} Star(s)",
        "exif_empty": "Please open a folder to start",
        "warning_badge": "[!]",
        "ai_best_badge": "[Best]",
        "ai_best_desc": "[Best] AI Recommended Best Shot",
        "stars_label": "Stars",
        "no_ai": "Not analyzed yet. Click 'Scan AI'.",
        "ai_analysis": "AI Analysis Metrics",
        "sharpness": "Focus Sharpness",
        "exposure": "Exposure Normalcy",
        "motion_blur": "No Motion Blur",
        "eye_focus": "Eye Focus",
        "loading": "Loading...",
        "decoding": "Decoding Full RAW...",
        "decode_btn": "Full Decode",
        "decode_success": "Decoded",
        "decode_failed": "Decode Failed",
        "burst_group": "Burst Group",
        "burst_single": "Single Shot",
        "burst_info": "Group {} ({} shots) - Frame {}",
        "export_title": "Export Settings",
        "target_folder": "Target Folder:",
        "browse": "Browse",
        "filter_cond": "Filter Condition:",
        "match_count": "Matches: {} file(s)",
        "conflict_handling": "Conflict Resolution:",
        "conflict_rename": "Auto Rename",
        "conflict_skip": "Skip",
        "conflict_overwrite": "Overwrite",
        "start_export": "Start Copying",
        "close": "Close",
        "exporting": "Copying files...",
        "export_success": "Done! Copied {} files",
        "export_skipped": ", skipped {} files",
        "export_failed": ", {} files failed",
        "lang_label": "Language",
        "cache_expired": "Cache expired, rebuilding...",
        "scanning_files": "Scanning folder...",
        "no_files_found": "No supported RAW files found (NEF/RAF)",
        "path_hint": "Or enter/paste folder path here...",
        "clear_cache": "Clear Current Cache",
        "file_menu": "File",
        "view_menu": "View",
        "tools_menu": "Tools",
        "lang_menu": "Language",
    }
}


def load_settings() -> dict[str, str]:
    """載入設定檔，預設使用繁體中文。"""
    default_settings = {"lang": "zh-Hant"}
    if not SETTINGS_FILE.exists():
        return default_settings

    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict) and data.get("lang") in TRANSLATIONS:
                return data
    except Exception:
        pass
    return default_settings


def save_settings(settings: dict[str, str]) -> None:
    """儲存設定檔。"""
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


class I18N:
    """國際化語言切換器。"""

    def __init__(self) -> None:
        self.settings = load_settings()
        self.lang = self.settings["lang"]

    def t(self, key: str, *args: any) -> str:
        """翻譯對應的 Key，支援格式化參數。"""
        lang_dict = TRANSLATIONS.get(self.lang, TRANSLATIONS["zh-Hant"])
        val = lang_dict.get(key, key)
        if args:
            try:
                return val.format(*args)
            except Exception:
                pass
        return val

    def set_language(self, lang: str) -> bool:
        """更換語言並儲存。"""
        if lang in TRANSLATIONS:
            self.lang = lang
            self.settings["lang"] = lang
            save_settings(self.settings)
            return True
        return False
