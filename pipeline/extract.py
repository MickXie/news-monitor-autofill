"""第 1 步：從影片每秒抽一格畫面，讀出各區域的文字，存成 frames.jsonl。

每一列記錄一秒：
  t       影片內的秒數
  clock   時鐘區辨識出的字（例如 "12:09"、"11/06(五)"）
  title   標題區每一行文字 [(文字, 字高, x0)]
  loc/tag 地點標、左上短標
  wrap    廣告包框特徵區的文字（只有民視）
  bar     標題區的平均顏色（判斷 bar 是否存在用）
同時存一張小縮圖，供驗證頁使用。

穩定性設計：
- 影片不論解析度，一律先縮放成 1280x720，畫面區域座標才會對。
- 每 10 秒寫一次 progress.json（給網頁顯示進度）。
- 完成後寫 done.json；中斷後重跑會從 frames.jsonl 最後一格接續，不必從頭來。

用法：python extract.py tvbs [--limit 秒數]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import time

import imageio_ffmpeg
import numpy as np
from PIL import Image

from config import CHANNELS, WORK, W, H, video_path
from ocr import ocr

FF = imageio_ffmpeg.get_ffmpeg_exe()


def crop(img, box):
    x0, y0, x1, y1 = box
    return img[y0:y1, x0:x1]


def read_lines(img):
    """回傳 [(文字, 字高, x0, 信心)]，依由上到下、由左到右排序。"""
    res = ocr(img)
    res.sort(key=lambda r: (round(r[2][1] / 20), r[2][0]))
    return [(s, round(b[3] - b[1], 1), round(b[0], 1), round(c, 2)) for s, c, b in res]


def duration(video) -> float:
    """用 ffmpeg 讀影片長度（秒）；讀不到回傳 0。"""
    p = subprocess.run([FF, "-hide_banner", "-i", str(video)], capture_output=True, text=True)
    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", p.stderr)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0


def resume_point(path):
    """frames.jsonl 已有幾格完整紀錄（最後一行可能寫一半，丟掉）。"""
    if not path.exists():
        return 0
    lines = path.read_text(encoding="utf-8").splitlines()
    good = []
    for ln in lines:
        try:
            json.loads(ln)
            good.append(ln)
        except json.JSONDecodeError:
            break
    path.write_text("".join(l + "\n" for l in good), encoding="utf-8")
    return len(good)


def write_progress(out_dir, done, total, started, status="running", start=0):
    elapsed = time.time() - started
    (out_dir / "progress.json").write_text(json.dumps(
        {"done": done, "total": total, "elapsed": round(elapsed), "status": status, "start": start}), encoding="utf-8")


def run(ch: str, limit: int | None = None):
    cfg = CHANNELS[ch]
    out_dir = WORK / ch
    thumbs = out_dir / "thumbs"
    thumbs.mkdir(parents=True, exist_ok=True)
    if (out_dir / "done.json").exists() and not limit:
        print(f"[{ch}] 已完成，略過", flush=True)
        return
    video = video_path(ch)
    total = int(limit or duration(video))
    frames_path = out_dir / "frames.jsonl"
    start = resume_point(frames_path)

    cmd = [FF, "-v", "error", "-hwaccel", "videotoolbox"]
    if start:
        cmd += ["-ss", str(start)]
    cmd += ["-i", str(video)]
    if limit:
        cmd += ["-t", str(max(limit - start, 0))]
    cmd += ["-vf", f"fps=1,scale={W}:{H}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=W * H * 3 * 4)

    roi = cfg["roi"]
    n = start
    t0 = time.time()
    write_progress(out_dir, n, total, t0, start=start)
    with open(frames_path, "a", encoding="utf-8") as f:
        while True:
            buf = proc.stdout.read(W * H * 3)
            if len(buf) < W * H * 3:
                break
            img = np.frombuffer(buf, np.uint8).reshape(H, W, 3)
            rec = {"t": n}
            rec["clock"] = " ".join(l[0] for l in read_lines(crop(img, roi["clock"])))
            rec["title"] = read_lines(crop(img, roi["title"]))
            for k in ("loc", "tag", "wrap"):
                if k in roi:
                    rec[k] = " ".join(l[0] for l in read_lines(crop(img, roi[k])))
            bar = crop(img, roi["title"]).reshape(-1, 3)
            rec["bar"] = [int(v) for v in bar.mean(0)]
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            Image.fromarray(img).resize((320, 180)).save(thumbs / f"{n:05d}.jpg", quality=60)
            n += 1
            if n % 10 == 0:
                f.flush()
                write_progress(out_dir, n, total, t0, start=start)
            if n % 300 == 0:
                print(f"[{ch}] {n}s 已處理，耗時 {time.time() - t0:.0f}s", flush=True)
    proc.wait()
    err = proc.stderr.read().decode(errors="ignore").strip()
    if n == 0:
        write_progress(out_dir, 0, total, t0, "error")
        raise SystemExit(f"[{ch}] 影片讀不出任何畫面，檔案可能損毀或格式不支援。{err[:200]}")
    write_progress(out_dir, n, max(total, n), t0, "done", start)
    if not limit:
        (out_dir / "done.json").write_text(json.dumps({"frames": n}), encoding="utf-8")
    print(f"[{ch}] 完成：{n} 格，耗時 {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("channel", choices=list(CHANNELS))
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    run(a.channel, a.limit)
