"""
core/raw_loader.py — RAW 檔案解碼

兩段式策略：
1. 快速路徑：讀取 embedded JPEG thumbnail（用於縮圖 + AI 分析）
2. 完整解碼：rawpy.postprocess()（使用者明確請求時）
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rawpy
from PIL import Image


# 縮圖長邊像素數
THUMBNAIL_MAX_SIZE = 256

# 主預覽長邊像素數（單張模式用，比縮圖大）
PREVIEW_MAX_SIZE = 1920


@dataclass
class LoadResult:
    """RAW 載入結果。"""

    image: np.ndarray          # HWC uint8 RGB
    width: int
    height: int
    is_fallback: bool = False  # True 代表使用 half_size fallback


# ─── 公開 API ────────────────────────────────────────────────


def load_embedded_preview(path: Path, max_size: int = PREVIEW_MAX_SIZE) -> LoadResult:
    """
    讀取 RAW 檔案的 embedded JPEG preview。

    優先使用 embedded_jpeg_thumbnail()；若不存在則 fallback 至
    half_size=True 的完整解碼（速度約 1-3 秒）。

    Args:
        path: RAW 檔案路徑
        max_size: 輸出圖像長邊最大像素數

    Returns:
        LoadResult with RGB numpy array
    """
    try:
        return _load_embedded(path, max_size)
    except (rawpy.LibRawNoThumbnailError, rawpy.LibRawUnsupportedThumbnailError):
        return _load_half_size(path, max_size)


def load_thumbnail(path: Path) -> LoadResult:
    """
    讀取縮圖（256px 長邊），用於格狀視圖快取。
    與 load_embedded_preview 相同邏輯，但限制輸出尺寸更小。
    """
    return load_embedded_preview(path, max_size=THUMBNAIL_MAX_SIZE)


def load_full_decode(path: Path) -> LoadResult:
    """
    完整 RAW 解碼，使用相機白平衡。
    速度較慢（3-8 秒），僅在使用者明確請求時呼叫。

    Returns:
        LoadResult with full-resolution RGB numpy array
    """
    with rawpy.imread(str(path)) as raw:
        rgb = raw.postprocess(
            use_camera_wb=True,
            half_size=False,
            no_auto_bright=False,
            output_bps=8,
        )
    h, w = rgb.shape[:2]
    return LoadResult(image=rgb, width=w, height=h, is_fallback=False)


def numpy_to_jpeg_bytes(arr: np.ndarray, quality: int = 85) -> bytes:
    """將 numpy RGB array 轉為 JPEG bytes（用於快取儲存）。"""
    img = Image.fromarray(arr)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def jpeg_bytes_to_numpy(data: bytes) -> np.ndarray:
    """將 JPEG bytes 轉為 numpy RGB array（從快取讀出時用）。"""
    img = Image.open(io.BytesIO(data)).convert("RGB")
    return np.array(img, dtype=np.uint8)


def resize_to_max(arr: np.ndarray, max_size: int) -> np.ndarray:
    """
    等比縮放至長邊 <= max_size，保持長寬比。
    若圖像已小於 max_size 則直接回傳（不放大）。
    """
    h, w = arr.shape[:2]
    if max(h, w) <= max_size:
        return arr
    if w >= h:
        new_w = max_size
        new_h = int(h * max_size / w)
    else:
        new_h = max_size
        new_w = int(w * max_size / h)
    img = Image.fromarray(arr).resize((new_w, new_h), Image.LANCZOS)
    return np.array(img, dtype=np.uint8)


# ─── 內部實作 ────────────────────────────────────────────────


def _load_embedded(path: Path, max_size: int) -> LoadResult:
    """
    讀取 embedded JPEG thumbnail，
    raises LibRawNoThumbnailError 或 LibRawUnsupportedThumbnailError 表示不存在。
    """
    with rawpy.imread(str(path)) as raw:
        thumb = raw.extract_thumb()

    if thumb.format == rawpy.ThumbFormat.JPEG:
        img = Image.open(io.BytesIO(thumb.data)).convert("RGB")
        arr = np.array(img, dtype=np.uint8)
    elif thumb.format == rawpy.ThumbFormat.BITMAP:
        arr = np.array(Image.fromarray(thumb.data).convert("RGB"), dtype=np.uint8)
    else:
        raise rawpy.LibRawUnsupportedThumbnailError("Unsupported thumbnail format")

    arr = resize_to_max(arr, max_size)
    h, w = arr.shape[:2]
    return LoadResult(image=arr, width=w, height=h, is_fallback=False)


def _load_half_size(path: Path, max_size: int) -> LoadResult:
    """
    Fallback：以 half_size=True 完整解碼（速度中等）。
    用於無 embedded thumbnail 的 RAF 檔案。
    """
    with rawpy.imread(str(path)) as raw:
        rgb = raw.postprocess(
            use_camera_wb=True,
            half_size=True,
            no_auto_bright=False,
            output_bps=8,
        )
    arr = resize_to_max(rgb, max_size)
    h, w = arr.shape[:2]
    return LoadResult(image=arr, width=w, height=h, is_fallback=True)
