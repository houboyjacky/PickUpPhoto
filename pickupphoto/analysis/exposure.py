"""
analysis/exposure.py — 曝光問題分析

使用亮度直方圖偵測過曝（highlight clipping）與欠曝（shadow clipping）。
輸出「曝光正常分」0-100，分數越高代表曝光越正常。
"""

from __future__ import annotations

import numpy as np


# 判定過曝的像素值閾值（0-255）
_HIGHLIGHT_THRESHOLD = 245
# 超過此比例像素在閾值以上則視為過曝
_HIGHLIGHT_CLIP_RATIO = 0.05  # 5%

# 判定欠曝的像素值閾值
_SHADOW_THRESHOLD = 10
# 超過此比例像素在閾值以下則視為欠曝
_SHADOW_CLIP_RATIO = 0.30  # 30%


def compute_exposure(image: np.ndarray) -> float:
    """
    計算曝光正常分（0-100）。
    分數越高代表曝光越正常；過曝或欠曝都會降低分數。

    Args:
        image: RGB uint8 numpy array，形狀 (H, W, 3)

    Returns:
        曝光分數 0.0–100.0
    """
    lum = _luminance(image)
    total_pixels = lum.size

    highlight_ratio = float(np.sum(lum >= _HIGHLIGHT_THRESHOLD) / total_pixels)
    shadow_ratio = float(np.sum(lum <= _SHADOW_THRESHOLD) / total_pixels)

    # 各自計算扣分（線性）
    highlight_penalty = min(highlight_ratio / _HIGHLIGHT_CLIP_RATIO, 1.0)
    shadow_penalty = min(shadow_ratio / _SHADOW_CLIP_RATIO, 1.0)

    # 取最大懲罰，避免雙重扣分（同一張不太可能同時過曝又欠曝）
    max_penalty = max(highlight_penalty, shadow_penalty)
    return round(max(0.0, (1.0 - max_penalty) * 100.0), 2)


def exposure_details(image: np.ndarray) -> dict[str, float]:
    """
    回傳詳細曝光資訊，用於除錯或 UI 顯示。

    Returns:
        {
            "score": 0-100,
            "highlight_ratio": 0-1,
            "shadow_ratio": 0-1,
            "mean_brightness": 0-255,
        }
    """
    lum = _luminance(image)
    total = lum.size
    highlight_ratio = float(np.sum(lum >= _HIGHLIGHT_THRESHOLD) / total)
    shadow_ratio = float(np.sum(lum <= _SHADOW_THRESHOLD) / total)

    highlight_penalty = min(highlight_ratio / _HIGHLIGHT_CLIP_RATIO, 1.0)
    shadow_penalty = min(shadow_ratio / _SHADOW_CLIP_RATIO, 1.0)
    max_penalty = max(highlight_penalty, shadow_penalty)
    score = max(0.0, (1.0 - max_penalty) * 100.0)

    return {
        "score": round(score, 2),
        "highlight_ratio": round(highlight_ratio, 4),
        "shadow_ratio": round(shadow_ratio, 4),
        "mean_brightness": round(float(np.mean(lum)), 2),
    }


def _luminance(image: np.ndarray) -> np.ndarray:
    """計算亮度通道（使用感知加權）。"""
    if image.ndim == 2:
        return image.astype(np.float32)
    return (
        0.299 * image[:, :, 0].astype(np.float32)
        + 0.587 * image[:, :, 1].astype(np.float32)
        + 0.114 * image[:, :, 2].astype(np.float32)
    )
