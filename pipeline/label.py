"""第 3 步：交給 LLM 判斷「哪些文字段屬於同一則新聞」並寫五字標。

規則先做完的事（時間、廣告、過濾跑馬燈/署名）不交給 LLM；
LLM 只負責語意判斷：區分標題與受訪字幕、合併同一事件、命名。

每 20 分鐘切一段獨立送出（前面多給 2 分鐘、後面多給 1 分鐘當上下文），
只保留「開始時間落在本段內」的新聞，所以各段可以平行處理。
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor

import openpyxl

from config import CHANNELS, JOB, SAMPLE, START_MIN, WORK
from llm import as_float, as_int, ask_json

# 每批送給 AI 的分鐘數：雲端大模型一次看 20 分鐘沒問題；本機小模型看太多會把不同新聞合併，預設改 10 分鐘
import os as _os
CHUNK_SEC = int(_os.environ.get("LLM_CHUNK_MIN") or (10 if _os.environ.get("LLM_BACKEND") == "local" else 20)) * 60
CTX_BEFORE = 120
CTX_AFTER = 60
MAX_WORKERS = 6
RETRIES = 3
WARNINGS: list[str] = []      # 給網頁顯示的警告（例如 LLM 失敗改用備案）

if JOB:
    _h = START_MIN // 60
    SLOT_LABEL = JOB["date"].replace("-", "/") + " " + ("午間新聞" if _h == 12 else f"{_h} 點新聞")
else:
    SLOT_LABEL = "2026/11/06 午間新聞"   # 與開發時的快取一致


def sample_labels():
    """參考寫法：有人工填寫範例時取範例裡的五字標；沒有時用命題文件的示例。"""
    if not SAMPLE.exists():
        return ["土城翁輾亡", "俊傑偷渡中", "高金遭起訴"]
    ws = openpyxl.load_workbook(SAMPLE).worksheets[0]
    out = []
    for col in "FJNR":
        for r in range(5, 65):
            v = ws[f"{col}{r}"].value
            if v and v not in ("廣告", "氣象"):
                out.extend(str(v).split("/"))
    return sorted(set(out))


SYSTEM = """你是電視新聞監看員，要把一個頻道午間新聞的畫面文字，整理成「每則新聞的開始時間與五字標」。

輸入是依時間排列的「文字段」，每段是主標題 bar 區域在一段時間內顯示的文字（已用 OCR 讀出，可能有錯字）：
  id | 開始時間 | 秒數 | 地點標 | 左上短標 | 提示 | 文字
提示 quote? 表示上方有小字名條，多半是受訪者說話字幕。
另有 [廣告] 列標出廣告時段（已由畫面規則判定，請直接採用，不要把廣告當新聞）。

你的工作：
1. 分辨每段是「新聞標題」還是「受訪者/記者/主播說話字幕」或其他雜訊。字幕通常短、口語、幾秒就換；標題像新聞標題、停留較久。
2. 把屬於同一則新聞的段落合成一則。同一則新聞會跨主播稿頭、SOT、Live、說新聞等形式，標題 bar 也可能換寫法，
   畫面或寫法換了不代表換題；只有「事件」改變才算新的一則。同一事件的不同面向（例如同案的不同報導）若主播已轉到下一則稿子、標題明顯換焦點，可以分成兩則。
   廣告結束後即使回到同一則，也要另起一則。
3. 每則給五字標：
   - 目的是讓看表的人認出是哪則新聞，不是把標題硬切成五個字。原則上 5 個中文字，必要時 4–6 字。
   - 社會事件（車禍、火災、犯罪、意外）一定要有地點，地點只能用畫面上出現的（地點標或標題文字），不能編造地點或行為。
     標題裡有更具體的地名（例如「汐止」「土城」「大園」）時優先用它，不要用較籠統或可能錯的縣市地點標。
   - 五字標要對準「這一則」的焦點：同一案件的不同進展（例如「求刑」與「共犯被押」）要用各自標題的焦點命名。
   - 其他新聞可選不同切入角度，但不能把未確認的事寫成定論。涉及指控（涉諜、涉案、貪污、詐騙等），
     標題只說「風波、疑雲、遭控、被指」時，五字標要用中性詞（例如「黃仁勳風波」），不可寫成「某某涉諜」；
     只有標題明確寫出起訴、求刑、判決、落網等司法結果，才能寫成事實。
   - 五字標不可出現「廣告」二字（避免和廣告破口混淆），例如藝人拍廣告的新聞要改寫成「蘇志燮爆紅」之類。
   - 只有「天氣預報/氣象報告」本身（降溫、降雨、颱風、東北季風等預報）五字標才寫「氣象」；
     只是提到天氣的生活或消費新聞（例如天冷帶動保暖商機）要寫它的內容，不可寫「氣象」。
   - OCR 亂碼、無法辨識內容的段落不可單獨成一則，併入前後最可能的新聞。
   - 參考過去人工寫過的五字標風格：{examples}
4. 無法確定時，仍要給出最可能的判斷，把 confidence 調低並在 note 說明原因。

輸出 JSON（字串內不要用半形雙引號 "，需要引號請用「」）：
{{"stories": [{{"first_id": 起始段id, "last_id": 結束段id, "label": "五字標", "headline": "最能代表這則的完整標題",
  "place": "地點或空字串", "kind": "社會|政治|財經|國際|生活|娛樂|體育|氣象|其他", "confidence": 0到1, "note": "判斷理由或疑點"}}]}}
stories 依時間排序、彼此不重疊，涵蓋所有輸入的新聞內容；純字幕或雜訊段併入所屬新聞，不要單獨成一則。"""


def clean(s):
    return s.replace('"', "＂").replace("\\", "")


def fmt_rows(runs, ads, t_lo, t_hi):
    items = [("run", r["t0"], r) for r in runs if t_lo <= r["t0"] < t_hi]
    items += [("ad", a["t0"], a) for a in ads if a["t1"] >= t_lo and a["t0"] < t_hi]
    rows = []
    for kind, _, x in sorted(items, key=lambda i: i[1]):
        if kind == "ad":
            rows.append(f"[廣告] {x['start']}–{x['end']}（{x['dur']} 秒，{x['type']}）")
        else:
            hint = ",".join(k for k in x["kinds"] if k != "text") or "-"
            rows.append(f"{x['id']} | {x['start']} | {x['dur']} | {clean(x.get('loc') or '-')} | "
                        f"{clean(x.get('tag') or '-')} | {hint} | {clean(x['text'])}")
    return "\n".join(rows)


def run_chunk(ch, an, lo, hi, system):
    runs, ads = an["runs"], an["ads"]
    body = fmt_rows(runs, ads, lo - CTX_BEFORE, hi + CTX_AFTER)
    lo_s = [r["start"] for r in runs if r["t0"] >= lo]
    user = (f"頻道：{CHANNELS[ch]['name']}，{SLOT_LABEL}。"
            f"請涵蓋全部輸入內容；系統只會採用開始時間在 {lo_s[0] if lo_s else '-'} 之後的新聞。\n\n{body}")
    last_err = None
    for attempt in range(RETRIES):
        try:
            res = ask_json(system, user)
            keep = [s for s in clean_stories(res.get("stories", []), len(runs))
                    if 0 <= s["first_id"] < len(runs) and lo <= runs[s["first_id"]]["t0"] < hi]
            print(f"[{ch}] {lo_s[0] if lo_s else '-'} 起 {CHUNK_SEC // 60} 分鐘：{len(keep)} 則", flush=True)
            return keep
        except Exception as e:  # noqa: BLE001  JSON 壞掉或 CLI 失敗就重試
            last_err = e
            print(f"[{ch}] 第 {attempt + 1} 次失敗，重試：{str(e)[:120]}", flush=True)
    # 備案：LLM 連續失敗時不中斷流程，改用「標題前段」暫代五字標並標低信心，列入抽查
    WARNINGS.append(f"{CHANNELS[ch]['name']} {lo_s[0] if lo_s else ''} 起 {CHUNK_SEC // 60} 分鐘：LLM 無法使用（{str(last_err)[:60]}），"
                    "已暫以標題前段代替五字標，這段請在驗證頁抽查。")
    return fallback_stories(runs, ads, lo, hi)


def clean_stories(raw, n_runs):
    """把 AI 回傳的每一則整理成固定格式；缺欄位或編號不合理的直接丟掉，不讓流程當掉。"""
    out = []
    for s in raw if isinstance(raw, list) else []:
        if not isinstance(s, dict):
            continue
        a, b = as_int(s.get("first_id")), as_int(s.get("last_id"))
        label = str(s.get("label") or "").strip()
        if a is None or not label or not (0 <= a < n_runs):
            continue
        out.append({**s, "first_id": a, "last_id": b if b is not None and b >= a else a,
                    "label": label, "headline": str(s.get("headline") or ""), "place": str(s.get("place") or ""),
                    "kind": str(s.get("kind") or "其他"), "confidence": as_float(s.get("confidence")),
                    "note": str(s.get("note") or "")})
    return out


def fallback_stories(runs, ads, lo, hi):
    """不靠 LLM 的保底分則：停留 ≥ 20 秒的文字段各算一則，相似標題併入前一則。"""
    from difflib import SequenceMatcher
    out = []
    for r in runs:
        # 受訪字幕每 2–4 秒就換一句；同一段文字停留 20 秒以上，幾乎都是標題
        if not (lo <= r["t0"] < hi) or r["dur"] < 20:
            continue
        head = r["text"].replace(" ", "")
        if out and SequenceMatcher(None, out[-1]["headline"], head).ratio() > 0.5:
            out[-1]["last_id"] = r["id"]
            continue
        out.append({"first_id": r["id"], "last_id": r["id"], "label": head[:5], "headline": head,
                    "place": r.get("loc", ""), "kind": "其他", "confidence": 0.4,   # 高於雜訊門檻、低於抽查門檻
                    "note": "LLM 無法使用，暫以標題前段代替"})
    return out


REPAIR_SYSTEM = """你是新聞監看表的五字標審稿員。以下五字標被規則檢查標出問題，請逐一處理。
規則：原則上 5 個中文字（必要時 4–6 字）；不可出現「廣告」；
五字標必須描述「畫面文字」所顯示的這則新聞，若問題是「對不上」，請只根據畫面文字重寫，不要沿用其他新聞的內容；
指控類新聞若 headline 沒有起訴、求刑、判決、落網等確定字眼，要用中性詞（風波、疑雲），不可寫成定論。
社會事件（車禍、火災、犯罪、意外）要有地點，只能用 place 欄提供的地點，並保留讓人認得出事件的關鍵詞。
例外：若事件本身是以知名人物或案件辨識（例如命題文件示例：張俊傑、高金素梅共諜案寫成「俊傑偷渡中」「高金遭起訴」，不需地點），
加地點反而會擠掉人名、讓人認不出時，請保留原名，設 keep 為 true 並說明理由。
輸出 JSON：{"fixes": [{"i": 編號, "label": "新五字標", "keep": false, "reason": "理由"}]}（字串內不要用半形雙引號）"""

ACCUSE = ("涉諜", "涉案", "涉貪", "貪污", "詐騙犯", "共諜")
CONFIRM = ("起訴", "求刑", "判", "落網", "收押", "聲押", "羈押", "逮", "遭押", "定讞")
# 標題有保留字眼（疑、爭議…），五字標卻用了定論式的評價詞 → 把未確認的事寫成定論
HEDGE = ("疑", "爭議", "風波", "質疑", "傳出", "被指", "遭控")
JUDGE = ("涉", "黑幫", "傲慢", "說謊", "貪", "詐欺", "失職")


NOT_PLACE = ("住宅區", "市區", "現場", "國外", "海外")


def place_tokens(place):
    """把 place 欄（例如「高雄前鎮漁港」「台北-香港」）拆成可比對的地名片段。"""
    out = set()
    for tok in place.replace("-", " ").replace("/", " ").replace("、", " ").split():
        if tok in NOT_PLACE or len(tok) < 2:
            continue
        out.add(tok)
        out.update(tok[i:i + 2] for i in range(len(tok) - 1))
    return out


GENERIC = set("的了在與和是被遭將及不也又再更最大小新中上下前後年月日人們要會有沒為")


def grounding(s):
    """五字標裡的字，有多少比例出現在這則新聞的畫面文字裡（標題、地點標）。用來抓張冠李戴。"""
    lab = [c for c in s.get("label", "") if "\u4e00" <= c <= "\u9fff" and c not in GENERIC]
    src = s.get("_screen", "")
    if not lab or not src:
        return 1.0
    return sum(c in src for c in lab) / len(lab)


def problems(s):
    lab, head = s.get("label", ""), s.get("headline", "")
    out = []
    toks = place_tokens(s.get("place", ""))
    if (s.get("kind") == "社會" and toks and not any(t in lab for t in toks)
            and not s.get("place_exempt")):
        out.append(f"社會新聞缺地點（畫面地點：{s.get('place')}）")
    if "廣告" in lab:
        out.append("含「廣告」")
    n = len(lab.replace("/", ""))
    if lab != "氣象" and not 3 <= n <= 7:
        out.append(f"長度 {n}")
    if any(a in lab for a in ACCUSE) and not any(c in head for c in CONFIRM):
        out.append("指控未確認卻寫成定論")
    elif (any(h in head for h in HEDGE) and any(j in lab for j in JUDGE)
          and not any(h in lab for h in ("疑", "爭議", "風波"))):
        out.append("標題有保留字眼（疑、爭議…）卻寫成定論")
    return out


def repair(stories):
    """規則檢查不過的五字標，再請 LLM 改一次；改完仍不過就保留並記在 note。"""
    bad = [(i, s, problems(s)) for i, s in enumerate(stories) if problems(s)]
    if not bad:
        return
    user = "\n".join(f"{i}. 五字標：{s['label']}｜headline：{clean(s.get('headline', ''))}｜"
                     f"place：{s.get('place', '')}｜畫面文字：{clean(s.get('_screen', '')[:300])}｜問題：{'、'.join(p)}"
                     for i, s, p in bad)
    try:
        fixes = ask_json(REPAIR_SYSTEM, user).get("fixes", [])
    except Exception as e:  # noqa: BLE001
        print("修正失敗：", e)
        fixes = []
    for f in fixes:
        i = as_int(f.get("i"), -1) if isinstance(f, dict) else -1
        if not (0 <= i < len(stories)) or not str(f.get("label") or "").strip() and not f.get("keep"):
            continue
        f["label"] = str(f.get("label") or "").strip()
        s = stories[i]
        old = s["label"]
        if f.get("keep"):
            # 以人名/案名辨識的新聞，審稿判定不加地點（命題示例「俊傑偷渡中」即無地點）
            s["place_exempt"] = True
            s["note"] = (s.get("note", "") + f"｜審稿保留原名：{f.get('reason', '')}").strip("｜")
            continue
        s["label"] = f["label"]
        s["note"] = (s.get("note", "") + f"｜規則修正：{old}→{f['label']}").strip("｜")
    for i, s, p in bad:
        if problems(s):
            s["note"] = (s.get("note", "") + "｜仍未通過檢查：" + "、".join(problems(s))).strip("｜")
            s["confidence"] = min(s.get("confidence", 1), 0.5)


def label_all(channels):
    system = SYSTEM.format(examples="、".join(sample_labels()[:60]))
    jobs = []
    analyses = {}
    for ch in channels:
        an = json.load(open(WORK / ch / "analysis.json", encoding="utf-8"))
        analyses[ch] = an
        t_first = min(r["t0"] for r in an["runs"])
        t_last = max(r["t1"] for r in an["runs"])
        t = t_first
        while t <= t_last:
            jobs.append((ch, t, t + CHUNK_SEC))
            t += CHUNK_SEC
    with ThreadPoolExecutor(MAX_WORKERS) as ex:
        futs = {ex.submit(run_chunk, ch, analyses[ch], lo, hi, system): (ch, lo) for ch, lo, hi in jobs}
        results = {k: f.result() for f, k in futs.items()}
    out = {}
    for ch in channels:
        runs = analyses[ch]["runs"]
        stories = [s for (c, lo) in sorted(k for k in results if k[0] == ch) for s in results[(c, lo)]]
        stories.sort(key=lambda s: runs[s["first_id"]]["t0"])
        for s in stories:
            s["start"] = runs[s["first_id"]]["start"]
            s["t0"] = runs[s["first_id"]]["t0"]
            s["t1"] = runs[min(s["last_id"], len(runs) - 1)]["t1"]
            # 這則新聞範圍內畫面出現過的所有文字（給「對照畫面文字」檢查用，存檔前移除）
            seg = runs[s["first_id"]:min(s["last_id"], len(runs) - 1) + 1]
            s["_screen"] = " ".join(r["text"] + " " + (r.get("loc") or "") + " " + (r.get("tag") or "") for r in seg)
        repair(stories)
        for s in stories:
            # 對照畫面文字：對不上只降為「建議抽查」，不自動改寫（自動改寫實測可能越改越糟）
            if s["label"] != "氣象" and grounding(s) < 0.5:
                s["confidence"] = min(s.get("confidence", 1), 0.5)
                s["note"] = (s.get("note", "") + "｜五字標和畫面文字對不上，請確認是否寫到別則新聞").strip("｜")
            s.pop("_screen", None)
        json.dump({"channel": ch, "stories": stories},
                  open(WORK / ch / "stories.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        out[ch] = stories
    return out


if __name__ == "__main__":
    chs = sys.argv[1:] or list(CHANNELS)
    for ch, stories in label_all(chs).items():
        print(f"== {ch}：{len(stories)} 則")
        for s in stories:
            print(f"  {s['start']} {s['label']}  ({s.get('confidence')}) {s.get('headline', '')[:32]}")
