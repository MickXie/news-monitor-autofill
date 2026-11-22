"""LLM 介面：可以替換後端。

LLM_BACKEND=local           → 本機 Ollama（資料不離開這台電腦，沒有使用費）；LOCAL_MODEL 指定模型
LLM_BACKEND=claude          → 呼叫本機的 `claude -p`（雲端，Demo 用）
LLM_BACKEND=deepseek        → DeepSeek API（雲端），需要 DEEPSEEK_API_KEY
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path


def _extract_json(text: str):
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if m:
        text = m.group(1)
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "llm_cache"   # 跨任務共用


def _cache_key(backend: str, model: str, system: str, user: str) -> str:
    return hashlib.sha256(f"{backend}\0{model}\0{system}\0{user}".encode()).hexdigest()[:32]


def ask_json(system: str, user: str, timeout: int = 600) -> dict:
    """同一份輸入只問一次：結果存在 work/llm_cache/，重跑直接沿用（LLM_NO_CACHE=1 可強制重問）。"""
    backend = os.environ.get("LLM_BACKEND", "claude")
    model = {"deepseek": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
             "local": os.environ.get("LOCAL_MODEL", "qwen3.5:9b")}.get(
        backend, os.environ.get("CLAUDE_MODEL", "sonnet"))
    path = CACHE_DIR / f"{_cache_key(backend, model, system, user)}.json"
    if path.exists() and not os.environ.get("LLM_NO_CACHE"):
        return json.loads(path.read_text(encoding="utf-8"))
    if backend == "local":
        res = _local(system, user, timeout, model)
    elif backend == "deepseek":
        res = _deepseek(system, user, timeout)
    else:
        res = _claude_cli(system, user, timeout)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    return res


def _claude_cli(system: str, user: str, timeout: int) -> dict:
    model = os.environ.get("CLAUDE_MODEL", "sonnet")
    prompt = f"{system}\n\n---\n\n{user}\n\n只輸出 JSON，不要其他文字。"
    p = subprocess.run(
        ["claude", "-p", "--output-format", "json", "--model", model],
        input=prompt, capture_output=True, text=True, timeout=timeout,
    )
    if p.returncode != 0:
        raise RuntimeError(f"claude CLI 失敗：{p.stderr[:500]}")
    outer = json.loads(p.stdout)
    return _extract_json(outer.get("result", ""))


def _deepseek(system: str, user: str, timeout: int) -> dict:
    key = os.environ["DEEPSEEK_API_KEY"]
    body = {
        "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    return _extract_json(data["choices"][0]["message"]["content"])


OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")


def _local(system: str, user: str, timeout: int, model: str) -> dict:
    """本機 Ollama。只連 127.0.0.1，資料不會送出這台電腦。"""
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system + "\n\n一律使用繁體中文（台灣用字）。"},
                     {"role": "user", "content": user + "\n\n只輸出 JSON，不要其他文字。"}],
        "stream": False,
        # 不用 "format": "json"：Ollama 以 Apple MLX 引擎執行時不支援（回 501），改由指令要求輸出 JSON
        "think": False,                       # 不要長篇推理，直接給答案（快很多）
        "keep_alive": "5m",                   # 用完 5 分鐘沒新工作就釋放記憶體
        "options": {"temperature": 0, "num_ctx": 16384, "seed": 7},
    }
    req = urllib.request.Request(f"{OLLAMA_URL}/api/chat", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
    except urllib.error.URLError as e:
        raise RuntimeError(f"連不上本機 AI（Ollama），請確認已啟動：{e}") from e
    return _extract_json(data["message"]["content"])


def as_int(v, default=None):
    """AI 有時把數字寫成字串（"12"）或小數（12.0）；一律轉成整數，轉不了回傳 default。"""
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return default


def as_float(v, default=0.5):
    try:
        return max(0.0, min(1.0, float(str(v).strip())))
    except (TypeError, ValueError):
        return default
