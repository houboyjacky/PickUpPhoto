"""
core/thumbnail_cache.py — 縮圖快取管理

協調 raw_loader 與 database，負責：
- 首次開啟資料夾時背景建立縮圖快取
- 讀取快取（SQLite blob → numpy array）
- mtime 比對（偵測原檔被修改）
- TTL 檢查
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

import numpy as np

from pickupphoto.core.database import DEFAULT_TTL_DAYS, Database
from pickupphoto.core.raw_loader import (
    jpeg_bytes_to_numpy,
    load_thumbnail,
    numpy_to_jpeg_bytes,
    resize_to_max,
)
from pickupphoto.core.scanner import PhotoInfo

# 縮圖長邊像素
THUMB_SIZE = 256


class ThumbnailCache:
    """
    管理單一資料夾的縮圖快取。

    使用方式：
        cache = ThumbnailCache(db, photos)
        cache.start_build(on_progress=callback)
        arr = cache.get(filename)
    """

    def __init__(self, db: Database, photos: list[PhotoInfo]) -> None:
        self._db = db
        self._photos = photos
        self._lock = threading.Lock()
        self._build_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    # ─── 快取讀取 ──────────────────────────────────────────────

    def get(self, filename: str) -> np.ndarray | None:
        """
        讀取縮圖 numpy array（RGB uint8）。
        若尚未快取或快取失效，回傳 None。
        """
        record = self._db.load_thumbnail(filename)
        if record is None:
            return None

        # mtime 比對：原檔被修改時回傳 None 觸發重建
        photo = self._find_photo(filename)
        if photo and record["file_mtime"] != photo.mtime:
            return None

        try:
            return jpeg_bytes_to_numpy(record["thumb_blob"])
        except Exception:
            return None

    def is_cached(self, filename: str) -> bool:
        """回傳指定檔案是否已有有效快取。"""
        return self.get(filename) is not None

    def cached_count(self) -> int:
        """已快取縮圖張數。"""
        return self._db.thumbnail_count()

    # ─── 快取建立（背景執行緒） ────────────────────────────────

    def start_build(
        self,
        on_progress: Callable[[int, int, str], None] | None = None,
        on_done: Callable[[], None] | None = None,
        max_workers: int = 4,
    ) -> None:
        """
        在背景執行緒啟動快取建立流程（Progressive Loading，支援多核心平行解析）。

        Args:
            on_progress: 每張完成時呼叫 (completed_count, total, filename)
            on_done: 全部完成時呼叫
            max_workers: 最大工作執行緒數
        """
        if self._build_thread and self._build_thread.is_alive():
            return  # 已在執行中

        self._stop_event.clear()
        self._build_thread = threading.Thread(
            target=self._build_worker,
            args=(on_progress, on_done, max_workers),
            daemon=True,
            name="ThumbnailCacheBuilder",
        )
        self._build_thread.start()

    def stop_build(self) -> None:
        """請求停止背景建立（例如使用者關閉資料夾）。"""
        self._stop_event.set()

    def is_building(self) -> bool:
        """回傳是否正在背景建立快取。"""
        return self._build_thread is not None and self._build_thread.is_alive()

    def _build_worker(
        self,
        on_progress: Callable[[int, int, str], None] | None,
        on_done: Callable[[], None] | None,
        max_workers: int,
    ) -> None:
        """背景執行緒工作：多執行緒平行提取縮圖並寫入 SQLite。"""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        total = len(self._photos)
        completed = 0
        completed_lock = threading.Lock()

        # 第一步：篩選出需要解碼的照片任務以優化平行調度
        tasks = []
        for photo in self._photos:
            if self._stop_event.is_set():
                break
            record = self._db.load_thumbnail(photo.filename)
            if record and record["file_mtime"] == photo.mtime:
                completed += 1
                if on_progress:
                    on_progress(completed, total, photo.filename)
            else:
                tasks.append(photo)

        if completed == total:
            if on_done and not self._stop_event.is_set():
                on_done()
            return

        def process_photo(photo: PhotoInfo) -> str:
            if self._stop_event.is_set():
                return photo.filename
            try:
                result = load_thumbnail(photo.path)
                blob = numpy_to_jpeg_bytes(result.image, quality=85)
                self._db.save_thumbnail(
                    filename=photo.filename,
                    blob=blob,
                    mtime=photo.mtime,
                    width=result.width,
                    height=result.height,
                    has_fallback=result.is_fallback,
                )
                photo.has_thumbnail = True
            except Exception:
                pass
            return photo.filename

        # 使用 ThreadPoolExecutor 平行解碼
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(process_photo, photo): photo for photo in tasks}
            for future in as_completed(futures):
                if self._stop_event.is_set():
                    executor.shutdown(wait=False, cancel_futures=True)
                    break

                try:
                    filename = future.result()
                except Exception:
                    continue

                with completed_lock:
                    completed += 1
                if on_progress:
                    on_progress(completed, total, filename)

        if on_done and not self._stop_event.is_set():
            on_done()

    # ─── TTL 管理 ──────────────────────────────────────────────

    def check_ttl(self, ttl_days: int = DEFAULT_TTL_DAYS) -> bool:
        """回傳快取是否已過期（超過 ttl_days 天未存取）。"""
        return self._db.is_expired(ttl_days)

    # ─── 工具 ──────────────────────────────────────────────────

    def _find_photo(self, filename: str) -> PhotoInfo | None:
        """依檔名找到 PhotoInfo（線性搜尋，小資料集夠快）。"""
        for p in self._photos:
            if p.filename == filename:
                return p
        return None


# ─── 快取資料夾掃描（用於關閉對話） ──────────────────────────


def get_cache_info(folder: Path) -> dict | None:
    """
    取得指定資料夾的快取摘要資訊。
    回傳 None 表示無快取。
    """
    from pickupphoto.core.database import get_db_path

    db_path = get_db_path(folder)
    if not db_path.exists():
        return None

    size = db_path.stat().st_size
    try:
        import sqlite3
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT last_accessed FROM cache_meta WHERE id = 1"
            ).fetchone()
            last = row["last_accessed"] if row else None
    except Exception:
        last = None

    return {
        "folder": folder,
        "db_path": db_path,
        "size_bytes": size,
        "last_accessed": last,
    }


def delete_cache(folder: Path) -> bool:
    """
    刪除指定資料夾的快取（cache.db）。
    ratings.json 不刪除（使用者評分永久保留）。
    回傳 True 表示成功。
    """
    from pickupphoto.core.database import get_db_path

    db_path = get_db_path(folder)
    if db_path.exists():
        try:
            db_path.unlink()
            return True
        except OSError:
            return False
    return False
