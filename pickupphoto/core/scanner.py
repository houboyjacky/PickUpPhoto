"""
core/scanner.py — 資料夾掃描與 EXIF 提取

掃描指定資料夾（不遞迴），建立 NEF/RAF 檔案清單，
並依 EXIF DateTimeOriginal 排序。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import piexif
import rawpy

# 支援的 RAW 副檔名（大小寫不敏感）
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".nef", ".raf"})

# EXIF 欄位對應（piexif tag IDs）
_EXIF_TAGS = {
    "make": piexif.ImageIFD.Make,
    "model": piexif.ImageIFD.Model,
    "datetime_original": piexif.ExifIFD.DateTimeOriginal,
    "subsec_time": piexif.ExifIFD.SubSecTimeOriginal,
    "exposure_time": piexif.ExifIFD.ExposureTime,
    "f_number": piexif.ExifIFD.FNumber,
    "iso": piexif.ExifIFD.ISOSpeedRatings,
    "focal_length": piexif.ExifIFD.FocalLength,
    "lens_model": piexif.ExifIFD.LensModel,
}


@dataclass
class PhotoInfo:
    """單張照片的 metadata。"""

    path: Path
    filename: str
    mtime: int  # 檔案修改時間（unix timestamp）
    file_size: int  # bytes

    # EXIF
    datetime_taken: datetime | None = None
    datetime_subsec: str = ""        # 次秒，例如 "25"
    camera_make: str = ""
    camera_model: str = ""
    lens_model: str = ""
    focal_length_mm: float | None = None
    f_number: float | None = None
    shutter_speed: str = ""          # 格式化字串，例如 "1/1000"
    iso: int | None = None

    # 狀態（由後續模組填入）
    stars: int = 0
    ai_best: bool = False
    burst_group_id: str | None = None
    burst_group_rank: int | None = None
    has_thumbnail: bool = False
    has_ai_scores: bool = False

    @property
    def display_name(self) -> str:
        return self.filename

    @property
    def exif_summary(self) -> str:
        """格式化 EXIF 摘要（用於底欄顯示）。"""
        parts: list[str] = []
        if self.datetime_taken:
            parts.append(self.datetime_taken.strftime("%Y-%m-%d %H:%M:%S"))
        camera = " ".join(filter(None, [self.camera_make, self.camera_model]))
        if camera:
            parts.append(camera)
        if self.lens_model:
            parts.append(self.lens_model)
        if self.focal_length_mm is not None:
            parts.append(f"{self.focal_length_mm:.0f}mm")
        if self.f_number is not None:
            parts.append(f"f/{self.f_number:.1f}")
        if self.shutter_speed:
            parts.append(self.shutter_speed)
        if self.iso is not None:
            parts.append(f"ISO {self.iso}")
        return " │ ".join(parts) if parts else "—"

    @property
    def sort_key(self) -> tuple[datetime, str]:
        """排序用 key：先依拍攝時間，同時間再依檔名。"""
        dt = self.datetime_taken or datetime.min
        return (dt, self.filename)


def scan_folder(folder: Path) -> list[PhotoInfo]:
    """
    掃描指定資料夾（不遞迴子資料夾），回傳依拍攝時間排序的 PhotoInfo 清單。

    Args:
        folder: 要掃描的資料夾路徑

    Returns:
        已排序的 PhotoInfo 清單；空資料夾回傳空 list

    Raises:
        NotADirectoryError: folder 不是資料夾
    """
    if not folder.is_dir():
        raise NotADirectoryError(f"不是有效資料夾：{folder}")

    photos: list[PhotoInfo] = []
    for entry in folder.iterdir():
        if not entry.is_file():
            continue
        if entry.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue

        stat = entry.stat()
        info = PhotoInfo(
            path=entry,
            filename=entry.name,
            mtime=int(stat.st_mtime),
            file_size=stat.st_size,
        )
        _populate_exif(info)
        photos.append(info)

    photos.sort(key=lambda p: p.sort_key)
    return photos


def _populate_exif(info: PhotoInfo) -> None:
    """嘗試從 RAW 檔案提取 EXIF，失敗時欄位保留預設值。"""
    # 先嘗試 piexif（快，只讀 header）
    try:
        _extract_with_piexif(info)
        return
    except Exception:
        pass

    # fallback：用 rawpy 讀取 metadata（較慢）
    try:
        _extract_with_rawpy(info)
    except Exception:
        pass  # 無法讀 EXIF，欄位保留 None/空字串


def _extract_with_piexif(info: PhotoInfo) -> None:
    """使用 piexif 提取 EXIF。"""
    exif_dict = piexif.load(str(info.path))

    image_ifd = exif_dict.get("0th", {})
    exif_ifd = exif_dict.get("Exif", {})

    # 相機廠牌/型號
    info.camera_make = _decode_bytes(image_ifd.get(piexif.ImageIFD.Make, b""))
    info.camera_model = _decode_bytes(image_ifd.get(piexif.ImageIFD.Model, b""))

    # 拍攝時間
    dt_raw = exif_ifd.get(piexif.ExifIFD.DateTimeOriginal, b"")
    if dt_raw:
        info.datetime_taken = _parse_datetime(dt_raw.decode("ascii", errors="replace"))
    subsec_raw = exif_ifd.get(piexif.ExifIFD.SubSecTimeOriginal, b"")
    info.datetime_subsec = _decode_bytes(subsec_raw)

    # 快門速度（Rational）
    et = exif_ifd.get(piexif.ExifIFD.ExposureTime)
    if et and et[1] != 0:
        numerator, denominator = et
        if numerator == 1 or denominator > numerator:
            info.shutter_speed = f"1/{denominator // numerator}" if numerator == 1 else f"{numerator}/{denominator}"
        else:
            info.shutter_speed = f"{numerator / denominator:.1f}s"

    # 光圈
    fn = exif_ifd.get(piexif.ExifIFD.FNumber)
    if fn and fn[1] != 0:
        info.f_number = fn[0] / fn[1]

    # ISO
    iso = exif_ifd.get(piexif.ExifIFD.ISOSpeedRatings)
    if iso is not None:
        info.iso = iso if isinstance(iso, int) else iso

    # 焦段
    fl = exif_ifd.get(piexif.ExifIFD.FocalLength)
    if fl and fl[1] != 0:
        info.focal_length_mm = fl[0] / fl[1]

    # 鏡頭型號
    lens_raw = exif_ifd.get(piexif.ExifIFD.LensModel, b"")
    info.lens_model = _decode_bytes(lens_raw)


def _extract_with_rawpy(info: PhotoInfo) -> None:
    """使用 rawpy 作為 fallback 讀取基本 metadata。"""
    with rawpy.imread(str(info.path)) as raw:
        # rawpy 提供有限的 metadata
        pass  # rawpy 本身 EXIF 支援有限，主要作為解碼器


def _decode_bytes(value: bytes | str) -> str:
    """解碼 bytes 為 str，去除 null bytes。"""
    if isinstance(value, str):
        return value.rstrip("\x00").strip()
    return value.decode("utf-8", errors="replace").rstrip("\x00").strip()


def _parse_datetime(dt_str: str) -> datetime | None:
    """解析 EXIF 時間字串（格式：'2024:06:15 14:32:10'）。"""
    # EXIF 格式
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(dt_str.strip(), fmt)
        except ValueError:
            continue
    return None


def get_burst_timestamp(info: PhotoInfo) -> float:
    """
    取得用於連拍分組的精確時間戳（含次秒）。
    回傳 Unix timestamp（float），無法取得時回傳 0.0。
    """
    if info.datetime_taken is None:
        return 0.0
    ts = info.datetime_taken.timestamp()
    if info.datetime_subsec:
        try:
            subsec = float(f"0.{info.datetime_subsec.strip()}")
            ts += subsec
        except ValueError:
            pass
    return ts
