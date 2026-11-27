# PickUpPhoto

PickUpPhoto 是 macOS 上的 RAW 照片挑選工具。支援 Nikon NEF 和 Fujifilm RAF，可用格狀縮圖或單張預覽瀏覽照片、查看 EXIF、評分，並依星等篩選後複製原始檔。照片分析包含對焦清晰度、曝光、運動模糊、連拍最佳幀，以及選用的眼部對焦分析。

## 安裝與啟動

從 [GitHub Releases](https://github.com/houboyjacky/PickUpPhoto/releases) 下載 Apple Silicon 版 DMG，開啟後將 PickUpPhoto 拖到「應用程式」。雙擊 `PickUpPhoto.app` 便會開啟原生視窗。視窗以 Apple WKWebView 顯示介面，RAW 處理與資料都留在 Mac 本機。

DMG 內的應用程式使用 ad hoc 簽章，尚未經 Apple Developer ID 簽章與公證。下載後可能需要在 macOS「系統設定 → 隱私權與安全性」確認開啟。

從原始碼執行需要 Python 3.12 或以上。眼部分析與發行建置採用 Python 3.12，搭配包含 FaceMesh 的 MediaPipe 版本。

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,face]'
python -m pickupphoto
```

也可以將照片資料夾當成第一個參數，或加上 `--browser` 改用預設瀏覽器。從原始碼使用舊版介面時，安裝 `.[legacy]` 並加上 `--legacy`。

## 鍵盤操作

| 按鍵 | 功能 |
| --- | --- |
| `0`–`5` | 評分，0 清除星等 |
| `←` / `→` | 切換上一張或下一張 |
| 雙擊縮圖 | 開啟單張預覽 |
| `Esc` | 從單張預覽回到格狀檢視 |

每個照片資料夾內仍使用 `.pickupphoto/ratings.json` 保存使用者評分，`.pickupphoto/cache.db` 保存可重建的縮圖及分析快取。匯出直接複製 RAW 原始檔。

## 建置與發行

在 Apple Silicon Mac 安裝上述開發依賴後執行 `./build_dmg.sh`。腳本會啟動並驗證封裝後的應用程式，輸出 DMG 和對應的 `.sha256`。

GitHub Actions 會在 PR、`main` 推送、`codex/**` 推送與手動執行時測試並打包 DMG，可從當次 workflow 的 Artifacts 下載。正式版本在預定發行的 commit 更新 `pickupphoto/__init__.py` 的 `__version__`，再推送同版本的 `vX.Y.Z` 標籤。通過測試和打包後，Actions 會將 DMG 及校驗檔發佈到 GitHub Releases。

## 授權

[MIT License](LICENSE)
