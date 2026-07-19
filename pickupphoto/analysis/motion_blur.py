"""
analysis/motion_blur.py — 運動模糊偵測

結合 Laplacian variance 與方向性邊緣分析，
輸出「無模糊清晰分」0-100，分數越低代表越模糊。
"""

from __future__ import annotations

import numpy as np
from scipy.signal import convolve2d


# 方向性 Sobel kernels
_SOBEL_X = np.array([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]], dtype=np.float32)
_SOBEL_Y = np.array([[-1, -2, -1], [0, 0, 0], [1, 2, 1]], dtype=np.float32)
_LAPLACIAN = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float32)

# 飽和值（實驗調校）
_LAP_SATURATION = 1500.0
_DIRECTION_SATURATION = 0.85  # 方向一致性上界（越接近 1 越模糊）


def compute_motion_blur(image: np.ndarray) -> float:
    """
    計算無模糊清晰分（0-100）。
    分數越高代表越無模糊；運動模糊嚴重時分數低。

    結合兩個指標：
    1. Laplacian variance（整體銳利度）
    2. Sobel 方向一致性（運動模糊往往有固定方向）

    Args:
        image: RGB uint8 numpy array

    Returns:
        清晰分 0.0–100.0
    """
    gray = _to_gray(image)

    # 指標 1：Laplacian variance（越高越清晰）
    lap = convolve2d(gray, _LAPLACIAN, mode="valid")
    lap_var = float(np.var(lap))
    lap_score = min(lap_var / _LAP_SATURATION, 1.0)

    # 指標 2：Sobel 方向一致性（接近 1 = 一個方向主導 = 運動模糊）
    gx = convolve2d(gray, _SOBEL_X, mode="valid")
    gy = convolve2d(gray, _SOBEL_Y, mode="valid")
    mag = np.sqrt(gx**2 + gy**2) + 1e-6
    # 計算主方向能量比
    x_energy = float(np.mean(np.abs(gx) / mag))
    y_energy = float(np.mean(np.abs(gy) / mag))
    direction_dominance = max(x_energy, y_energy)
    # 方向一致性高（接近 1）→ 低分
    direction_score = 1.0 - min(direction_dominance / _DIRECTION_SATURATION, 1.0)

    # 加權合併：Laplacian 主導
    combined = lap_score * 0.7 + direction_score * 0.3
    return round(min(max(combined * 100.0, 0.0), 100.0), 2)


def _to_gray(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return image.astype(np.float32)
    return (
        0.299 * image[:, :, 0].astype(np.float32)
        + 0.587 * image[:, :, 1].astype(np.float32)
        + 0.114 * image[:, :, 2].astype(np.float32)
    )
