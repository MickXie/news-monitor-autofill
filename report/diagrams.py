"""報告用的四張圖（inline SVG），配色照學生提案範本：黑線、白底、淺藍 #D9E8F7 強調。

flow_asis()   1.1 現行流程圖（負責人、工具、工時、痛點、瓶頸）
fishbone()    1.2 魚骨圖
architecture() 3.3 系統架構圖
roadmap()     5.1 前 90 天路線圖
"""
from __future__ import annotations

from html import escape as E

BLUE = "#D9E8F7"
GRAY = "#F3F3F3"
FONT = "Arial, 'PingFang TC', 'Heiti TC', sans-serif"


def svg(w, h, body):
    return (f"<svg viewBox='0 0 {w} {h}' xmlns='http://www.w3.org/2000/svg' "
            f"style='width:100%;height:auto;display:block' font-family=\"{FONT}\">"
            "<defs><marker id='ar' viewBox='0 0 10 10' refX='9' refY='5' markerWidth='7' markerHeight='7' "
            "orient='auto-start-reverse'><path d='M0,0 L10,5 L0,10 z' fill='#000'/></marker></defs>"
            f"{body}</svg>")


def box(x, y, w, h, fill="#fff", sw=1.2, dash=None, rx=0):
    d = f" stroke-dasharray='{dash}'" if dash else ""
    return f"<rect x='{x}' y='{y}' width='{w}' height='{h}' rx='{rx}' fill='{fill}' stroke='#000' stroke-width='{sw}'{d}/>"


def text(x, y, lines, size=14, anchor="start", bold_first=False, lh=None, fill="#000"):
    lh = lh or size * 1.35
    out = []
    for i, ln in enumerate(lines):
        w = " font-weight='bold'" if bold_first and i == 0 else ""
        out.append(f"<text x='{x}' y='{y + i * lh}' font-size='{size}' text-anchor='{anchor}' fill='{fill}'{w}>{E(ln)}</text>")
    return "".join(out)


def arrow(x1, y1, x2, y2, sw=1.3, dash=None):
    d = f" stroke-dasharray='{dash}'" if dash else ""
    return f"<line x1='{x1}' y1='{y1}' x2='{x2}' y2='{y2}' stroke='#000' stroke-width='{sw}' marker-end='url(#ar)'{d}/>"


def line(x1, y1, x2, y2, sw=1.2, dash=None):
    d = f" stroke-dasharray='{dash}'" if dash else ""
    return f"<line x1='{x1}' y1='{y1}' x2='{x2}' y2='{y2}' stroke='#000' stroke-width='{sw}'{d}/>"


# ---------------- 1.1 現行流程圖 ----------------
def flow_asis():
    steps = [
        ("1. 監看四台", "工讀生", "電視牆", "全時段持續", ["一人看四台，", "只能輪流注意"], False),
        ("2. 判斷換題", "工讀生", "人眼判讀", "隨監看進行", ["標題、字幕、跑馬", "與包框混在一起"], True),
        ("3. 寫五字標", "工讀生", "人工撰寫", "每則約 20–30 秒", ["寫法因人而異，", "換人就換風格"], False),
        ("4. 對時填表", "工讀生", "手錶、Excel", "每則約 10–20 秒", ["多台同時換題，", "分鐘容易對錯"], True),
        ("5. 隔日分析", "行政", "Excel", "隔日", ["錯誤到此才發現，", "且無法追溯"], False),
    ]
    W, bw, gap, top = 1000, 176, 25, 34
    b = [text(500, 18, ["午間新聞 12:00–13:00 的監看作業（工時為估計值）"], 15, "middle")]
    for i, (name, who, tool, t, pain, neck) in enumerate(steps):
        x = 8 + i * (bw + gap)
        b.append(box(x, top, bw, 34, BLUE))
        b.append(text(x + bw / 2, top + 23, [name], 16, "middle", True))
        b.append(box(x, top + 34, bw, 150, "#fff", 2.6 if neck else 1.2))
        b.append(text(x + 10, top + 60, [f"負責人：{who}", f"工具：{tool}", f"工時：{t}", "痛點："] + pain, 14, lh=20))
        if neck:
            b.append(box(x + bw - 62, top + 41, 54, 22, "#000"))
            b.append(text(x + bw - 35, top + 57, ["瓶頸"], 13, "middle", fill="#fff"))
        if i < len(steps) - 1:
            b.append(arrow(x + bw + 2, top + 100, x + bw + gap - 2, top + 100))
    b.append(text(8, 246, ["粗框為關鍵瓶頸：步驟 2 決定「是不是新的一則」，步驟 4 決定「記在哪一分鐘」，兩者出錯都會讓台別、時間、事件對不起來。"], 13))
    return svg(W, 256, "".join(b))


# ---------------- 1.2 魚骨圖 ----------------
def fishbone():
    W, H, sy = 1000, 396, 180
    b = [line(30, sy, 770, sy, 2.4)]
    b.append(box(772, sy - 62, 218, 124, BLUE, 1.6))
    b.append(text(881, sy - 30, ["問題結果", "台別、時間、事件", "對不起來；", "廣告破口紀錄失準"], 15, "middle", True, 23))
    bones = [  # (起點 x, 上/下, 類別, 真因代號, 原因)
        (230, -1, "畫面", "A", ["標題與受訪字幕同位置同色", "包框時 bar 輪播舊標題", "預告卡有標題卻無時鐘"]),
        (560, -1, "方法", "A", ["稿頭、SOT、Live 切換畫面全變", "同一則換 2–3 種標題寫法", "跑馬、推播與標題並存"]),
        (230, 1, "時間", "B", ["時鐘只顯示「時:分」", "民視時鐘與日期輪流出現", "檔名時間與播出差 10–22 秒"]),
        (560, 1, "人力", "C", ["一人同時看四台", "判斷標準只在個人經驗", "填錯無法事後查證"]),
    ]
    for x0, d, cat, code, causes in bones:
        y0 = sy + d * 140
        b.append(line(x0, y0, x0 + 140, sy, 1.8))
        lab_y = y0 - 12 if d < 0 else y0 + 26
        b.append(box(x0 - 52, lab_y - 19, 104, 26, "#fff"))
        b.append(text(x0, lab_y, [f"{cat}（真因 {code}）"], 14, "middle", True))
        for k, c in enumerate(causes):
            t = 0.25 + k * 0.27
            px, py = x0 + 140 * t, y0 + (sy - y0) * t
            b.append(line(px - 18, py, px, py, 1))
            b.append(text(px - 22, py + 5, [c], 13.5, "end"))
    b.append(text(30, H - 4, ["真因 A：畫面上的文字不等於正在播的新聞　真因 B：沒有可靠的時間基準　真因 C：判斷無法規模化與追溯"], 13.5))
    return svg(W, H, "".join(b))


# ---------------- 3.3 系統架構圖 ----------------
def architecture():
    W, H = 1100, 500
    dy = 92                                   # 本機區塊整體下移，上方留給雲端 LLM
    b = []
    b.append(box(150, 26 + dy, 940, 236, "none", 1.2, "6 4"))
    b.append(text(160, 44 + dy, ["本機（Mac）處理：影片與截圖不離開本機"], 13.5))
    b.append(box(6, 70 + dy, 128, 120, BLUE))
    b.append(text(70, 94 + dy, ["輸入", "四台側錄 mp4", "範本 xlsx", "10/26 範例"], 14, "middle", True, 23))
    b.append(arrow(134, 115 + dy, 166, 115 + dy))
    mods = [
        ("① 抽取畫面", ["ffmpeg", "每秒 1 張"]),
        ("② 讀字", ["Apple Vision", "只讀固定區域"]),
        ("③ 規則判斷", ["時鐘推算時間", "廣告判定、分段"]),
        ("④ 語意判斷", ["LLM 判斷同一則", "撰寫五字標"]),
        ("⑤ 檢查與統一", ["規則檢查重寫", "跨台統一命名"]),
        ("⑥ 寫入輸出", ["openpyxl 寫四欄", "產生驗證頁"]),
    ]
    bw, gap, x0, y = 136, 17, 168, 70 + dy
    centers = []
    for i, (t, sub) in enumerate(mods):
        x = x0 + i * (bw + gap)
        centers.append(x + bw / 2)
        b.append(box(x, y, bw, 32, BLUE if i == 3 else GRAY))
        b.append(text(x + bw / 2, y + 22, [t], 14.5, "middle", True))
        b.append(box(x, y + 32, bw, 56))
        b.append(text(x + bw / 2, y + 54, sub, 13.5, "middle", lh=21))
        if i < len(mods) - 1:
            b.append(arrow(x + bw + 1, y + 60, x + bw + gap - 1, y + 60))
    stores = [(1, "frames.jsonl", "每秒辨識紀錄"), (2, "analysis.json", "時間、廣告、文字段"),
              (3, "stories.json", "每則新聞＋理由"), (4, "event_registry", "事件命名表")]
    cy = 192 + dy
    for i, name, desc in stores:
        cx = centers[i]
        b.append(line(cx, y + 88, cx, cy - 6, 1, "3 3"))
        b.append(f"<ellipse cx='{cx}' cy='{cy}' rx='62' ry='7' fill='#fff' stroke='#000'/>")
        b.append(f"<path d='M{cx - 62},{cy} v42 a62,7 0 0 0 124,0 v-42' fill='#fff' stroke='#000'/>")
        b.append(text(cx, cy + 22, [name, desc], 12.5, "middle", lh=17))
    c4 = centers[3]
    b.append(box(c4 - 130, 8, 260, 60, "#fff", 1.4, rx=8))
    b.append(text(c4, 32, ["LLM 服務（雲端）", "Claude 示範／DeepSeek 正式"], 14, "middle", True, 22))
    b.append(arrow(c4 - 22, y - 2, c4 - 22, 70))
    b.append(arrow(c4 + 22, 70, c4 + 22, y - 2))
    b.append(text(c4 + 140, 30, ["只送標題文字（不送影片）；", "結果快取，同一輸入不重問"], 12.5, lh=18))
    c6 = centers[5]
    oy = 300 + dy
    b.append(arrow(c6, y + 88, c6, oy - 2))
    b.append(box(c6 - 72, oy, 144, 50, BLUE))
    b.append(text(c6, oy + 20, ["輸出", "Excel、驗證頁"], 14, "middle", True, 21))
    py = 410 + dy
    b.append(box(c6 - 160, py - 18, 240, 50))
    b.append(text(c6 - 40, py + 2, ["抽查員（原工讀生）", "看驗證頁低信心格、回報錯誤"], 13, "middle", True, 20))
    b.append(arrow(c6, oy + 50, c6 - 40, py - 20))
    c3 = centers[2]
    b.append(box(c3 - 150, py - 18, 300, 50))
    b.append(text(c3, py + 2, ["監看組長（AI 績效負責人）", "維護畫面區域設定 config.py、修訂規則"], 13, "middle", True, 20))
    b.append(f"<line x1='{c3}' y1='{py - 20}' x2='{c3}' y2='{cy + 52}' stroke='#000' stroke-width='1.2' stroke-dasharray='4 3' marker-end='url(#ar)'/>")
    b.append(f"<line x1='{c6 - 160}' y1='{py + 7}' x2='{c3 + 152}' y2='{py + 7}' stroke='#000' stroke-width='1.2' stroke-dasharray='4 3' marker-end='url(#ar)'/>")
    b.append(text((c6 - 160 + c3 + 152) / 2, py - 2, ["錯誤類型回報"], 12, "middle"))
    return svg(W, H + 40, "".join(b))


# ---------------- 5.1 90 天路線圖 ----------------
def roadmap():
    W, H = 1000, 332
    xs = [40, 345, 650, 955]
    b = [arrow(30, 40, 975, 40, 2)]
    for x, lab in zip(xs, ["第 0 天", "第 30 天", "第 60 天", "第 90 天"]):
        b.append(line(x, 32, x, 48, 2))
        b.append(text(x, 22, [lab], 14, "middle", True))
    for x in xs[1:3]:
        b.append(f"<polygon points='{x},52 {x + 11},64 {x},76 {x - 11},64' fill='#000'/>")
    phases = [
        ("並行試行", "午間一小時每天自動跑", ["人工對照組（同小時人工另填）", "改用 DeepSeek、固定參數"],
         ["分鐘對齊 ≥ 95%", "廣告破口 100%", "五字標 ≥ 90%（連續 2 週）"]),
        ("擴大時段", "擴到晚間與全天新聞", ["各節目版面設定", "工讀生轉抽查員、抽查制度"],
         ["抽查 ≤ 10 分鐘／小時", "告警誤報 ≤ 1 次／週"]),
        ("正式上線", "串流即時處理", ["排程與告警", "收視、破口分析直接使用"],
         ["連續 30 天零人工補填", "行政使用不需修改"]),
    ]
    for i, (name, goal, deliv, kpi) in enumerate(phases):
        x = xs[i] + 6
        w = xs[i + 1] - xs[i] - 12
        b.append(box(x, 84, w, 30, BLUE))
        b.append(text(x + w / 2, 105, [f"{name}（{['0–30', '31–60', '61–90'][i]} 天）"], 15, "middle", True))
        b.append(box(x, 114, w, 172))
        b.append(text(x + 10, 136, [f"目標：{goal}", "交付物："] + [f"・{d}" for d in deliv] + ["驗收 KPI："], 13.5, lh=19))
        b.append(text(x + 10, 136 + 19 * 5, [f"・{k}" for k in kpi], 13.5, lh=19))
    b.append(text(40, 312, ["◆ Go / No-go 判斷點：第 30 天達標才擴大時段；第 60 天抽查時間與告警達標才轉串流上線。"], 13.5))
    b.append(text(40, 332, ["未達標時暫停擴大，只保留已證實穩定的時間與廣告自動化，五字標改由人工依系統提供的完整標題撰寫後再評估。"], 13.5))
    return svg(W, H + 8, "".join(b))
