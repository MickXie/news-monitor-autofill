"""第 4–5 步：把「新聞開始」與「廣告開始」事件對到分鐘，寫進範本。

只寫四台的五字標欄（F/J/N/R），其他儲存格、格式完全不動。
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass

import openpyxl

from config import CHANNELS, OUT_NAME, OUTPUT, START_MIN, END_MIN, TEMPLATE, WORK


MIN_NEWS_SEC = 30    # 短於 30 秒的新聞（預告、快訊帶過）不記
NOISE_CONF = 0.35    # 信心低於此值且不到 1 分鐘 → 視為雜訊


@dataclass
class Event:
    kind: str        # "news" 或 "ad"
    label: str       # 五字標；廣告時為 "廣告"
    start: float     # 播出時間（秒，從 00:00 起算）
    dur: float       # 持續秒數
    confidence: float = 1.0


def cell_text(events: list[Event]) -> str | None:
    """決定某一分鐘的儲存格要寫什麼。

    events：這一分鐘內「開始」的事件，已依時間排序（新聞開始、廣告開始都在內）。
    沒有事件時不會呼叫（該格留白＝延續上一則）。

    回傳要寫入的文字；回傳 None 表示這格留白。

    參考 10/26 範例的寫法：
      - 單一新聞開始 → "土城翁輾亡"
      - 進廣告 → "廣告"
      - 同分鐘有多則 → "持刀警開槍/台股二補跌"
    """
    # 規則從 10/26 範例四台欄位歸納：
    #  - 每台每小時 22–27 格、約每 2 分鐘一則 → 30 秒以下的新聞不記
    #  - 同格多則最多 2 則，用 "/" 串
    #  - "廣告" 一律單獨寫；廣告短到同分鐘就回新聞時，寫 "廣告/五字標"，避免漏記恢復
    news = [e for e in events if e.kind == "news" and e.dur >= MIN_NEWS_SEC]
    ad = next((e for e in events if e.kind == "ad"), None)
    if ad:
        back = [e for e in news if e.start >= ad.start + ad.dur]
        return "/".join(["廣告"] + [e.label for e in back[:1]])
    if not news:
        return None
    keep = sorted(sorted(news, key=lambda e: -e.dur)[:2], key=lambda e: e.start)
    return "/".join(e.label for e in keep)


def build_events(ch):
    an = json.load(open(WORK / ch / "analysis.json", encoding="utf-8"))
    st = json.load(open(WORK / ch / "stories.json", encoding="utf-8"))["stories"]
    off = an["offset"]
    evs = []
    for s in st:
        evs.append(Event("news", s["label"], s["t0"] + off, s["t1"] - s["t0"] + 1, s.get("confidence", 1)))
    ads = [Event("ad", "廣告", max(a["t0"] + off, START_MIN * 60), a["dur"]) for a in an["ads"]]
    # 開始時間落在廣告破口內的新聞（例如破口中的插播快訊）屬於破口，不另外記
    evs = [e for e in evs if not any(a.start <= e.start < a.start + a.dur for a in ads)]
    evs += ads
    evs.sort(key=lambda e: e.start)
    # 新聞長度＝到下一個事件（下一則或廣告）開始為止
    def set_durations(evs):
        for i, e in enumerate(evs):
            if e.kind == "news":
                # 最後一則會播到 13:00 之後，不能因為「到整點只剩幾秒」就被當成太短
                nxt = evs[i + 1].start if i + 1 < len(evs) else e.start + 600
                e.dur = nxt - e.start
    set_durations(evs)
    # LLM 自己判為低信心、又不到 1 分鐘的段落，多半是主播圖卡引言或 OCR 雜訊 → 併入前一則
    evs = [e for e in evs if not (e.kind == "news" and e.confidence < NOISE_CONF and e.dur < 60)]
    set_durations(evs)
    # 同一則被切成兩段（中間沒有廣告）→ 合併
    merged = []
    for e in evs:
        if merged and e.kind == "news" and merged[-1].kind == "news" and merged[-1].label == e.label:
            merged[-1].dur = e.start + e.dur - merged[-1].start
            continue
        merged.append(e)
    return merged


def by_minute(events):
    rows = {}
    for e in events:
        m = int(e.start // 60)
        if START_MIN <= m <= END_MIN:
            rows.setdefault(m, []).append(e)
    return rows


class TemplateError(Exception):
    """範本格式不符時丟出，訊息直接給使用者看。"""


def locate(ws):
    """從範本本身找出「每分鐘在哪一列」「各台五字標在哪一欄」，不寫死座標。

    - 分鐘列：A 欄的 1200、1201… 這類數字（時×100＋分）
    - 台別欄：表頭列中寫著台名（TVBS-N、東森…）的那一格，就是該台五字標欄
    """
    minute_row = {}
    for r in range(1, ws.max_row + 1):
        v = ws.cell(r, 1).value
        if isinstance(v, (int, float)) and 0 <= v <= 2359 and int(v) % 100 < 60:
            minute_row[int(v) // 100 * 60 + int(v) % 100] = r
    col_of = {}
    for r in range(1, 6):
        for c in range(1, ws.max_column + 1):
            v = str(ws.cell(r, c).value or "")
            for ch, cfg in CHANNELS.items():
                if ch not in col_of and cfg["header"] in v:
                    col_of[ch] = openpyxl.utils.get_column_letter(c)
    return minute_row, col_of


def fill(out_name=OUT_NAME):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    out = OUTPUT / out_name
    shutil.copy(TEMPLATE, out)          # 從範本複製，保留所有格式
    wb = openpyxl.load_workbook(out)
    ws = wb.worksheets[0]
    minute_row, col_of = locate(ws)
    missing = [m for m in range(START_MIN, END_MIN + 1) if m not in minute_row]
    if len(missing) == END_MIN - START_MIN + 1:
        raise TemplateError(f"範本裡找不到 {START_MIN // 60:02d}:00 這個時段的時間列（A 欄應有 {START_MIN // 60}00、"
                            f"{START_MIN // 60}01…），請確認選的時段或範本是否正確。")
    result = {}
    for ch, cfg in CHANNELS.items():
        if not (WORK / ch / "stories.json").exists():
            continue
        col = col_of.get(ch)
        if not col:
            raise TemplateError(f"範本表頭找不到「{cfg['name']}」這一台的欄位。")
        rows = by_minute(build_events(ch))
        result[ch] = {}
        for m, evs in rows.items():
            text = cell_text(evs)
            if text and m in minute_row:
                ws[f"{col}{minute_row[m]}"] = text
                result[ch][m] = text
    wb.save(out)
    return out, result


if __name__ == "__main__":
    path, res = fill()
    print("已輸出", path)
    for ch, rows in res.items():
        print(ch, len(rows), "格")
