"""
core/database.py — SQLite sidecar 資料庫管理

每個被開啟的 RAW 照片資料夾旁建立 `.pickupphoto/cache.db`，
儲存縮圖快取、EXIF metadata、評分與 AI 分析結果。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# 快取預設 TTL（天）
DEFAULT_TTL_DAYS = 7

# Schema 版本
SCHEMA_VERSION = 1


def get_db_path(folder: Path) -> Path:
    """取得指定資料夾的 .pickupphoto/cache.db 路徑。"""
    return folder / ".pickupphoto" / "cache.db"


def get_ratings_path(folder: Path) -> Path:
    """取得指定資料夾的 .pickupphoto/ratings.json 路徑。"""
    return folder / ".pickupphoto" / "ratings.json"


class Database:
    """管理單一資料夾的 SQLite sidecar 資料庫。"""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.db_path = get_db_path(folder)
        self.ratings_path = get_ratings_path(folder)
        self._conn: sqlite3.Connection | None = None
        self._write_lock = __import__('threading').Lock()  # 序列化所有讀寫與連線操作

    # ─── 連線管理 ─────────────────────────────────────────────

    def open(self) -> None:
        """開啟資料庫連線並建立 schema（若不存在）。"""
        with self._write_lock:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,  # 允許多執行緒使用同一連線（由 _write_lock 序列化保護）
                timeout=10.0,             # 等待 lock 釋放的超時（秒）
            )
            self._conn.row_factory = sqlite3.Row
            # 使用 PRAGMA 配置
            self._conn.execute("PRAGMA journal_mode=WAL")  # 讀寫並發
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA busy_timeout=5000")  # 5 秒 busy timeout
        
        # 下列方法會內部調用已加鎖的 self.execute / self.executescript
        self._create_schema()
        self._touch_last_accessed()

    def close(self) -> None:
        """關閉資料庫連線。"""
        with self._write_lock:
            if self._conn:
                self._conn.close()
                self._conn = None

    def __enter__(self) -> "Database":
        self.open()
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Database not opened. Call open() first.")
        return self._conn

    # ─── 執行緒安全包裝方法 ───────────────────────────────────────

    def execute(self, sql: str, parameters: tuple = ()) -> sqlite3.Cursor:
        """執行 SQL 語句，並保證執行緒安全。"""
        with self._write_lock:
            return self.conn.execute(sql, parameters)

    def executescript(self, sql_script: str) -> sqlite3.Cursor:
        """執行 SQL 腳本，並保證執行緒安全。"""
        with self._write_lock:
            return self.conn.executescript(sql_script)

    def commit(self) -> None:
        """提交交易，並保證執行緒安全。"""
        with self._write_lock:
            self.conn.commit()

    # ─── Schema ───────────────────────────────────────────────

    def _create_schema(self) -> None:
        """建立所有資料表（若不存在）。"""
        self.executescript("""
            CREATE TABLE IF NOT EXISTS cache_meta (
                id              INTEGER PRIMARY KEY CHECK (id = 1),
                schema_version  INTEGER NOT NULL DEFAULT 1,
                created_at      TEXT NOT NULL,
                last_accessed   TEXT NOT NULL,
                pickupphoto_ver TEXT NOT NULL DEFAULT '0.1.0'
            );

            CREATE TABLE IF NOT EXISTS thumbnails (
                filename        TEXT PRIMARY KEY,
                thumb_blob      BLOB NOT NULL,
                file_mtime      INTEGER NOT NULL,
                width           INTEGER NOT NULL,
                height          INTEGER NOT NULL,
                has_fallback    INTEGER NOT NULL DEFAULT 0,
                cached_at       TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS ratings (
                filename        TEXT PRIMARY KEY,
                stars           INTEGER NOT NULL DEFAULT 0 CHECK (stars BETWEEN 0 AND 5),
                updated_at      TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS ai_scores (
                filename        TEXT PRIMARY KEY,
                sharpness       REAL,
                exposure        REAL,
                motion_blur     REAL,
                eye_focus       REAL,
                has_face        INTEGER,
                analyzed_at     TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS burst_groups (
                filename        TEXT PRIMARY KEY,
                group_id        TEXT NOT NULL,
                group_size      INTEGER NOT NULL DEFAULT 1,
                group_rank      INTEGER NOT NULL DEFAULT 1,
                ai_best         INTEGER NOT NULL DEFAULT 0,
                composite_score REAL
            );

            CREATE INDEX IF NOT EXISTS idx_burst_group_id ON burst_groups (group_id);
        """)
        self.commit()

        # 確保 cache_meta 有一行
        now = _utcnow()
        self.execute("""
            INSERT OR IGNORE INTO cache_meta (id, created_at, last_accessed)
            VALUES (1, ?, ?)
        """, (now, now))
        self.commit()

    def _touch_last_accessed(self) -> None:
        """更新最後存取時間。"""
        self.execute(
            "UPDATE cache_meta SET last_accessed = ? WHERE id = 1",
            (_utcnow(),),
        )
        self.commit()

    # ─── TTL 檢查 ─────────────────────────────────────────────

    def is_expired(self, ttl_days: int = DEFAULT_TTL_DAYS) -> bool:
        """回傳快取是否已超過 TTL。"""
        row = self.execute(
            "SELECT last_accessed FROM cache_meta WHERE id = 1"
        ).fetchone()
        if not row:
            return True
        last = datetime.fromisoformat(row["last_accessed"])
        return datetime.now(timezone.utc) - last > timedelta(days=ttl_days)

    def cache_size_bytes(self) -> int:
        """回傳 cache.db 檔案大小（bytes）。"""
        return self.db_path.stat().st_size if self.db_path.exists() else 0

    def last_accessed(self) -> datetime | None:
        """回傳最後存取時間（UTC）。"""
        row = self.execute(
            "SELECT last_accessed FROM cache_meta WHERE id = 1"
        ).fetchone()
        if not row:
            return None
        return datetime.fromisoformat(row["last_accessed"])

    # ─── 縮圖 ─────────────────────────────────────────────────

    def save_thumbnail(
        self,
        filename: str,
        blob: bytes,
        mtime: int,
        width: int,
        height: int,
        has_fallback: bool = False,
    ) -> None:
        """儲存縮圖 blob。"""
        self.execute("""
            INSERT OR REPLACE INTO thumbnails
                (filename, thumb_blob, file_mtime, width, height, has_fallback, cached_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (filename, blob, mtime, width, height, int(has_fallback), _utcnow()))
        self.commit()

    def load_thumbnail(self, filename: str) -> dict[str, Any] | None:
        """讀取縮圖記錄，回傳 dict 或 None。"""
        row = self.execute(
            "SELECT * FROM thumbnails WHERE filename = ?", (filename,)
        ).fetchone()
        return dict(row) if row else None

    def get_cached_mtime(self, filename: str) -> int | None:
        """取得已快取的 mtime，用於比對原檔是否被修改。"""
        row = self.execute(
            "SELECT file_mtime FROM thumbnails WHERE filename = ?", (filename,)
        ).fetchone()
        return row["file_mtime"] if row else None

    def thumbnail_count(self) -> int:
        """已快取縮圖張數。"""
        return self.execute("SELECT COUNT(*) FROM thumbnails").fetchone()[0]

    def delete_thumbnail(self, filename: str) -> None:
        """刪除單張快取記錄（用於強制重新快取）。"""
        self.execute("DELETE FROM thumbnails WHERE filename = ?", (filename,))
        self.commit()

    # ─── 評分 ─────────────────────────────────────────────────

    def set_rating(self, filename: str, stars: int) -> None:
        """儲存評分（0-5），同時同步更新 ratings.json。"""
        assert 0 <= stars <= 5, f"Invalid stars: {stars}"
        self.execute("""
            INSERT OR REPLACE INTO ratings (filename, stars, updated_at)
            VALUES (?, ?, ?)
        """, (filename, stars, _utcnow()))
        self.commit()
        self._sync_ratings_json()

    def get_rating(self, filename: str) -> int:
        """取得評分，未評分回傳 0。"""
        row = self.execute(
            "SELECT stars FROM ratings WHERE filename = ?", (filename,)
        ).fetchone()
        return row["stars"] if row else 0

    def get_all_ratings(self) -> dict[str, int]:
        """取得所有評分 {filename: stars}。"""
        rows = self.execute("SELECT filename, stars FROM ratings").fetchall()
        return {r["filename"]: r["stars"] for r in rows}

    def _sync_ratings_json(self) -> None:
        """將評分同步寫入 ratings.json（人類可讀備份）。"""
        ratings = self.get_all_ratings()
        self.ratings_path.write_text(
            json.dumps(ratings, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def load_ratings_from_json(self) -> None:
        """從 ratings.json 恢復評分到 SQLite（首次開啟時用）。"""
        if not self.ratings_path.exists():
            return
        try:
            data: dict[str, int] = json.loads(self.ratings_path.read_text("utf-8"))
            for filename, stars in data.items():
                if isinstance(stars, int) and 0 <= stars <= 5:
                    self.execute("""
                        INSERT OR IGNORE INTO ratings (filename, stars, updated_at)
                        VALUES (?, ?, ?)
                    """, (filename, stars, _utcnow()))
            self.commit()
        except (json.JSONDecodeError, KeyError):
            pass  # ratings.json 損毀時靜默略過

    # ─── AI 分析 ──────────────────────────────────────────────

    def save_ai_scores(
        self,
        filename: str,
        *,
        sharpness: float | None = None,
        exposure: float | None = None,
        motion_blur: float | None = None,
        eye_focus: float | None = None,
        has_face: bool | None = None,
    ) -> None:
        """儲存 AI 分析結果。"""
        self.execute("""
            INSERT OR REPLACE INTO ai_scores
                (filename, sharpness, exposure, motion_blur, eye_focus, has_face, analyzed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            filename, sharpness, exposure, motion_blur, eye_focus,
            int(has_face) if has_face is not None else None,
            _utcnow(),
        ))
        self.commit()

    def get_ai_scores(self, filename: str) -> dict[str, Any] | None:
        """取得 AI 分析結果，尚未分析回傳 None。"""
        row = self.execute(
            "SELECT * FROM ai_scores WHERE filename = ?", (filename,)
        ).fetchone()
        return dict(row) if row else None

    def get_all_ai_scores(self) -> dict[str, dict[str, Any]]:
        """取得所有 AI 分析結果 {filename: scores}。"""
        rows = self.execute("SELECT * FROM ai_scores").fetchall()
        return {r["filename"]: dict(r) for r in rows}

    # ─── 連拍群組 ─────────────────────────────────────────────

    def save_burst_group(
        self,
        filename: str,
        group_id: str,
        group_size: int,
        group_rank: int,
        ai_best: bool,
        composite_score: float | None,
    ) -> None:
        """儲存連拍群組資訊。"""
        self.execute("""
            INSERT OR REPLACE INTO burst_groups
                (filename, group_id, group_size, group_rank, ai_best, composite_score)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (filename, group_id, group_size, group_rank, int(ai_best), composite_score))
        self.commit()

    def get_burst_group(self, filename: str) -> dict[str, Any] | None:
        """取得連拍群組資訊。"""
        row = self.execute(
            "SELECT * FROM burst_groups WHERE filename = ?", (filename,)
        ).fetchone()
        return dict(row) if row else None

    def get_all_burst_groups(self) -> dict[str, dict[str, Any]]:
        """取得所有連拍群組資訊 {filename: group_info}。"""
        rows = self.execute("SELECT * FROM burst_groups").fetchall()
        return {r["filename"]: dict(r) for r in rows}

    def clear_burst_groups(self) -> None:
        """清除所有連拍群組資料（重新掃描前呼叫）。"""
        self.execute("DELETE FROM burst_groups")
        self.commit()


# ─── 工具函式 ─────────────────────────────────────────────────

def _utcnow() -> str:
    """回傳當前 UTC 時間的 ISO 8601 字串。"""
    return datetime.now(timezone.utc).isoformat()


def list_cached_folders(search_roots: list[Path] | None = None) -> list[dict[str, Any]]:
    """
    掃描已建立快取的資料夾清單。
    回傳 [{folder, db_path, size_bytes, last_accessed}, ...]
    """
    if search_roots is None:
        return []

    result = []
    for root in search_roots:
        for db_path in root.rglob(".pickupphoto/cache.db"):
            folder = db_path.parent.parent
            size = db_path.stat().st_size
            # 快速讀取 last_accessed 不完整開啟
            try:
                with sqlite3.connect(str(db_path)) as c:
                    c.row_factory = sqlite3.Row
                    row = c.execute(
                        "SELECT last_accessed FROM cache_meta WHERE id = 1"
                    ).fetchone()
                    last = row["last_accessed"] if row else None
            except sqlite3.Error:
                last = None
            result.append({
                "folder": folder,
                "db_path": db_path,
                "size_bytes": size,
                "last_accessed": last,
            })
    return result
