# PickUpPhoto

> 輕量、開源的 RAW 照片瀏覽、評星與輸出工具，專為個人攝影師設計。

支援 **Nikon NEF** 與 **Fujifilm RAF** 格式，提供雙模式視圖（格狀縮圖 / 單張預覽）、鍵盤優先操作，並內建 AI 輔助分析（對焦清晰度、曝光、連拍最佳幀推薦）。

---

## 💻 運行環境與發行說明

* **開發與編譯環境**：本應用程式由作者於 **MacStudio M1 Max (Apple Silicon, macOS)** 系統上開發、編譯並通過完整測試。

> [!WARNING]
> **⚠️ 注意：**
> 本安裝檔未進行 Apple 開發者簽章與公證。
> 其他使用者下載安裝後，若開啟時彈出「無法驗證開發者」提示，請遵循以下開源分享解決方案：
> 1. 於應用程式圖示上按住 Control 鍵並點擊（或點擊右鍵），選擇「打開」。
> 2. 或者前往「系統設定」->「隱私權與安全性」，在下方點擊「強制允許開啟」。

---

## 📦 安裝與下載

### 方式一：下載 DMG 安裝檔（推薦 macOS 一般用戶）
1. 前往本專案的 [Releases](https://github.com/houboyjacky/pickupphoto/releases) 頁面。
2. 下載最新編譯的 `PickUpPhoto_v1.0.0_AppleSilicon.dmg` 安裝包。
3. 雙擊打開 `.dmg`，將 `PickUpPhoto` 圖示拖曳到 **Applications (應用程式)** 資料夾即可。

### 方式二：開發者自行建置與執行 (Source Code)

#### 系統需求
* **Python 3.10+**（推薦 Python 3.12+，或利用 Python 3.14 free-threaded 模式加速背景載入）
* macOS（開發環境；架構上不排除跨平台）

#### 本機啟動步驟
```bash
# 1. Clone 專案
git clone https://github.com/houboyjacky/pickupphoto.git
cd pickupphoto

# 2. 建立虛擬環境
python3 -m venv .venv
source .venv/bin/activate

# 3. 安裝依賴
pip install -e "."

# 4. （可選）安裝眼睛對焦分析模組
pip install -e ".[face]"

# 5. 執行
python -m pickupphoto
```

---

## 🛠️ 打包編譯自己專屬的 DMG

如果您希望在本機修改程式碼後自行打包成獨立的 App 與 DMG，本專案提供了一鍵打包腳本（會自動清理 `build/`, `dist/`, `__pycache__` 等暫存編譯快取）：

```bash
# 賦予執行權限並執行
chmod +x build_dmg.sh
./build_dmg.sh
```

---

## ⌨️ 鍵盤快捷鍵

| 按鍵 | 功能 |
|------|------|
| `0` – `5` | 設定星等（0 = 清除，1–5 = 對應星數，支援主鍵盤與右側數字鍵盤） |
| `←` | 上一張照片（單張模式） |
| `→` | 下一張照片（單張模式） |
| `雙擊縮圖` | 進入單張預覽模式 |

---

## 📂 資料存放設計

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

## 📄 授權條款

本專案採用 **MIT License** 授權。詳見 [LICENSE](LICENSE) 檔案。
