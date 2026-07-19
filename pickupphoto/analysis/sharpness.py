"""
analysis/sharpness.py — 對焦清晰度分析

使用 Laplacian variance 計算圖像清晰度。
分數越高代表越清晰，正規化至 0-100。
"""

from __future__ import annotations

import numpy as np


# Laplacian variance 對應 100 分的飽和值（實驗調校）
_LAPLACIAN_SATURATION = 2000.0


def compute_sharpness(image: np.ndarray) -> float:
    """
    計算圖像對焦清晰度分數（0-100）。

    Args:
        image: RGB uint8 numpy array，形狀 (H, W, 3) 或灰階 (H, W)

    Returns:
        清晰度分數 0.0–100.0，分數越高越清晰
    """
    gray = _to_gray(image)
    lap_var = _laplacian_variance(gray)
    return _normalize(lap_var, _LAPLACIAN_SATURATION)


def _to_gray(image: np.ndarray) -> np.ndarray:
    """RGB 轉灰階（若已是灰階則直接回傳）。"""
    if image.ndim == 2:
        return image.astype(np.float32)
    # 使用亮度加權公式
    return (
        0.299 * image[:, :, 0].astype(np.float32)
        + 0.587 * image[:, :, 1].astype(np.float32)
        + 0.114 * image[:, :, 2].astype(np.float32)
    )


def _laplacian_variance(gray: np.ndarray) -> float:
    """計算 Laplacian variance。"""
    # 3×3 Laplacian kernel
    kernel = np.array([[0, 1, 0],
                       [1, -4, 1],
                       [0, 1, 0]], dtype=np.float32)
    from scipy.signal import convolve2d
    laplacian = convolve2d(gray, kernel, mode="valid")
    return float(np.var(laplacian))


def _normalize(value: float, saturation: float) -> float:
    """將 0~saturation 線性映射至 0~100，clamp 至上下界。"""
    score = min(value / saturation * 100.0, 100.0)
    return max(0.0, score)
