"""第 3.5 步：跨台同一事件統一五字標，並累積「事件命名表」。

為什麼：收視率與編播分析要比較「同一事件在各台的表現」，各台寫法不同就對不起來；
命名表也讓之後的時段、隔天遇到同一事件時沿用同一個名字。

規則：
- 只有「同一起具體事件」才歸為一組（同一場火災、同一車禍、同一人的同一件事），
  只是同一大主題的不同角度（例如台股崩跌下的國安基金、0050）不算。
- 某台在同一組內有 2 則以上（代表該台拆成不同角度報導）→ 該台不統一，避免被誤合併。
- 統一後的名字仍要通過 label.problems() 的規則檢查，不通過就保留原名。
"""
from __future__ import annotations

import json
from datetime import date

from config import CHANNELS, DATA, RUN_KEY, WORK
from label import clean, problems
from llm import as_int, ask_json

REGISTRY = DATA / "event_registry.json"   # 跨任務共用、長期累積

SYSTEM = """你是新聞監看表的總編輯。以下是同一時段四個電視台各自整理出的新聞（含各台自己寫的五字標）。
請找出「不同台在報同一起具體事件」的新聞，為每個事件定一個統一的五字標。

同一事件的判斷：同一場火災、同一起車禍、同一個人的同一件事、同一份數據公布等。
只是同一大主題的不同角度（例如台股崩跌下的「國安基金」與「0050」、選戰中不同候選人的行程）不算同一事件，要分開。

統一五字標規則：原則上 5 個中文字（必要時 4–6 字）；讓看表的人一眼認出事件；社會事件要有地點，且只能用 place 或 headline 中出現的地點、
優先最具體的地名；不可出現「廣告」；指控類若 headline 沒有起訴、求刑、判決、落網等字眼，要用中性詞。
統一名字不得改變任何一台原本的意思，不可產生新的指控或評價（例如把「兒虐數據爭議」寫成「某某兒虐案」）。
天氣預報一律維持「氣象」，不要改名。
若「既有命名表」中已有同一事件，請直接沿用該名字。

輸出 JSON（字串內不要用半形雙引號）：
{"events": [{"label": "統一五字標", "members": [編號...], "reason": "為何是同一事件"}]}
只輸出含 2 個以上不同台的事件。"""


RISKY = ("案", "涉", "黑幫", "傲慢", "說謊", "貪", "詐", "殺", "罪")


def safe_rename(s, canon):
    """統一名字只能讓原名「一樣或更好」，以下情況保留原名：
    - 原名是「氣象」（範例慣例）
    - 原名帶地點（place 欄的地名）而新名沒有 → 社會新聞會失去地點
    - 新名出現原名與標題都沒有的評價/指控字眼 → 可能改變原意
    """
    orig, head, place = s["label_orig"], s.get("headline", ""), s.get("place", "")
    if orig == "氣象":
        return False, "原名為氣象"
    places = [p for p in place.replace("、", " ").replace("/", " ").split() if p]
    for p in places + [p[:2] for p in places if len(p) > 2]:
        if p in orig and p not in canon:
            return False, f"新名失去地點「{p}」"
    for w in RISKY:
        if w in canon and w not in orig and w not in head:
            return False, f"新名多出「{w}」"
    return True, ""


def load_registry():
    if REGISTRY.exists():
        return json.loads(REGISTRY.read_text(encoding="utf-8"))
    return []


def unify(channels=None):
    channels = channels or list(CHANNELS)
    items = []
    stories = {}
    for ch in channels:
        stories[ch] = json.load(open(WORK / ch / "stories.json", encoding="utf-8"))
        for j, s in enumerate(stories[ch]["stories"]):
            s.setdefault("label_orig", s["label"])
            items.append((ch, j, s))
    reg = load_registry()
    # 只參考「其他時段」累積的名字：同一時段重跑時輸入完全相同 → 命中快取 → 結果一致
    reg_other = [r for r in reg if r.get("source") != RUN_KEY]
    lines = [f"{i} | {CHANNELS[ch]['name']} | {s['start']} | {clean(s['label_orig'])} | "
             f"{clean(s.get('headline', ''))} | {clean(s.get('place', ''))}" for i, (ch, j, s) in enumerate(items)]
    reg_txt = "\n".join(f"- {r['label']}：{r['headline']}" for r in reg_other[-200:]) or "（尚無）"
    res = ask_json(SYSTEM, f"既有命名表：\n{reg_txt}\n\n各台新聞（編號 | 台 | 開始 | 原五字標 | 標題 | 地點）：\n" + "\n".join(lines))

    applied, skipped = 0, 0
    today = date.today().isoformat()
    reg = reg_other                     # 本時段的舊紀錄以這次結果重建
    known = {r["label"] for r in reg}
    for ev in res.get("events", []):
        if not isinstance(ev, dict) or not str(ev.get("label") or "").strip():
            continue
        members = [m for m in (as_int(x) for x in ev.get("members", []) or []) if m is not None and 0 <= m < len(items)]
        by_ch = {}
        for m in members:
            by_ch.setdefault(items[m][0], []).append(m)
        if len(by_ch) < 2:
            continue
        canon = ev["label"]
        probe = {"label": canon, "headline": items[members[0]][2].get("headline", "")}
        if problems(probe):
            skipped += 1
            continue
        for ch, ms in by_ch.items():
            if len(ms) > 1:   # 該台拆成多則不同角度 → 不統一
                continue
            s = items[ms[0]][2]
            ok, why = safe_rename(s, canon)
            if not ok:
                s["note"] = (s.get("note", "") + f"｜跨台統一略過（{why}）：保留 {s['label_orig']}").strip("｜")
                skipped += 1
                continue
            if s["label"] != canon:
                s["note"] = (s.get("note", "") + f"｜跨台統一：{s['label_orig']}→{canon}").strip("｜")
                s["label"] = canon
                applied += 1
            s["event"] = canon
        if canon not in known:
            reg.append({"label": canon, "headline": items[members[0]][2].get("headline", ""),
                        "source": RUN_KEY, "first_seen": today, "channels": sorted(by_ch)})
            known.add(canon)
    for ch in channels:
        json.dump(stories[ch], open(WORK / ch / "stories.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    REGISTRY.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
    return res.get("events", []), applied, skipped


if __name__ == "__main__":
    evs, applied, skipped = unify()
    print(f"跨台事件 {len(evs)} 組，改名 {applied} 則，規則不過略過 {skipped} 組")
    for e in evs:
        print(" ", e["label"], e["members"])
