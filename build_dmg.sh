#!/bin/bash
# ==============================================================================
# PickUpPhoto macOS 一鍵 DMG 打包腳本
# ==============================================================================
# 此編譯成果主要在 MacStudio M1 Max (Apple Silicon) 系統上進行測試與編譯。
# 預設編譯為該架構的原生二進位檔。

set -e

APP_NAME="PickUpPhoto"
DMG_NAME="PickUpPhoto_AppleSilicon.dmg"

echo "=== 1. 清理舊的編譯快取與暫存資料 ==="
rm -rf build dist *.spec "$DMG_NAME"
find . -name "*.pyc" -delete
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

echo "=== 2. 啟動 PyInstaller 封裝 .app ==="
# --noconsole: 不顯示終端機視窗
# --name: 指定產出 App 名稱
# --clean: 每次編譯清除 PyInstaller 快取
# --collect-all: 收集相關第三方函式庫的 binary/data (防止 mediapipe 或 rawpy 遺失依賴)
.venv/bin/pyinstaller \
    --noconsole \
    --clean \
    --name="$APP_NAME" \
    --collect-all rawpy \
    --collect-all mediapipe \
    pickupphoto/__main__.py

echo "=== 3. 封裝成 DMG 磁碟映像檔 ==="
if command -v create-dmg &> /dev/null; then
    echo "偵測到 create-dmg，將製作精美的拖曳式安裝 DMG..."
    create-dmg \
        --volname "PickUpPhoto 安裝器" \
        --window-pos 200 120 \
        --window-size 600 350 \
        --icon-size 100 \
        --icon "$APP_NAME.app" 150 150 \
        --hide-extension "$APP_NAME.app" \
        --app-drop-link 450 150 \
        "$DMG_NAME" \
        "dist/$APP_NAME.app"
else
    echo "未偵測到 create-dmg，使用系統內建 hdiutil 進行基礎 DMG 打包..."
    # 建立一個臨時資料夾，將 .app 放進去，並建立 Applications 捷徑
    TEMP_DIR="dist/dmg_temp"
    mkdir -p "$TEMP_DIR"
    cp -R "dist/$APP_NAME.app" "$TEMP_DIR/"
    ln -s /Applications "$TEMP_DIR/Applications"
    
    hdiutil create -volname "PickUpPhoto 安裝器" -srcfolder "$TEMP_DIR" -ov -format UDZO "$DMG_NAME"
    rm -rf "$TEMP_DIR"
fi

echo "=============================================================================="
echo "🎉 打包完成！輸出檔案為: $DMG_NAME"
echo "=============================================================================="
echo "⚠️  注意："
echo "本安裝檔未進行 Apple 開發者簽章與公證。"
echo "其他使用者下載安裝後，若開啟時彈出「無法驗證開發者」提示，請遵循以下開源分享解決方案："
echo "1. 於應用程式圖示上按住 Control 鍵並點擊（或點擊右鍵），選擇「打開」。"
echo "2. 或者前往「系統設定」->「隱私權與安全性」，在下方點擊「強制允許開啟」。"
echo "=============================================================================="
