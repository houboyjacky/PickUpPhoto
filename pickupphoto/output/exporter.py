"""
output/exporter.py — RAW 檔案輸出邏輯

依星等條件篩選照片清單並複製原始 RAW 檔案到目標資料夾。
不做任何格式轉換，位元完全相同。
"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Generator

from pickupphoto.core.scanner import PhotoInfo


class FilterMode(Enum):
    GTE = ">="   # 大於等於
    EQ = "="     # 等於


class ConflictAction(Enum):
    SKIP = "skip"
    OVERWRITE = "overwrite"
    RENAME = "rename"


@dataclass
class ExportConfig:
    """輸出設定。"""
    target_folder: Path
    filter_mode: FilterMode = FilterMode.GTE
    filter_stars: int = 3
    conflict_action: ConflictAction = ConflictAction.RENAME


@dataclass
class ExportResult:
    """輸出結果摘要。"""
    copied: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.copied) + len(self.skipped) + len(self.errors)


def filter_photos(
    photos: list[PhotoInfo],
    mode: FilterMode,
    stars: int,
) -> list[PhotoInfo]:
    """
    依星等條件篩選照片清單。

    Args:
        photos: 全部照片清單
        mode: GTE（≥N）或 EQ（=N）
        stars: 星等數（1-5）

    Returns:
        符合條件的照片清單
    """
    if mode == FilterMode.GTE:
        return [p for p in photos if p.stars >= stars]
    else:  # EQ
        return [p for p in photos if p.stars == stars]


def export_photos(
    photos: list[PhotoInfo],
    config: ExportConfig,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> ExportResult:
    """
    複製符合條件的照片到目標資料夾。

    Args:
        photos: 已篩選的照片清單
        config: 輸出設定
        on_progress: 進度回呼 (completed, total, filename)

    Returns:
        ExportResult 摘要
    """
    config.target_folder.mkdir(parents=True, exist_ok=True)
    result = ExportResult()
    total = len(photos)

    for i, photo in enumerate(photos):
        dest = _resolve_dest(photo, config)
        try:
            if dest is None:
                # skip
                result.skipped.append(photo.filename)
            else:
                shutil.copy2(str(photo.path), str(dest))
                result.copied.append(photo.filename)
        except Exception as e:
            result.errors.append((photo.filename, str(e)))

        if on_progress:
            on_progress(i + 1, total, photo.filename)

    return result


def _resolve_dest(photo: PhotoInfo, config: ExportConfig) -> Path | None:
    """
    計算目標路徑，依衝突策略決定：
    - SKIP：若已存在回傳 None
    - OVERWRITE：直接覆蓋
    - RENAME：加數字後綴（img.NEF → img_1.NEF → img_2.NEF ...）
    """
    dest = config.target_folder / photo.filename
    if not dest.exists():
        return dest

    if config.conflict_action == ConflictAction.SKIP:
        return None
    elif config.conflict_action == ConflictAction.OVERWRITE:
        return dest
    else:  # RENAME
        stem = photo.path.stem
        suffix = photo.path.suffix
        counter = 1
        while True:
            candidate = config.target_folder / f"{stem}_{counter}{suffix}"
            if not candidate.exists():
                return candidate
            counter += 1


def verify_copy_integrity(src: Path, dest: Path) -> bool:
    """
    驗證複製完整性（MD5 比對）。
    用於測試或使用者請求驗證時呼叫。
    """
    def md5(path: Path) -> str:
        h = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    return md5(src) == md5(dest)
