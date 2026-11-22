"""一鍵執行：影片 → 特徵 → 時間/廣告 → LLM 五字標 → Excel + 驗證頁。

兩種用法：
  .venv/bin/python pipeline/run.py                     # 開發模式：專案根目錄的四支影片
  .venv/bin/python pipeline/run.py --job jobs/<任務>    # 網頁程式呼叫：讀 jobs/<任務>/job.json

任務模式會持續寫 <任務>/status.json，網頁靠它顯示進度；中斷後重跑會從完成的地方接續。
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent

STAGES = [
    ("extract", "讀取影片畫面與文字"),
    ("analyze", "對時與判斷廣告"),
    ("label", "判斷新聞並寫五字標"),
    ("unify", "四台統一命名"),
    ("fill", "填入 Excel"),
    ("review", "產生驗證頁"),
]


class Status:
    def __init__(self, job_dir: Path | None):
        self.path = job_dir / "status.json" if job_dir else None
        self.data = {"state": "running", "stage": None, "stage_label": "", "started": time.time(),
                     "warnings": [], "error": None, "result": None, "stages_done": []}
        if self.path and self.path.exists():
            old = json.loads(self.path.read_text(encoding="utf-8"))
            self.data["warnings"] = []
            self.data["stages_done"] = old.get("stages_done", [])
        self.save()

    def save(self):
        if self.path:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)          # 原子寫入，網頁不會讀到寫一半的檔案

    def stage(self, key):
        self.data["stage"] = key
        self.data["stage_label"] = dict(STAGES)[key]
        print(f"▶ {self.data['stage_label']}", flush=True)
        self.save()

    def done_stage(self, key):
        if key not in self.data["stages_done"]:
            self.data["stages_done"].append(key)
        self.save()

    def warn(self, msg):
        print("⚠", msg, flush=True)
        self.data["warnings"].append(msg)
        self.save()

    def finish(self, state, **kw):
        self.data.update(state=state, finished=time.time(), **kw)
        self.save()


CHILDREN: list[subprocess.Popen] = []


def stop_children(*_):
    for p in CHILDREN:
        if p.poll() is None:
            p.terminate()
    sys.exit(130)


def fmt(sec):
    sec = int(sec)
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}"


def sanity(st, analyses, CHANNELS, START_MIN, END_MIN):
    """跑完分析後的合理性檢查：有問題寫成警告，讓使用者知道哪一台要特別看。"""
    for ch, an in analyses.items():
        name = CHANNELS[ch]["name"]
        n = len(an["frame_state"])
        if an["clock_frames"] < n * 0.3:
            st.warn(f"{name}：大部分畫面讀不到時鐘（{an['clock_frames']}/{n}），可能不是 {name} 的畫面或版面改版，結果請特別檢查。")
        elif an["clock_agree"] < an["clock_frames"] * 0.95:
            st.warn(f"{name}：時鐘讀數一致率偏低（{an['clock_agree']}/{an['clock_frames']}），時間可能有偏差。")
        first = an["offset"]
        last = an["offset"] + n
        if first > START_MIN * 60 + 120 or last < (END_MIN + 1) * 60 - 120:
            st.warn(f"{name}：影片只涵蓋 {fmt(first)}–{fmt(last)}，時段 {fmt(START_MIN * 60)}–{fmt((END_MIN + 1) * 60)} 其餘分鐘不會有資料。")
        ads = len(an["ads"])
        if ads == 0 or ads > 6:
            st.warn(f"{name}：判定出 {ads} 段廣告，與一般午間新聞（2–4 段）差異大，請在驗證頁確認。")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job")
    ap.add_argument("--skip-extract", action="store_true")
    ap.add_argument("--skip-label", action="store_true")
    a = ap.parse_args()
    job_dir = Path(a.job).resolve() if a.job else None
    if job_dir:
        os.environ["NM_JOB"] = str(job_dir)
    sys.path.insert(0, str(HERE))
    signal.signal(signal.SIGTERM, stop_children)

    st = Status(job_dir)
    t0 = time.time()
    try:
        from config import CHANNELS, END_MIN, START_MIN, WORK, video_path
        if not CHANNELS:
            raise UserError("這個任務沒有任何影片。")
        for ch in CHANNELS:
            if not video_path(ch).exists():
                raise UserError(f"找不到 {CHANNELS[ch]['name']} 的影片檔：{video_path(ch).name}")

        # ① 抽格＋辨識：四台各自一個行程平行處理（已完成的台會自動略過）
        if not a.skip_extract:
            st.stage("extract")
            env = dict(os.environ)
            for ch in CHANNELS:
                p = subprocess.Popen([sys.executable, str(HERE / "extract.py"), ch], cwd=HERE, env=env,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                p.ch = ch
                CHILDREN.append(p)
            failed = []
            for p in CHILDREN:
                out, _ = p.communicate()
                print(out, end="", flush=True)
                if p.returncode != 0:
                    failed.append((p.ch, out.strip().splitlines()[-1:] or [""]))
            if failed:
                msg = "；".join(f"{CHANNELS[c]['name']}：{m[0][:120]}" for c, m in failed)
                raise UserError(f"讀取影片失敗（{msg}）。請確認檔案完整、可以正常播放。")
            st.done_stage("extract")

        # ② 對時、廣告、分段
        st.stage("analyze")
        import analyze
        analyses = {ch: analyze.analyze(ch) for ch in CHANNELS}
        sanity(st, analyses, CHANNELS, START_MIN, END_MIN)
        st.done_stage("analyze")

        # ③ LLM
        if not a.skip_label:
            st.stage("label")
            import label
            label.label_all(list(CHANNELS))
            for w in label.WARNINGS:
                st.warn(w)
            st.done_stage("label")
            st.stage("unify")
            import unify
            try:
                evs, applied, _ = unify.unify()
                print(f"    跨台事件 {len(evs)} 組，改名 {applied} 則", flush=True)
            except Exception as e:  # noqa: BLE001  統一命名失敗不影響主結果
                st.warn(f"四台統一命名這一步失敗，已保留各台原本的五字標（{str(e)[:80]}）。")
            st.done_stage("unify")

        # ④ Excel
        st.stage("fill")
        import fill_excel
        try:
            path, res = fill_excel.fill()
        except fill_excel.TemplateError as e:
            raise UserError(str(e)) from e
        st.done_stage("fill")

        # ⑤ 驗證頁
        st.stage("review")
        import review
        page = review.render()
        chans, _, stats = review.build()
        st.done_stage("review")

        result = {
            "excel": str(path.relative_to(job_dir)) if job_dir else str(path),
            "review": str(page.relative_to(job_dir)) if job_dir else str(page),
            "seconds": round(time.time() - t0),
            "channels": {ch: {"name": CHANNELS[ch]["name"], "cells": stats[ch]["cells"],
                              "ads": stats[ch]["ads"], "low": stats[ch]["low"]} for ch in chans},
        }
        st.finish("done", result=result)
        print(f"完成，耗時 {result['seconds']} 秒\n  Excel：{path}\n  驗證頁：{page}", flush=True)
    except UserError as e:
        st.finish("error", error=str(e))
        print("✗", e, flush=True)
        sys.exit(1)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        st.finish("error", error=f"發生未預期的錯誤：{type(e).__name__}：{str(e)[:200]}。可以按「重新執行」再試一次；"
                                  f"若仍失敗，請把任務資料夾裡的 log.txt 交給維護人員。")
        sys.exit(1)


class UserError(Exception):
    """可以直接顯示給使用者看的錯誤。"""


if __name__ == "__main__":
    main()
