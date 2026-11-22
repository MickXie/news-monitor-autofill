"""新聞監看自動填表：本機網頁程式（後端）。

只在這台 Mac 上執行（127.0.0.1），用瀏覽器操作。
- 每次處理是一個「任務」，放在 jobs/<任務編號>/：videos/ 影片、job.json 設定、status.json 進度、
  log.txt 紀錄、work/ 中間檔、output/ 成果（Excel、驗證頁）。
- 同一時間只跑一個任務，其餘排隊；處理在獨立的子行程裡進行，網頁關掉也不影響。
- 程式被關閉時正在跑的任務，下次開啟會標成「中斷」，按「繼續執行」會從完成的地方接續。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_from_directory

ROOT = Path(__file__).resolve().parent.parent
PIPE = ROOT / "pipeline"
JOBS = ROOT / "jobs"
DATA = ROOT / "data"
STATIC = Path(__file__).resolve().parent / "static"
SETTINGS = DATA / "settings.json"
PY = sys.executable
PORT = int(os.environ.get("NM_PORT", 8790))

sys.path.insert(0, str(PIPE))
from config import CHANNELS, DEFAULT_TEMPLATE  # noqa: E402

JOBS.mkdir(exist_ok=True)
DATA.mkdir(exist_ok=True)
app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = None
LOCK = threading.Lock()
RUNNING: dict[str, subprocess.Popen] = {}

STATE_NAMES = {"queued", "running", "done", "error", "interrupted", "cancelled"}
DEFAULT_SETTINGS = {"backend": "local", "local_model": "qwen3.5:9b", "deepseek_key": "", "delete_videos": True}


# ---------------- 共用 ----------------
def load_settings():
    s = dict(DEFAULT_SETTINGS)
    if SETTINGS.exists():
        s.update(json.loads(SETTINGS.read_text(encoding="utf-8")))
    return s


def jdir(jid):
    if not re.fullmatch(r"[0-9a-z_-]{6,40}", jid or ""):
        abort(404)
    d = JOBS / jid
    if not d.exists():
        abort(404)
    return d


def read_json(p, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def write_json(p, data):
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def job_view(d: Path):
    job = read_json(d / "job.json", {})
    st = read_json(d / "status.json")
    state = job.get("state", "draft")           # 狀態以 job.json 為準，由背景執行緒更新
    prog = {}
    for ch in job.get("videos", {}):
        p = read_json(d / "work" / ch / "progress.json")
        if p:
            prog[ch] = p
    return {**job, "state": state, "status": st, "progress": prog,
            "channel_names": {k: v["name"] for k, v in CHANNELS.items()}}


def ok(**kw):
    return jsonify({"ok": True, **kw})


def fail(msg, code=400):
    return jsonify({"ok": False, "error": msg}), code


# ---------------- 任務 ----------------
@app.post("/api/jobs")
def create_job():
    jid = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
    d = JOBS / jid
    (d / "videos").mkdir(parents=True)
    write_json(d / "job.json", {"id": jid, "created": time.time(), "state": "draft",
                                "date": "", "slot_hour": None, "files": [], "videos": {}, "template": None})
    return ok(id=jid)


@app.get("/api/jobs")
def list_jobs():
    out = []
    for d in sorted(JOBS.iterdir(), reverse=True):
        if (d / "job.json").exists():
            v = job_view(d)
            if v["state"] == "draft" or v["state"] not in STATE_NAMES:   # 草稿與內部測試任務不列出
                continue
            out.append({k: v.get(k) for k in ("id", "created", "state", "date", "slot_hour", "videos")} |
                       {"result": (v.get("status") or {}).get("result"),
                        "error": (v.get("status") or {}).get("error")})
    return ok(jobs=out)


@app.get("/api/jobs/<jid>")
def get_job(jid):
    return ok(job=job_view(jdir(jid)))


@app.delete("/api/jobs/<jid>")
def delete_job(jid):
    d = jdir(jid)
    if jid in RUNNING:
        return fail("任務正在執行，請先按「停止」。")
    shutil.rmtree(d)
    return ok()


@app.put("/api/jobs/<jid>/files")
def upload(jid):
    """以串流方式接收一支影片（不整支讀進記憶體），存完後自動辨識台別與時間。"""
    d = jdir(jid)
    name = Path(request.args.get("name", "")).name
    if not name or not re.search(r"\.(mp4|mov|ts|mkv|m4v|mxf)$", name, re.I):
        return fail("只能放影片檔（mp4、mov、ts、mkv）。")
    size = int(request.headers.get("Content-Length") or 0)
    free = shutil.disk_usage(JOBS).free
    if size and free < size * 1.5 + 2e9:
        return fail(f"磁碟空間不足：這支影片 {size / 1e9:.1f} GB，剩餘 {free / 1e9:.1f} GB。請先刪除舊任務或清出空間。")
    dest = d / "videos" / name
    tmp = dest.with_suffix(dest.suffix + ".part")
    with open(tmp, "wb") as f:
        while True:
            chunk = request.stream.read(8 * 1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
    if size and tmp.stat().st_size != size:
        tmp.unlink(missing_ok=True)
        return fail("上傳中斷，檔案不完整，請重新放一次。")
    tmp.replace(dest)
    from probe import probe
    info = probe(dest)
    info["path"] = str(dest)
    info["size"] = dest.stat().st_size
    with LOCK:
        job = read_json(d / "job.json")
        job["files"] = [f for f in job["files"] if f["file"] != name] + [info]
        if info.get("channel") and info["channel"] not in job["videos"]:
            job["videos"][info["channel"]] = str(dest)
        # 日期、時段：沒填過就用影片推測（檔名中的 8 位數日期、畫面時鐘的小時）
        m = re.search(r"(20\d{2})(\d{2})(\d{2})", name)
        if not job.get("date") and m:
            job["date"] = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        if job.get("slot_hour") is None and info.get("clock_start"):
            h, mm = map(int, info["clock_start"].split(":"))
            job["slot_hour"] = (h + 1) % 24 if mm >= 50 else h
        write_json(d / "job.json", job)
    return ok(file=info, job=job_view(d))


@app.delete("/api/jobs/<jid>/files/<name>")
def remove_file(jid, name):
    d = jdir(jid)
    with LOCK:
        job = read_json(d / "job.json")
        f = next((f for f in job["files"] if f["file"] == name), None)
        if not f:
            abort(404)
        job["files"].remove(f)
        job["videos"] = {k: v for k, v in job["videos"].items() if Path(v).name != name}
        write_json(d / "job.json", job)
    (d / "videos" / Path(name).name).unlink(missing_ok=True)
    return ok(job=job_view(d))


@app.post("/api/jobs/<jid>/config")
def set_config(jid):
    """設定：每支影片是哪一台、日期、時段。"""
    d = jdir(jid)
    body = request.get_json(force=True)
    with LOCK:
        job = read_json(d / "job.json")
        if "assign" in body:                  # {檔名: 台別代號或 ""}
            videos = {}
            for f in job["files"]:
                ch = body["assign"].get(f["file"], "")
                if ch:
                    if ch in videos:
                        return fail(f"「{CHANNELS[ch]['name']}」被指定給兩支影片，請確認。")
                    videos[ch] = f["path"]
            job["videos"] = videos
        if "date" in body:
            job["date"] = body["date"]
        if "slot_hour" in body:
            job["slot_hour"] = int(body["slot_hour"])
        write_json(d / "job.json", job)
    return ok(job=job_view(d))


@app.put("/api/jobs/<jid>/template")
def upload_template(jid):
    d = jdir(jid)
    dest = d / "template.xlsx"
    dest.write_bytes(request.get_data())
    msg = check_template(dest, read_json(d / "job.json").get("slot_hour"))
    if msg:
        dest.unlink(missing_ok=True)
        return fail(msg)
    with LOCK:
        job = read_json(d / "job.json")
        job["template"] = str(dest)
        job["template_name"] = Path(request.args.get("name", "template.xlsx")).name
        write_json(d / "job.json", job)
    return ok(job=job_view(d))


def check_template(path, hour):
    import openpyxl
    from fill_excel import locate
    if not Path(path).exists():
        return "找不到預設的監看表範本，請在步驟 2 按「換用其他範本」上傳你們的監看表 Excel。"
    try:
        ws = openpyxl.load_workbook(path).worksheets[0]
    except Exception:  # noqa: BLE001
        return "這個檔案打不開，請確認是 Excel（.xlsx）檔。"
    minute_row, col_of = locate(ws)
    if not minute_row:
        return "範本 A 欄找不到時間（例如 1200、1201…），請確認是監看表範本。"
    if hour is not None and hour * 60 not in minute_row:
        return f"範本裡沒有 {hour:02d}:00 這個時段的時間列。"
    miss = [CHANNELS[c]["name"] for c in CHANNELS if c not in col_of]
    if len(miss) == len(CHANNELS):
        return "範本表頭找不到任何一台的台名（TVBS-N、東森、民視、華視）。"
    return None


@app.post("/api/jobs/<jid>/start")
def start(jid):
    d = jdir(jid)
    with LOCK:
        job = read_json(d / "job.json")
        problems = []
        if not job["videos"]:
            problems.append("還沒有可以處理的影片（每支影片都要指定是哪一台）。")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", job.get("date") or ""):
            problems.append("請填監看日期。")
        if job.get("slot_hour") is None:
            problems.append("請選時段。")
        if not problems:
            msg = check_template(Path(job.get("template") or DEFAULT_TEMPLATE), job["slot_hour"])
            if msg:
                problems.append(msg)
        if problems:
            return fail(" ".join(problems))
        job["slot_start"] = job["slot_hour"] * 60
        job["slot_end"] = job["slot_hour"] * 60 + 59
        job["state"] = "queued"
        job["queued_at"] = time.time()
        write_json(d / "job.json", job)
    WAKE.set()
    return ok(job=job_view(d))


@app.post("/api/jobs/<jid>/cancel")
def cancel(jid):
    d = jdir(jid)
    p = RUNNING.get(jid)
    if p and p.poll() is None:
        os.killpg(p.pid, signal.SIGTERM)
    with LOCK:
        job = read_json(d / "job.json")
        job["state"] = "cancelled"
        write_json(d / "job.json", job)
    return ok(job=job_view(d))


@app.get("/jobs/<jid>/output/<path:p>")
def output_file(jid, p):
    d = jdir(jid) / "output"
    as_att = p.endswith(".xlsx")
    return send_from_directory(d, p, as_attachment=as_att)


# ---------------- 設定 ----------------
@app.get("/api/settings")
def get_settings():
    s = load_settings()
    key = s.get("deepseek_key", "")
    return ok(settings={**s, "deepseek_key": "", "has_key": bool(key),
                        "key_hint": (key[:4] + "…" + key[-4:]) if len(key) > 10 else "",
                        "claude_available": bool(claude_path()),
                        "local_available": bool(ollama_path()), "local_models": local_models()})


@app.post("/api/settings")
def save_settings():
    body = request.get_json(force=True)
    s = load_settings()
    for k in ("backend", "delete_videos", "local_model"):
        if k in body:
            s[k] = body[k]
    if body.get("deepseek_key"):
        s["deepseek_key"] = body["deepseek_key"].strip()
    write_json(SETTINGS, s)
    os.chmod(SETTINGS, 0o600)
    return get_settings()


@app.post("/api/settings/test")
def test_llm():
    s = load_settings()
    if s.get("backend") == "local":
        msg = ensure_ollama()
        if msg:
            return fail(msg)
    env = llm_env(s)
    code = ("import sys; sys.path.insert(0, %r); from llm import ask_json; "
            "print(ask_json('只回傳 JSON', '請回傳 {\"ok\": true}'))" % str(PIPE))
    env["LLM_NO_CACHE"] = "1"
    try:
        p = subprocess.run([PY, "-c", code], env=env, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return fail("連線逾時（超過 2 分鐘沒有回應）。")
    if p.returncode == 0 and "True" in p.stdout:
        return ok(message="連線成功，可以使用。")
    err = (p.stderr or p.stdout).strip().splitlines()[-1:] or ["未知錯誤"]
    hint = "（金鑰可能錯誤或額度用完）" if "401" in err[0] or "402" in err[0] else ""
    return fail(f"連線失敗{hint}：{err[0][:200]}")


# ---------------- 本機 AI（Ollama） ----------------
OLLAMA = {"proc": None}
OLLAMA_URL = "http://127.0.0.1:11434"


def ollama_path():
    return shutil.which("ollama") or next((p for p in ("/opt/homebrew/bin/ollama", "/usr/local/bin/ollama")
                                           if Path(p).exists()), None)


def ollama_up():
    import urllib.request
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/version", timeout=2):
            return True
    except Exception:  # noqa: BLE001
        return False


def local_models():
    import urllib.request
    if not ollama_up():
        return []
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=3) as r:
            return sorted(m["name"] for m in json.loads(r.read())["models"])
    except Exception:  # noqa: BLE001
        return []


def ensure_ollama():
    """需要本機 AI 時才啟動 Ollama（不設開機自動啟動）；回傳 None 表示可用，否則回傳給使用者看的原因。"""
    if ollama_up():
        return None
    exe = ollama_path()
    if not exe:
        return "這台電腦還沒安裝本機 AI（Ollama），請依使用說明安裝，或到設定改用其他 AI 服務。"
    env = dict(os.environ, OLLAMA_FLASH_ATTENTION="1", OLLAMA_KV_CACHE_TYPE="q8_0", OLLAMA_HOST="127.0.0.1:11434")
    log = open(DATA / "ollama.log", "a")
    OLLAMA["proc"] = subprocess.Popen([exe, "serve"], env=env, stdout=log, stderr=log, start_new_session=True)
    for _ in range(30):
        if ollama_up():
            return None
        time.sleep(0.5)
    return "本機 AI 啟動失敗，請把 data/ollama.log 交給維護人員。"


def local_status():
    """本機 AI 目前狀態：是否執行中、載入了哪些模型、佔多少記憶體。"""
    import urllib.request
    if not ollama_up():
        return {"running": False, "loaded": [], "mem_gb": 0}
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/ps", timeout=3) as r:
            ms = json.loads(r.read()).get("models", [])
    except Exception:  # noqa: BLE001
        ms = []
    return {"running": True, "loaded": [m["name"] for m in ms],
            "mem_gb": round(sum(m.get("size_vram") or m.get("size", 0) for m in ms) / 1e9, 1),
            "started_by_app": bool(OLLAMA["proc"] and OLLAMA["proc"].poll() is None)}


@app.get("/api/local")
def api_local():
    return ok(status=local_status())


@app.post("/api/local/start")
def api_local_start():
    msg = ensure_ollama()
    return fail(msg) if msg else ok(status=local_status())


@app.post("/api/local/stop")
def api_local_stop():
    """關閉本機 AI：處理中不允許；先卸下模型釋放記憶體，再結束 Ollama。"""
    import urllib.request
    if any(p.poll() is None for p in RUNNING.values()):
        return fail("目前有任務正在處理，請等處理完或先按「停止處理」。")
    for name in local_status()["loaded"]:
        try:
            req = urllib.request.Request(f"{OLLAMA_URL}/api/generate", method="POST",
                                         data=json.dumps({"model": name, "keep_alive": 0}).encode())
            urllib.request.urlopen(req, timeout=20).read()
        except Exception:  # noqa: BLE001
            pass
    if OLLAMA["proc"] and OLLAMA["proc"].poll() is None:
        OLLAMA["proc"].terminate()
        OLLAMA["proc"].wait(timeout=10)
    elif ollama_up():
        subprocess.run(["pkill", "-x", "ollama"])        # 不是本程式啟動的也一併關閉（使用者明確按了關閉）
    for _ in range(20):
        if not ollama_up():
            break
        time.sleep(0.5)
    return ok(status=local_status())


def claude_path():
    return shutil.which("claude") or next((str(p) for p in [Path.home() / ".local/bin/claude"] if p.exists()), None)


def llm_env(s):
    env = dict(os.environ)
    env["LLM_BACKEND"] = s.get("backend", "local")
    env["LOCAL_MODEL"] = s.get("local_model", "qwen3.5:9b")
    if s.get("deepseek_key"):
        env["DEEPSEEK_API_KEY"] = s["deepseek_key"]
    cp = claude_path()
    if cp:
        env["PATH"] = str(Path(cp).parent) + os.pathsep + env.get("PATH", "")
    return env


# ---------------- 背景執行 ----------------
WAKE = threading.Event()


def worker():
    while True:
        WAKE.wait(5)
        WAKE.clear()
        queued = []
        for d in JOBS.iterdir():
            job = read_json(d / "job.json")
            if job and job.get("state") == "queued":
                queued.append((job.get("queued_at", 0), d, job))
        for _, d, job in sorted(queued, key=lambda x: x[0])[:1]:
            run_job(d, job)


def run_job(d: Path, job: dict):
    jid = job["id"]
    with LOCK:
        job = read_json(d / "job.json")
        if job.get("state") != "queued":
            return
        job["state"] = "running"
        job["started"] = time.time()
        write_json(d / "job.json", job)
    s = load_settings()
    if s.get("backend") == "local":
        msg = ensure_ollama()
        if msg:                                  # 本機 AI 起不來：照樣跑，寫五字標那段會改用備案並警告
            with open(d / "log.txt", "a", encoding="utf-8") as log:
                log.write(f"[本機 AI] {msg}\n")
    env = llm_env(s)
    env["PYTHONUNBUFFERED"] = "1"
    with open(d / "log.txt", "a", encoding="utf-8") as log:
        log.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} 開始 =====\n")
        log.flush()
        p = subprocess.Popen([PY, str(PIPE / "run.py"), "--job", str(d)], cwd=ROOT, env=env,
                             stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        RUNNING[jid] = p
        with LOCK:
            j2 = read_json(d / "job.json")
            j2["pid"] = p.pid
            write_json(d / "job.json", j2)
        # 執行期間不讓 Mac 進入睡眠
        caf = subprocess.Popen(["caffeinate", "-i", "-w", str(p.pid)]) if shutil.which("caffeinate") else None
        p.wait()
        RUNNING.pop(jid, None)
        if caf:
            caf.wait(timeout=5)
    st = read_json(d / "status.json", {}) or {}
    with LOCK:
        job = read_json(d / "job.json")
        if job.get("state") != "cancelled":
            job["state"] = st.get("state") if st.get("state") in ("done", "error") else "error"
            if job["state"] == "error" and not st.get("error"):
                st["error"] = "處理程式意外結束，請按「重新執行」，若仍失敗請把 log.txt 交給維護人員。"
                st["state"] = "error"
                write_json(d / "status.json", st)
        job["finished"] = time.time()
        write_json(d / "job.json", job)
    if job["state"] == "done" and s.get("delete_videos"):
        shutil.rmtree(d / "videos", ignore_errors=True)   # 上傳的是副本，原檔仍在使用者電腦上
        with LOCK:
            job = read_json(d / "job.json")
            job["videos_deleted"] = True
            write_json(d / "job.json", job)
    WAKE.set()


def kill_group(pid):
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass


def recover():
    """程式上次被關掉時還在跑的任務 → 停掉遺留的處理行程，並標成中斷，等使用者按「繼續執行」。"""
    for d in JOBS.iterdir():
        job = read_json(d / "job.json")
        if job and job.get("state") == "running":
            if job.get("pid"):
                kill_group(job["pid"])
            job["state"] = "interrupted"
            write_json(d / "job.json", job)


def shutdown(*_):
    """關閉黑色視窗（SIGHUP）或按 Ctrl+C 時，一併停掉處理中的任務與本程式啟動的本機 AI，避免留下沒人管的行程。"""
    if OLLAMA["proc"] and OLLAMA["proc"].poll() is None:
        OLLAMA["proc"].terminate()
    for jid, p in list(RUNNING.items()):
        if p.poll() is None:
            kill_group(p.pid)
            d = JOBS / jid
            job = read_json(d / "job.json")
            if job:
                job["state"] = "interrupted"
                write_json(d / "job.json", job)
    os._exit(0)


@app.post("/api/jobs/<jid>/resume")
def resume(jid):
    d = jdir(jid)
    with LOCK:
        job = read_json(d / "job.json")
        if job.get("videos_deleted"):
            return fail("這個任務的影片已在完成後刪除，請建立新任務重新放入影片。")
        job["state"] = "queued"
        job["queued_at"] = time.time()
        write_json(d / "job.json", job)
    WAKE.set()
    return ok(job=job_view(d))


# ---------------- 頁面 ----------------
@app.get("/")
def index():
    return send_from_directory(STATIC, "index.html")


@app.get("/static/<path:p>")
def static_file(p):
    return send_from_directory(STATIC, p)


@app.get("/api/health")
def health():
    return ok(channels={k: v["name"] for k, v in CHANNELS.items()})


def free_port(start):
    """預設 port 被別的程式占用時（macOS 內建服務有時會用），往後找一個空的。"""
    import socket
    for p in range(start, start + 20):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise SystemExit("找不到可用的連接埠，請重新開機後再試。")


def main():
    for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, shutdown)
    recover()
    threading.Thread(target=worker, daemon=True).start()
    WAKE.set()
    port = free_port(PORT)
    (DATA / "port.txt").write_text(str(port))          # 啟動檔靠它知道要開哪個網址
    print(f"新聞監看自動填表已啟動：http://127.0.0.1:{port}", flush=True)
    app.run(host="127.0.0.1", port=port, threaded=True, debug=False)


if __name__ == "__main__":
    main()
