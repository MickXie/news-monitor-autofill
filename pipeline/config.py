"""各台設定：Excel 欄位，以及畫面上要讀的區域（ROI）。

ROI 座標以 1280x720 為準，格式 (x0, y0, x1, y1)。影片不是 720p 時，抽格時會先縮放成 1280x720。
新增頻道或台改版時，只要改這個檔案。

執行模式：
- 設定環境變數 NM_JOB=<任務資料夾> 時，從 <任務資料夾>/job.json 讀入影片、日期、時段、範本，
  中間檔放在 <任務資料夾>/work，成果放在 <任務資料夾>/output（給網頁程式用）。
- 沒有 NM_JOB 時，沿用專案根目錄的影片與 work/、output/（開發與報告用）。
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"                 # 跨任務共用：LLM 快取、事件命名表、設定
SAMPLE = ROOT / "範例（有填寫的版本）.xlsx"
DEFAULT_TEMPLATE = ROOT / "範本（乾淨版）.xlsx"

W, H = 1280, 720

CHANNELS = {
    "tvbs": {
        "name": "TVBS-N", "video": "tvbsn_20261106120005.mp4", "col": "F", "header": "TVBS",
        "logo": ("TVBS", "TUBS", "T/BS", "BS新聞台"),
        "roi": {
            "title": (318, 556, 1238, 652),
            "clock": (100, 644, 316, 690),
            "loc":   (150, 536, 270, 582),
        },
        # 進廣告時時鐘會消失（全螢幕廣告）
        "wrap_marker": None,
    },
    "ebc": {
        "name": "東森", "video": "ebc_20261106120018.mp4", "col": "J", "header": "東森",
        "logo": ("東森", "EBC", "CBC東森"),
        "roi": {
            "title": (90, 566, 1240, 654),
            "clock": (80, 648, 250, 692),
            "loc":   (100, 540, 300, 582),
            "tag":   (80, 30, 600, 108),     # 左上角短標
        },
        "wrap_marker": None,
    },
    "ftv": {
        "name": "民視", "video": "ftv_20261106120013.mp4", "col": "N", "header": "民視",
        "logo": ("民視", "FORMOSA"),
        "roi": {
            # 從 x=292 開始，避開左側「別則新聞推播」小框
            "title": (292, 556, 1238, 654),
            "clock": (95, 648, 290, 710),    # 時鐘和日期 11/06(五) 輪流出現
            "loc":   (100, 528, 300, 576),
            "tag":   (80, 30, 700, 110),
            "wrap":  (890, 98, 1200, 156),   # 廣告包框右上的「現在最焦點」
        },
        "wrap_marker": "最焦點",
    },
    "cts": {
        "name": "華視", "video": "cti_20261106120007.mp4", "col": "R", "header": "華視",
        "logo": ("華視", "CTS"),
        "roi": {
            # 包含受訪者名條那一行（小字），後處理用字高分開主標和名條
            "title": (190, 580, 1240, 666),
            "clock": (50, 664, 185, 712),
        },
        "wrap_marker": None,
    },
}

JOB_DIR = Path(os.environ["NM_JOB"]) if os.environ.get("NM_JOB") else None

if JOB_DIR:
    JOB = json.loads((JOB_DIR / "job.json").read_text(encoding="utf-8"))
    WORK = JOB_DIR / "work"
    OUTPUT = JOB_DIR / "output"
    TEMPLATE = Path(JOB.get("template") or DEFAULT_TEMPLATE)
    START_MIN = int(JOB["slot_start"])
    END_MIN = int(JOB["slot_end"])
    RUN_KEY = f"{JOB['date'].replace('-', '')}_{START_MIN // 60:02d}"
    # 只處理這個任務有放影片的台
    for ch in list(CHANNELS):
        if ch in JOB["videos"]:
            CHANNELS[ch]["video"] = JOB["videos"][ch]
        else:
            del CHANNELS[ch]
    OUT_NAME = f"監看_自動填表_{JOB['date'].replace('-', '')}_{START_MIN // 60:02d}.xlsx"
else:
    JOB = None
    WORK = ROOT / "work"
    OUTPUT = ROOT / "output"
    TEMPLATE = DEFAULT_TEMPLATE
    START_MIN = 12 * 60          # 12:00
    END_MIN = 12 * 60 + 59       # 12:59
    RUN_KEY = "20261106_12"
    OUT_NAME = "12監看_自動填表_20261106.xlsx"

FIRST_ROW = 5                    # 舊版範本 1200 那一列（新版改由範本 A 欄自動找）


def video_path(ch):
    p = Path(CHANNELS[ch]["video"])
    return p if p.is_absolute() else ROOT / p
