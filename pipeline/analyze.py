"""第 2 步：把每秒的辨識結果，整理成「時間對齊 + 廣告區段 + 文字段落」。

1. 時間對齊：時鐘只顯示「時:分」。每一個讀到 HH:MM 的畫面都限制了
   「播出時間 = 影片秒數 + 偏移量」的範圍；取同時滿足最多畫面的偏移量，
   就能把每一格（包含讀不到時鐘的廣告、日期畫面）換算成播出時間。
2. 廣告判斷：時鐘消失（TVBS/東森/華視的全螢幕廣告、東森預告卡、華視台呼）
   或出現包框特徵（民視「現在最焦點」）→ 判為廣告；再用最短持續時間去除雜訊。
3. 文字段落：主標題區最大字那一行，連續幾秒內容相近就合成一段（容許 OCR 錯字）。
"""
from __future__ import annotations

import json
import re
from difflib import SequenceMatcher

from config import CHANNELS, WORK, START_MIN, END_MIN

CLOCK_RE = re.compile(r"(1[12])\s*[:：]\s*([0-5]\d)")
DATE_RE = re.compile(r"11\s*/\s*0?6")
BYLINE_RE = re.compile(r"(報導|記者|攝影|主播|編譯|整理)\s*$")

AD_MIN_SEC = 8       # 連續 8 秒以上沒有新聞特徵，才算進廣告
NEWS_MIN_SEC = 6     # 廣告中短暫讀到時鐘（< 6 秒）不算回到新聞
BREAK_MIN_SEC = 60   # 廣告破口至少 60 秒
BREAK_GAP_SEC = 60   # 兩段廣告間隔 < 60 秒視為同一破口


def load(ch):
    with open(WORK / ch / "frames.jsonl", encoding="utf-8") as f:
        return [json.loads(l) for l in f]


# ---------- 1. 時間對齊 ----------
def fit_offset(frames):
    """找出讓最多畫面時鐘讀數成立的偏移量（秒）。"""
    events = []
    for fr in frames:
        m = CLOCK_RE.search(fr["clock"])
        if not m:
            continue
        mins = int(m.group(1)) * 60 + int(m.group(2))
        lo = mins * 60 - fr["t"] - 0.5
        hi = mins * 60 + 60 - fr["t"] + 0.5
        events += [(lo, 1), (hi, -1)]
    events.sort()
    best, cur, best_lo, best_hi = 0, 0, None, None
    for i, (x, d) in enumerate(events):
        cur += d
        if d == 1 and cur > best:
            best, best_lo = cur, x
            best_hi = events[i + 1][0] if i + 1 < len(events) else x
    n_read = len(events) // 2
    return (best_lo + best_hi) / 2, best, n_read


def fmt(sec):
    sec = int(round(sec))
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


# ---------- 2. 廣告判斷 ----------
def news_signal(fr, cfg):
    has_clock = bool(CLOCK_RE.search(fr["clock"]) or DATE_RE.search(fr["clock"]))
    marker = cfg.get("wrap_marker")
    in_wrap = bool(marker and marker in fr.get("wrap", ""))
    return has_clock and not in_wrap, in_wrap


def smooth(flags, min_true, min_false):
    """把短於門檻的區段併入前後，回傳平滑後的布林序列。"""
    out = list(flags)
    for val, min_len in ((False, min_false), (True, min_true)):
        i = 0
        while i < len(out):
            if out[i] == val:
                j = i
                while j < len(out) and out[j] == val:
                    j += 1
                if j - i < min_len and i > 0:
                    out[i:j] = [not val] * (j - i)
                i = j
            else:
                i += 1
    return out


# ---------- 3. 文字段落 ----------
def main_line(fr):
    """取標題區字最大的一行；過濾記者署名。"""
    lines = [l for l in fr["title"] if len(l[0].strip()) >= 4]
    if not lines:
        return "", "none"
    big = max(l[1] for l in lines)
    cand = [l for l in lines if l[1] >= big * 0.8]
    text = " ".join(l[0] for l in sorted(cand, key=lambda l: l[2])).strip()
    if BYLINE_RE.search(text):
        return text, "byline"
    # 有小字名條（受訪者職稱/姓名）時，這一行多半是受訪字幕
    small = [l for l in lines if l[1] < big * 0.8]
    return text, ("quote?" if small else "text")


def similar(a, b):
    return SequenceMatcher(None, a, b).ratio()


def build_runs(frames, offset, is_news):
    runs = []
    for fr, news in zip(frames, is_news):
        bt = fr["t"] + offset
        if bt < START_MIN * 60 or bt >= (END_MIN + 1) * 60 or not news:
            continue
        text, kind = main_line(fr)
        if not text or kind == "byline":
            continue
        if runs and runs[-1]["t1"] >= fr["t"] - 2 and similar(runs[-1]["text"], text) >= 0.7:
            r = runs[-1]
            r["t1"] = fr["t"]
            r["n"] += 1
            r["kinds"].add(kind)
            if len(text) > len(r["text"]) and r["n"] <= 3:
                r["text"] = text
            for k in ("loc", "tag"):
                if fr.get(k):
                    r[k] = r.get(k) or fr[k]
        else:
            runs.append({"t0": fr["t"], "t1": fr["t"], "n": 1, "text": text, "kinds": {kind},
                         "loc": fr.get("loc", ""), "tag": fr.get("tag", "")})
    for i, r in enumerate(runs):
        r["id"] = i
        r["dur"] = r["t1"] - r["t0"] + 1
        r["start"] = fmt(r["t0"] + offset)
        r["end"] = fmt(r["t1"] + offset + 1)
        r["kinds"] = sorted(r["kinds"])
    return runs


def ad_segments(frames, offset, is_news, wrap_flags):
    segs, cur = [], None
    for fr, news, wr in zip(frames, is_news, wrap_flags):
        bt = fr["t"] + offset
        if not news:
            if cur is None:
                cur = {"t0": fr["t"], "t1": fr["t"], "wrap": 0}
            cur["t1"] = fr["t"]
            cur["wrap"] += int(wr)
        elif cur:
            segs.append(cur)
            cur = None
    if cur:
        segs.append(cur)
    # 兩段廣告中間夾的新聞少於 60 秒（例如東森的插播快訊、華視台呼）→ 視為同一個破口
    merged = []
    for s in segs:
        if merged and s["t0"] - merged[-1]["t1"] < BREAK_GAP_SEC:
            merged[-1]["t1"] = s["t1"]
            merged[-1]["wrap"] += s["wrap"]
        else:
            merged.append(s)
    # 少於 60 秒的無時鐘片段（開場片頭、片尾）不算廣告
    segs = [s for s in merged if s["t1"] - s["t0"] + 1 >= BREAK_MIN_SEC]
    for s in segs:
        s["start"] = fmt(s["t0"] + offset)
        s["end"] = fmt(s["t1"] + offset + 1)
        s["dur"] = s["t1"] - s["t0"] + 1
        s["type"] = "包框" if s["wrap"] > s["dur"] * 0.3 else "全螢幕/無時鐘"
    return segs


def analyze(ch):
    cfg = CHANNELS[ch]
    frames = load(ch)
    offset, ok, n_read = fit_offset(frames)
    raw = [news_signal(fr, cfg) for fr in frames]
    is_news = smooth([r[0] for r in raw], min_true=NEWS_MIN_SEC, min_false=AD_MIN_SEC)
    wrap_flags = [r[1] for r in raw]
    runs = build_runs(frames, offset, is_news)
    ads = [a for a in ad_segments(frames, offset, is_news, wrap_flags)
           if (a["t0"] + offset) < (END_MIN + 1) * 60 and (a["t1"] + offset) >= START_MIN * 60]
    result = {
        "channel": ch, "offset": offset, "clock_frames": n_read, "clock_agree": ok,
        "frame_state": [{"t": fr["t"], "bt": fmt(fr["t"] + offset), "news": n}
                        for fr, n in zip(frames, is_news)],
        "ads": ads, "runs": runs,
    }
    with open(WORK / ch / "analysis.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    return result


if __name__ == "__main__":
    import sys
    for ch in (sys.argv[1:] or CHANNELS):
        r = analyze(ch)
        print(f"[{ch}] 偏移 {r['offset']:.1f}s（影片 0 秒 = {fmt(r['offset'])}），"
              f"時鐘一致 {r['clock_agree']}/{r['clock_frames']}，廣告 {len(r['ads'])} 段，文字段 {len(r['runs'])} 段")
        for a in r["ads"]:
            print(f"   廣告 {a['start']}–{a['end']} ({a['dur']}s, {a['type']})")
