"""驗證頁：把自動填表的每一格，配上畫面截圖、時間、信心與理由，方便對照影片抽查。

輸出 output/驗證頁.html（圖片在 output/review_img/）。
信心 < 0.7 的格子標成黃色，列入「建議抽查」。
"""
from __future__ import annotations

import html
import json
import shutil

from config import CHANNELS, OUTPUT, START_MIN, END_MIN, WORK
from fill_excel import build_events, by_minute, cell_text

LOW_CONF = 0.7


def hhmm(sec):
    sec = int(sec)
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def thumb(ch, t, img_dir):
    src = WORK / ch / "thumbs" / f"{int(t):05d}.jpg"
    if not src.exists():
        return ""
    dst = img_dir / f"{ch}_{int(t):05d}.jpg"
    if not dst.exists():
        shutil.copy(src, dst)
    return f"review_img/{dst.name}"


def build():
    img_dir = OUTPUT / "review_img"
    img_dir.mkdir(parents=True, exist_ok=True)
    chans = [c for c in CHANNELS if (WORK / c / "stories.json").exists()]
    data, stats = {}, {}
    for ch in chans:
        an = json.load(open(WORK / ch / "analysis.json", encoding="utf-8"))
        st = {s["t0"]: s for s in json.load(open(WORK / ch / "stories.json", encoding="utf-8"))["stories"]}
        off = an["offset"]
        rows = by_minute(build_events(ch))
        data[ch] = {}
        low = 0
        for m, evs in rows.items():
            cell = cell_text(evs)
            details = []
            for e in evs:
                t_vid = e.start - off
                s = st.get(round(t_vid))
                conf = e.confidence if e.kind == "news" else 1.0
                low += int(e.kind == "news" and conf < LOW_CONF and e.dur >= 30)
                details.append({
                    "kind": e.kind, "label": e.label, "time": hhmm(e.start), "dur": int(e.dur),
                    "conf": conf, "img": thumb(ch, t_vid + 3, img_dir),
                    "headline": (s or {}).get("headline", ""), "note": (s or {}).get("note", ""),
                    "used": e.kind == "ad" or e.label in (cell or ""),
                })
            data[ch][m] = {"cell": cell, "events": details}
        stats[ch] = {"cells": sum(1 for v in data[ch].values() if v["cell"]), "low": low,
                     "ads": len(an["ads"]), "offset": hhmm(off), "clock": f"{an['clock_agree']}/{an['clock_frames']}"}
    return chans, data, stats


def render():
    chans, data, stats = build()
    css = """
    :root{--bg:#fff;--fg:#1a1a1a;--muted:#666;--line:#e3e3e3;--ad:#eef1f6;--low:#fff4cc;--chip:#f3f3f3}
    @media (prefers-color-scheme:dark){:root{--bg:#141414;--fg:#eee;--muted:#999;--line:#333;--ad:#1e2633;--low:#3a3214;--chip:#222}}
    body{font-family:-apple-system,"PingFang TC",sans-serif;background:var(--bg);color:var(--fg);margin:0;padding:16px}
    h1{font-size:20px;margin:0 0 4px} .sub{color:var(--muted);font-size:13px;margin-bottom:12px}
    .stats{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
    .stat{background:var(--chip);border-radius:8px;padding:8px 12px;font-size:13px}
    .wrap{overflow-x:auto} table{border-collapse:collapse;min-width:1100px;width:100%}
    th,td{border-bottom:1px solid var(--line);padding:6px;vertical-align:top;font-size:13px;text-align:left}
    th{position:sticky;top:0;background:var(--bg)} td.min{font-weight:600;white-space:nowrap}
    .cell{font-size:15px;font-weight:600} .ad{background:var(--ad)} .low{background:var(--low)}
    .ev{display:flex;gap:6px;margin-top:4px} .ev img{width:128px;height:72px;object-fit:cover;border-radius:4px;cursor:zoom-in}
    .ev .meta{color:var(--muted);font-size:12px;line-height:1.4} .skip{opacity:.45}
    #zoom{position:fixed;inset:0;background:rgba(0,0,0,.8);display:none;align-items:center;justify-content:center}
    #zoom img{max-width:92vw;max-height:92vh}
    """
    out = [f"<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'>"
           f"<meta name='viewport' content='width=device-width,initial-scale=1'><title>自動填表驗證頁</title>"
           f"<style>{css}</style></head><body>"
           "<h1>新聞監看自動填表：驗證頁</h1>"
           "<div class='sub'>2026/11/06 12:00–12:59｜每格附畫面截圖、播出時間、LLM 信心與理由。"
           "黃底＝信心低於 0.7 建議抽查；藍底＝廣告；半透明＝因過短（&lt;30 秒）未寫入。</div><div class='stats'>"]
    for ch in chans:
        s = stats[ch]
        out.append(f"<div class='stat'><b>{CHANNELS[ch]['name']}</b>　填 {s['cells']} 格｜廣告 {s['ads']} 段｜"
                   f"建議抽查 {s['low']}｜影片 0 秒＝{s['offset']}｜時鐘一致 {s['clock']}</div>")
    out.append("</div><div class='wrap'><table><tr><th>時間</th>")
    out += [f"<th>{CHANNELS[c]['name']}（{CHANNELS[c]['col']} 欄）</th>" for c in chans]
    out.append("</tr>")
    for m in range(START_MIN, END_MIN + 1):
        out.append(f"<tr><td class='min'>{m // 60}{m % 60:02d}</td>")
        for ch in chans:
            d = data[ch].get(m)
            if not d:
                out.append("<td></td>")
                continue
            evs = d["events"]
            cls = "ad" if any(e["kind"] == "ad" for e in evs) else (
                "low" if any(e["conf"] < LOW_CONF and e["used"] for e in evs) else "")
            parts = [f"<div class='cell'>{html.escape(d['cell'] or '（留白）')}</div>"]
            for e in evs:
                meta = (f"{e['time']}｜{e['dur']} 秒" + (f"｜信心 {e['conf']:.2f}" if e["kind"] == "news" else "")
                        + (f"<br>{html.escape(e['headline'])}" if e["headline"] else "")
                        + (f"<br>※ {html.escape(e['note'])}" if e["note"] else ""))
                img = f"<img src='{e['img']}' loading='lazy' alt=''>" if e["img"] else ""
                parts.append(f"<div class='ev {'' if e['used'] else 'skip'}'>{img}<div class='meta'>"
                             f"<b>{html.escape(e['label'])}</b><br>{meta}</div></div>")
            out.append(f"<td class='{cls}'>{''.join(parts)}</td>")
        out.append("</tr>")
    out.append("</table></div><div id='zoom' onclick=\"this.style.display='none'\"><img></div>"
               "<script>document.querySelectorAll('.ev img').forEach(i=>i.onclick=()=>{const z=document.getElementById('zoom');"
               "z.querySelector('img').src=i.src;z.style.display='flex'})</script></body></html>")
    path = OUTPUT / "驗證頁.html"
    path.write_text("".join(out), encoding="utf-8")
    return path


if __name__ == "__main__":
    print("已輸出", render())
