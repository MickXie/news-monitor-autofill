"""上傳後的影片自動辨識：是哪一台、多長、畫面時鐘顯示的起訖時間。

不靠檔名判斷台別（例如華視的檔名可能叫 cti_…），而是讀畫面右上角的台標；
讀不到台標時才參考檔名，兩者都沒有就回傳 None，讓使用者在網頁上自己選。
"""
from __future__ import annotations

import re
import subprocess
from collections import Counter
from pathlib import Path

import imageio_ffmpeg
import numpy as np

from config import CHANNELS, W, H
from extract import duration
from ocr import ocr

FF = imageio_ffmpeg.get_ffmpeg_exe()
CLOCK_RE = re.compile(r"(1\d|2[0-3]|0\d)\s*[:：]\s*([0-5]\d)")
LOGO_BOX = (700, 0, 1280, 140)          # 右上角台標區
NAME_HINT = {"tvbs": "tvbs", "ebc": "ebc", "ftv": "ftv", "cts": "cts"}


def grab(video, t):
    raw = subprocess.run([FF, "-v", "error", "-ss", f"{max(t, 0):.1f}", "-i", str(video), "-frames:v", "1",
                          "-vf", f"scale={W}:{H}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True).stdout
    if len(raw) < W * H * 3:
        return None
    return np.frombuffer(raw, np.uint8).reshape(H, W, 3)


def guess_channel(frames, filename):
    score = Counter()
    for img in frames:
        x0, y0, x1, y1 = LOGO_BOX
        txt = "".join(t for t, _, _ in ocr(img[y0:y1, x0:x1])).upper().replace(" ", "")
        for ch, cfg in CHANNELS.items():
            if any(k.upper() in txt for k in cfg["logo"]):
                score[ch] += 1
    if score:
        ch, n = score.most_common(1)[0]
        return ch, "畫面台標", n
    low = filename.lower()
    for key, ch in NAME_HINT.items():
        if low.startswith(key) and ch in CHANNELS:
            return ch, "檔名", 0
    return None, "無法判斷", 0


def read_clock(video, ch, ts):
    roi = CHANNELS[ch]["roi"]["clock"]
    for t in ts:
        img = grab(video, t)
        if img is None:
            continue
        x0, y0, x1, y1 = roi
        txt = " ".join(s for s, _, _ in ocr(img[y0:y1, x0:x1]))
        m = CLOCK_RE.search(txt)
        if m:
            return f"{int(m.group(1)):02d}:{m.group(2)}"
    return None


def probe(video: Path) -> dict:
    dur = duration(video)
    info = {"file": video.name, "duration": round(dur), "ok": dur > 0}
    if dur <= 0:
        info["error"] = "讀不到影片長度，檔案可能損毀或不是影片。"
        return info
    samples = [t for t in (30, 120, 600, dur / 2, dur - 120) if 0 <= t < dur]
    frames = [f for f in (grab(video, t) for t in samples) if f is not None]
    if not frames:
        info.update(ok=False, error="影片讀不出畫面，檔案可能損毀或格式不支援。")
        return info
    ch, how, hits = guess_channel(frames, video.name)
    info.update(channel=ch, channel_by=how, logo_hits=hits)
    if ch:
        info["clock_start"] = read_clock(video, ch, [20, 40, 70, 100, 140])
        info["clock_end"] = read_clock(video, ch, [dur - 20, dur - 45, dur - 80, dur - 120])
    return info


if __name__ == "__main__":
    import json
    import sys
    for p in sys.argv[1:]:
        print(json.dumps(probe(Path(p)), ensure_ascii=False))
