#!/bin/bash
# 雙擊這個檔案就會開啟「新聞監看自動填表」。使用期間請不要關閉這個黑色視窗。
cd "$(dirname "$0")" || exit 1
clear
echo "======================================"
echo "  新聞監看自動填表"
echo "======================================"

# 第一次使用：自動安裝需要的套件
if [ ! -x .venv/bin/python ]; then
  echo "第一次使用，正在安裝需要的元件（約 3–5 分鐘，需要網路）…"
  if ! command -v python3 >/dev/null 2>&1; then
    echo "這台電腦沒有 Python 3。請先在終端機執行 xcode-select --install 安裝開發者工具，完成後再雙擊這個檔案。"
    read -r -p "按 Enter 關閉…"; exit 1
  fi
  python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt
  if [ $? -ne 0 ]; then
    rm -rf .venv
    echo "安裝失敗，請確認網路連線後再雙擊一次。"
    read -r -p "按 Enter 關閉…"; exit 1
  fi
fi

# 已經開著了：直接打開網頁
if [ -f data/port.txt ]; then
  PORT=$(cat data/port.txt)
  if curl -s -m 2 "http://127.0.0.1:$PORT/api/health" | grep -q '"ok"'; then
    echo "程式已經在執行，正在開啟網頁…"
    open "http://127.0.0.1:$PORT"
    exit 0
  fi
fi

rm -f data/port.txt
(
  for _ in $(seq 1 30); do
    if [ -f data/port.txt ]; then sleep 1; open "http://127.0.0.1:$(cat data/port.txt)"; exit 0; fi
    sleep 0.5
  done
) &
echo "啟動中，稍後會自動開啟瀏覽器。"
echo "使用期間請不要關閉這個視窗；要結束程式時，關閉這個視窗即可。"
echo
exec .venv/bin/python app/server.py
