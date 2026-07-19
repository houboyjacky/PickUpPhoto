# PickUpPhoto

> 輕量、開源的 RAW 照片瀏覽、評星與輸出工具，專為個人攝影師設計。

支援 **Nikon NEF** 與 **Fujifilm RAF** 格式，提供雙模式視圖（格狀縮圖 / 單張預覽）、鍵盤優先操作，並內建 AI 輔助分析（對焦清晰度、曝光、連拍最佳幀推薦）。

---

## 功能特色

- 📂 **快速瀏覽**：以 embedded JPEG preview 快速載入，首次開啟後快取至本地 SQLite
- ⭐ **鍵盤評星**：數字鍵 `0–5` 快速評分，`←` `→` 切換照片
- 🤖 **AI 分析**（手動觸發）：
  - 對焦清晰度（Laplacian variance）
  - 曝光問題（直方圖分析）
  - 運動模糊偵測
  - 連拍群組自動分組（≤3 秒閾值），選出群組最佳幀（🏆）
  - 眼睛對焦分析（可選，需 `mediapipe`，Mac Metal 加速）
- 📤 **輸出**：按星等條件（`≥N` 或 `=N`）複製原始 RAW 檔案，不做格式轉換

---

## 安裝

### 需求

- **Python 3.14**（推薦；利用 free-threaded 模式加速背景載入）
- 備案：**Python 3.12+**（所有功能相同）
- macOS（開發環境；架構上不排除跨平台）

### 步驟

```bash
# 1. Clone 專案
git clone https://github.com/your-username/pickupphoto.git
cd pickupphoto

# 2. 建立虛擬環境
python3.14 -m venv .venv      # 或 python3.12 -m venv .venv
source .venv/bin/activate

# 3. 安裝依賴
pip install -e "."

# 4. （可選）安裝眼睛對焦分析模組
pip install -e ".[face]"

# 5. 執行
python -m pickupphoto
```

---

## 鍵盤快捷鍵

| 按鍵 | 功能 |
|------|------|
| `0` – `5` | 設定星等（0 = 清除，1–5 = 對應星數） |
| `←` | 上一張照片（單張模式） |
| `→` | 下一張照片（單張模式） |
| `雙擊縮圖` | 進入單張預覽模式 |

---

## 資料存放

每個被瀏覽的資料夾旁會建立 `.pickupphoto/` 隱藏資料夾：

```
/Photos/2024-wedding/
  ├── IMG_001.NEF
  ├── IMG_002.NEF
  └── .pickupphoto/
      ├── cache.db      ← 縮圖快取 + AI 分析結果（可刪除重建，預設 7 天 TTL）
      └── ratings.json  ← 使用者評分（永久保留，建議備份）
```

> ⚠️ **ratings.json 是唯一不可重建的資料**，請定期備份或納入版控。

---

## 開發

```bash
# 安裝開發依賴
pip install -e ".[dev]"

# 執行測試
pytest
```

---

## 授權

MIT License
