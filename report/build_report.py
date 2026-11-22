"""產生提案報告：report/提案報告.html → report/提案報告.pdf

版面照「學生提案範本」：Arial／黑字、1pt 黑框表格、表頭淺藍 #D9E8F7、章節 1.1–5.3。
Excel 摘錄、各台統計、驗證頁範例都直接讀實際輸出，不手抄。
用法：.venv/bin/python report/build_report.py
"""
from __future__ import annotations

import html
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

import openpyxl  # noqa: E402

from config import CHANNELS, OUTPUT  # noqa: E402
from review import build as review_build  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import diagrams  # noqa: E402

REPORT = ROOT / "report"
CHROME = Path.home() / "Library/Caches/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-mac-arm64/chrome-headless-shell"
XLSX = OUTPUT / "12監看_自動填表_20261106.xlsx"
E = html.escape
# 提案者姓名放在不上傳 GitHub 的 data/proposer.txt
PROPOSER = (ROOT / "data" / "proposer.txt").read_text(encoding="utf-8").strip() if (ROOT / "data" / "proposer.txt").exists() else "（請填寫）"


# ---------- 從實際輸出取資料 ----------
def excel_excerpt(r0, r1):
    ws = openpyxl.load_workbook(XLSX)["12監看"]
    rows = ["<table class='xl'><tr><th>時間</th><th>TVBS-N（F）</th><th>東森（J）</th><th>民視（N）</th><th>華視（R）</th></tr>"]
    for r in range(5, 65):
        t = ws[f"A{r}"].value
        if r0 <= t <= r1:
            cells = "".join(f"<td>{E(ws[f'{c}{r}'].value or '')}</td>" for c in "FJNR")
            rows.append(f"<tr><td>{t}</td>{cells}</tr>")
    rows.append("</table>")
    return "".join(rows)


def excel_facts():
    ws = openpyxl.load_workbook(XLSX)["12監看"]
    counts = [sum(1 for r in range(5, 65) if ws[f"{c}{r}"].value) for c in "FJNR"]
    return min(counts), max(counts)


def stats_rows():
    chans, data, stats = review_build()
    rows = []
    for ch in chans:
        s = stats[ch]
        rows.append(f"<tr><td>{CHANNELS[ch]['name']}</td><td>{s['offset']}</td><td>{s['clock']}</td>"
                    f"<td>{s['ads']} 段</td><td>{s['cells']} 格</td></tr>")
    return "".join(rows), data


def review_rows(data, picks):
    """驗證頁範例，改用一般表格呈現。"""
    img_dir = REPORT / "img"
    out = []
    for ch, m, why, *want in picks:
        d = data[ch][m]
        ev = next((e for e in d["events"] if e["used"] and (not want or want[0] in e["label"])), d["events"][0])
        name = f"rv_{ch}_{m}.jpg"
        if ev["kind"] == "ad" and ch == "ftv" and (img_dir / "wrap_ftv.jpg").exists():
            name = "wrap_ftv.jpg"
        elif (OUTPUT / ev["img"]).exists():
            shutil.copy(OUTPUT / ev["img"], img_dir / name)
        info = f"{ev['time']}，{ev['dur']} 秒" + (f"，信心 {ev['conf']:.2f}" if ev["kind"] == "news" else "")
        head = f"<br>標題：{E(ev['headline'])}" if ev["headline"] else ""
        out.append(f"<tr><td class='img'><img src='img/{name}'></td>"
                   f"<td>{CHANNELS[ch]['name']} {m // 60}{m % 60:02d}：{E(d['cell'] or '')}<br>{info}{head}"
                   f"<br>說明：{E(why)}</td></tr>")
    return "".join(out)


CSS = """
@page { size: A4; margin: 15mm 17mm 14mm 17mm; }
body { font-family: Arial, "PingFang TC", "Heiti TC", sans-serif; font-size: 10pt; line-height: 1.45; color: #000; margin: 0; }
h1 { font-size: 21pt; font-weight: normal; margin: 0 0 3mm; }
h2 { font-size: 15pt; font-weight: normal; margin: 5mm 0 2mm; break-after: avoid; }
h3 { font-size: 11.5pt; font-weight: bold; margin: 4mm 0 1.5mm; break-after: avoid; }
p { margin: 1mm 0 2mm; }
ul, ol { margin: 1mm 0 2mm; padding-left: 6mm; } li { margin: .5mm 0; }
table { border-collapse: collapse; width: 100%; margin: 1.5mm 0 3mm; break-inside: auto; }
tr { break-inside: avoid; }
th, td { border: 1px solid #000; padding: 1.1mm 1.8mm; vertical-align: top; text-align: left; }
th { background: #D9E8F7; font-weight: normal; }
table.info th { background: #F3F3F3; }
table.xl td, table.xl th { text-align: center; padding: .9mm 1mm; }
td.img { width: 52mm; } td.img img { width: 50mm; display: block; }
.fig { break-inside: avoid; margin: 2mm 0 3mm; }
.fig img { width: 100%; display: block; border: 1px solid #999; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 4mm; }
.three { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 3mm; }
.cap { font-size: 9pt; margin-top: 1mm; }
.note { font-size: 9.3pt; }
.newpage { break-before: page; }
table.keep, table.xl { break-inside: avoid; }
"""


def build():
    stats, data = stats_rows()
    cmin, cmax = excel_facts()
    examples = review_rows(data, [
        ("ftv", 12 * 60 + 35, "民視包框，時鐘與下方標題都還在，以右上「現在最焦點」判為廣告"),
        ("ftv", 12 * 60 + 5, "地點取標題中最具體的「汐止」"),
        ("cts", 12 * 60 + 19, "標題只寫「風波」，依規則不可寫成「涉諜」", "黃仁勳"),
    ])
    body = f"""
<h1>新聞監看全自動填表</h1>
<p>UNEXT AI 企業創新實戰營　學生提案</p>
<table class="info">
<tr><th colspan="2">基本資訊</th></tr>
<tr><td style="width:35%">提案者姓名</td><td>{E(PROPOSER)}</td></tr>
<tr><td>企業名稱</td><td>三立新聞台</td></tr>
<tr><td>交付內容</td><td>1. 自動填好的 Excel：12監看_自動填表_20261106.xlsx<br>2. 驗證頁：驗證頁.html（每一格附畫面截圖、播出時間、判斷理由）<br>3. 可重跑的程式：pipeline/run.py</td></tr>
</table>

<h2>摘要 Summary</h2>
<table>
<tr><th style="width:17%">摘要項目</th><th style="width:17%">撰寫重點</th><th>內容</th></tr>
<tr><td>問題痛點與價值</td><td>What I found</td><td>核心根因是「畫面上的文字不等於正在播的新聞」，而且缺少可靠的時間基準。同一則新聞會換好幾種標題寫法，廣告包框時下方標題 bar 還在輪播舊新聞，工讀生只能靠經驗和手錶判斷。若以每日監看 18 小時、時薪 196 元估算，人工成本約 129 萬元／年（假設值），導入後每年約可節省 107 萬元工時。</td></tr>
<tr><td>核心解決方案</td><td>What I recommend</td><td>建立一套固定流程：用規則處理時間對齊與廣告判斷，只把「是不是同一則新聞、五字標怎麼寫」交給 AI，每一格都留下可查證的紀錄。由監看組主導日常運作，工讀生改為抽查。</td></tr>
<tr><td>驗證結果評估</td><td>What the evaluation showed</td><td>已用 11/06 12:00–13:00 四台影片實際跑完，人工補填 0 格。新聞開始分鐘逐格核對 112 格，正確 109 格（97.3%，目標 95%）；廣告破口 13 段全部判對（目標 100%）；同一份輸入重跑兩次結果完全相同。處理 1 小時四台影片約 18 分鐘。六項指標皆已達標。</td></tr>
</table>
<p class="note">本報告依範本章節撰寫，命題的五個問題分別在：問題 1（流程與工具）3.1、3.3；問題 2（換題與五字標）3.2；問題 3（廣告包框）3.2；問題 4（Excel 與驗證）2.3、4.1；問題 5（進度、限制與擴大全天）4.2、5.1。</p>

<h2 class="newpage">1. 問題 The Problem</h2>
<h3>1.1 現況分析</h3>
<p>目前由當班工讀生一人同時看四台，主要看畫面下方的新聞標題 bar，判斷換題後整理五字標，再對照時間填進 Excel。隔天由行政補上收視率，供收視與廣告破口分析使用。</p>
<div class="fig">{diagrams.flow_asis()}<div class="cap">圖 1　現行監看流程（負責人、工具、工時、痛點與瓶頸）</div></div>

<h3>1.2 真因分析</h3>
<p>資料來源為命題文件、說明會簡報，以及 11/06 四台側錄逐分鐘抽圖的觀察。先列出所有觀察到的現象，再依「畫面、方法、時間、人力」四個面向歸類（圖 2）。</p>
<div class="fig">{diagrams.fishbone()}<div class="cap">圖 2　魚骨圖：四個面向的原因收斂為三項真因</div></div>
<p>收斂邏輯：「畫面」與「方法」兩類現象的共同點，是畫面上出現的文字和實際正在播的新聞不一致，歸為真因 A；「時間」類現象都指向沒有可用的時間基準，歸為真因 B；「人力」類則是判斷只存在個人經驗、無法交接與查證，歸為真因 C。實證：四台時鐘只到分鐘、檔名與播出差 10–22 秒（B）；民視 12:36–12:40 包框時下方 bar 顯示的是 12:12 已播過的標題（A）。</p>
<p>表面現象為「工讀生要一直看、一直打字」，實際根因實為「畫面文字不等於正在播的新聞，且沒有可靠的時間基準」。因此單純把 OCR 讀到的字抄進 Excel 並不可行，會把包框殘留的標題當成新聞。</p>

<h3>1.3 路由判斷 Routing</h3>
<table>
<tr><th style="width:24%">真因</th><th style="width:24%">解法</th><th>理由</th></tr>
<tr><td>B. 時間基準</td><td>非 AI：規則</td><td>時鐘位置固定，用規則推算即可達到 100% 一致，不需要模型</td></tr>
<tr><td>A. 廣告與包框</td><td>非 AI：畫面特徵規則</td><td>各台廣告版面固定（時鐘消失、出現「現在最焦點」），規則比模型穩定且容易解釋</td></tr>
<tr><td>A. 標題與字幕、是否同一則</td><td>AI：文字辨識＋LLM</td><td>需要理解語意，例如口語和標題的差別、不同寫法是不是同一事件，規則寫不完</td></tr>
<tr><td>C. 命名一致與追溯</td><td>AI＋管理制度</td><td>LLM 依固定規則命名並留下理由；抽查與規則修訂由監看組負責</td></tr>
</table>
<p>評估「能否先用非 AI 方案解決」後，時間與廣告兩項以規則處理。未採用自行訓練模型（只有一小時資料，且版面固定），也未採用 AI Agent（讓 AI 自行決定下一步，結果較難重現）。</p>

<h3>1.4 改善空間與商業價值</h3>
<table>
<tr><th>指標</th><th>現況 Baseline</th><th>目標 Target</th><th>落差 Gap</th></tr>
<tr><td>人工填表工時</td><td>監看時段全程 1 人</td><td>每小時抽查 10 分鐘以內</td><td>約減少 83%</td></tr>
<tr><td>台別、分鐘、事件對齊</td><td>未量測，無法追溯</td><td>95% 以上，且每格可查證</td><td>由不可驗證變為可驗證</td></tr>
<tr><td>廣告破口紀錄</td><td>依人判斷，包框容易漏判</td><td>破口開始分鐘 100% 正確</td><td>本次 13/13 已達成</td></tr>
</table>
<p>估算公式：年人工成本 ＝ 每日監看 18 小時 × 365 天 × 時薪 196 元 ≈ 128.8 萬元（未含勞健保；時數與時薪為假設，需依實際排班修正）。導入後保留每小時 10 分鐘抽查，約 21.5 萬元，每年可節省約 107 萬元。系統成本見 4.2，每日約數十元。</p>
<p>若維持現狀，未來一年的主要風險：（1）包框誤判造成廣告破口分析失準，影響排播與業務判斷，影響程度高；（2）多台同時換題時事件與時間錯位，收視率歸因錯誤，影響程度中高；（3）人員流動使五字標寫法不一致，歷史資料難以比對，影響程度中。</p>

<h2>2. 未來場景與評估方式 To-Be Scenarios &amp; Evaluation Method</h2>
<h3>2.1 未來的工作方式</h3>
<table>
<tr><th style="width:15%">角色</th><th style="width:30%">現在</th><th>導入後</th></tr>
<tr><td>系統</td><td>無</td><td>每小時自動處理四台，產出 Excel 與驗證頁；時鐘一致率低於 95% 或廣告段數異常時發出告警</td></tr>
<tr><td>工讀生</td><td>全程看四台、手動輸入</td><td>改為抽查：只看驗證頁標黃（低信心）的格子，加上每台隨機 5 格，回報錯誤類型，約 10 分鐘／小時</td></tr>
<tr><td>監看組長</td><td>排班、偶爾校對</td><td>擔任 AI 績效負責人：每週檢視抽查正確率，電視台改版時更新畫面區域設定，決定規則修訂或停用</td></tr>
<tr><td>行政</td><td>隔日填收視率</td><td>不變，直接使用自動產出的 Excel（格式與原表完全相同）</td></tr>
</table>
<p>交接方式：系統完成後通知抽查員；抽查發現錯誤時記錄類型，由組長每週決定是否修改規則（例如 4.1 的地點、氣象、雜訊等修正都屬此流程）。</p>

<h3>2.2 設定評估指標</h3>
<table>
<tr><th>指標</th><th>計算方式</th><th>目標</th><th>權重</th><th>資料來源</th></tr>
<tr><td>五字標可辨識率</td><td>抽查格中「看得出是哪則新聞且不違反規則」的比例</td><td>90% 以上</td><td>30%</td><td>驗證頁抽查</td></tr>
<tr><td>分鐘對齊率</td><td>新聞開始的分鐘判斷正確的比例</td><td>95% 以上</td><td>20%</td><td>逐格截圖核對</td></tr>
<tr><td>廣告破口正確率</td><td>破口開始分鐘正確的比例</td><td>100%</td><td>20%</td><td>影片逐分鐘對照</td></tr>
<tr><td>零人工補填</td><td>產出過程需人工補填的格數</td><td>0 格</td><td>10%</td><td>系統紀錄</td></tr>
<tr><td>格式正確</td><td>Excel 可開啟，四欄以外的儲存格差異數</td><td>0 處</td><td>10%</td><td>程式比對範本</td></tr>
<tr><td>處理速度</td><td>處理 1 小時四台影片所需時間</td><td>60 分鐘以內</td><td>10%</td><td>系統紀錄</td></tr>
</table>

<h3>2.3 驗證方式（實驗設計）</h3>
<table>
<tr><th style="width:32%">關鍵假設</th><th style="width:12%">風險</th><th>驗證方法</th></tr>
<tr><td>H1 畫面時鐘可作為時間基準</td><td>高</td><td>統計每台「讀到的時鐘」與「推算時間」的一致率</td></tr>
<tr><td>H2 廣告可由畫面版面判定</td><td>高</td><td>每分鐘抽一張畫面拼成對照圖，逐段核對廣告起訖</td></tr>
<tr><td>H3 LLM 能分辨字幕並合併同一則新聞</td><td>中</td><td>對每一格截取開始前 6 秒與後 4 秒的標題 bar，逐格判斷開始分鐘是否正確；五字標錯誤分類後修改規則再重跑比較</td></tr>
</table>
<p>測試資料為命題提供的 11/06 12:00–13:00 四台側錄。規則基準取自 10/26 人工填寫範例（每台每小時 22–27 格、同格最多 2 則、廣告單獨一格）。正式導入時建議同一小時另由人工填一份，作為對照組。</p>

<h2>3. 解法與施作 Solution &amp; Implementation</h2>
<h3>3.1 解決方案 The Solution</h3>
<p>方案名稱：新聞監看自動填表流程。核心精神：時間和廣告交給規則，語意交給 AI，每一格都留下證據。</p>
<table>
<tr><th style="width:18%">項目</th><th>內容</th></tr>
<tr><td>輸入</td><td>四台側錄 mp4（1280×720，約 60 分鐘；檔名時間不可信）、範本（乾淨版）.xlsx、10/26 填寫範例（只參考寫法）</td></tr>
<tr><td>輸出</td><td>只寫入 F、J、N、R 四欄、其他格式不變的 Excel；以及驗證頁（每格附截圖、播出時間、信心與判斷理由）</td></tr>
<tr><td>不涵蓋事項</td><td>收視率欄位、三立欄位、秒級紀錄、新增欄位，以及命題範圍以外的時段</td></tr>
</table>

<h3>3.2 解法思路 Solution logic</h3>
<p><b>（1）五字標如何對準分鐘：以時鐘推算時間</b></p>
<p>畫面時鐘只顯示「時:分」，但每一張讀到「12:09」的畫面，代表播出時間落在 12:09:00 到 12:09:59 之間，也就是「播出時間 ＝ 影片秒數 ＋ 偏移量」中的偏移量必須落在某個範圍。把數千張畫面的範圍疊在一起，取同時滿足最多畫面的偏移量，就能換算出每一張畫面的播出時間，誤差約 1 秒，連看不到時鐘的廣告畫面也能換算。</p>
<table>
<tr><th>頻道</th><th>影片第 0 秒的播出時間</th><th>時鐘一致</th><th>廣告破口</th><th>填寫格數</th></tr>
{stats}
</table>
<p>四台一致率皆為 100%。影片第 0 秒對應 11:59:41 至 11:59:55，與檔名時間差 10–22 秒，若直接用檔名對時，每台都會錯位。</p>

<p><b>（2）換題與無關字幕怎麼判斷</b></p>
<ol>
<li>只讀主標題區：每台設定固定的讀取範圍，跑馬燈、角落天氣、別則推播與小廣告都不在範圍內（圖 6、圖 7）。</li>
<li>取字最大的一行：同一區若有受訪者職稱的小字名條，標記為「可能是字幕」；「○○報導」等記者署名直接濾除。</li>
<li>合成文字段：連續幾秒內容相近（容許 OCR 錯字）的畫面合成一段，記下開始時間與秒數。</li>
<li>由 LLM 判斷是否同一則：每 20 分鐘一批送出，前後各附 1–2 分鐘上下文。規則是畫面形式或標題寫法改變都不算換題，只有事件改變才算。</li>
<li>寫五字標：依命題規則與 10/26 範例的寫法。地點只能取畫面上出現的，優先用標題中最具體的地名；指控類新聞若標題只寫「風波」「疑」，五字標不可寫成定論。</li>
<li>規則檢查：程式檢查五字標是否含「廣告」、長度、未確認的指控、社會新聞是否缺地點，不合格就退回 LLM 重寫。以人名或案名就能辨識的新聞可保留原名（比照命題示例「俊傑偷渡中」）。</li>
<li>跨台統一：同一事件在四台使用同一名字，並累積成事件命名表供之後沿用；改名時不得失去地點、不得新增評價字眼，「氣象」不改。</li>
</ol>

<p><b>（3）廣告包框怎麼處理</b></p>
<p>判斷廣告時不看「畫面上有沒有新聞文字」，而是看主畫面的版面。四台的廣告樣式不同，各自使用最穩定的特徵：</p>
<table>
<tr><th style="width:12%">頻道</th><th>廣告樣式</th><th style="width:30%">判定特徵</th></tr>
<tr><td>TVBS</td><td>全螢幕廣告</td><td>時鐘消失</td></tr>
<tr><td>東森</td><td>全螢幕廣告，中間插入沒有時鐘的新聞預告卡，以及 23 秒的插播快訊</td><td>時鐘消失；兩段廣告間隔不到 60 秒視為同一破口</td></tr>
<tr><td>民視</td><td>包框：左邊播廣告、右邊「現在最焦點」，下方 bar 輪播已播過的標題</td><td>右上「現在最焦點」字樣</td></tr>
<tr><td>華視</td><td>全螢幕廣告，加上「正在播出 Now On CTS」台呼</td><td>時鐘消失</td></tr>
</table>
<div class="two fig">
<div><img src="img/wrap_ftv.jpg"><div class="cap">圖 3　民視包框（12:36）。時鐘仍在，下方 bar 顯示的是 12:12 已播過的別則標題；系統以右上「現在最焦點」判定為廣告。</div></div>
<div><img src="img/ebc_promo.jpg"><div class="cap">圖 4　東森廣告中的預告卡。有新聞標題但沒有時鐘，判定為廣告。</div></div>
</div>
<table>
<tr><th style="width:22%">情境</th><th>處理方式</th></tr>
<tr><td>進入廣告</td><td>連續 8 秒以上沒有新聞特徵才算；整段破口滿 60 秒才記「廣告」，以排除片頭、片尾與全螢幕圖卡</td></tr>
<tr><td>廣告中短暫出現新聞</td><td>兩段廣告之間不到 60 秒的新聞（如東森 12:43 插播快訊）視為破口的一部分，不另外記</td></tr>
<tr><td>回到新聞</td><td>廣告結束後的第一則新聞一定重新寫五字標，即使是同一則的延續，避免沿用包框殘留的文字</td></tr>
<tr><td>廣告前的預告</td><td>廣告前幾秒的「稍後報導」因不到 30 秒而不記，回到新聞後才記（如華視 12:32 武嶺重機預告，12:35 才記）</td></tr>
<tr><td>無法判斷</td><td>系統不停下來等人工：仍以最可能的判斷寫入，調低信心，把理由寫進驗證頁並列入抽查清單</td></tr>
</table>

<h3>3.3 採用工具 Tools</h3>
<div class="fig">{diagrams.architecture()}<div class="cap">圖 5　系統架構：本機處理影片與文字辨識，只把標題文字送到雲端 LLM</div></div>
<table>
<tr><th style="width:13%">功能</th><th style="width:20%">選用工具</th><th>選用理由</th><th style="width:24%">已知限制</th></tr>
<tr><td>畫面抽取</td><td>ffmpeg（硬體解碼）</td><td>免費、穩定，每秒一張即可滿足分鐘精度</td><td>無</td></tr>
<tr><td>文字辨識</td><td>Apple Vision（macOS 內建）</td><td>在本機執行、免費、繁體中文辨識佳，影片不需上傳雲端</td><td>需使用 Mac；小字偶有錯字，由 LLM 容錯</td></tr>
<tr><td>時間與廣告</td><td>Python 規則</td><td>可解釋、可重現、沒有額外成本</td><td>電視台改版時需更新區域設定（集中在 config.py）</td></tr>
<tr><td>語意判斷</td><td>LLM（本次以 Claude 示範，正式改用 DeepSeek）</td><td>只送文字、不送影片，成本低；換後端只需改一個設定；結果快取，同一輸入重跑結果相同</td><td>新事件首次命名可能與人工習慣不同</td></tr>
<tr><td>輸出</td><td>openpyxl、HTML</td><td>由範本複製一份再寫入，格式不會被改動</td><td>無</td></tr>
</table>
<div class="two fig">
<div><img src="img/roi_tvbs.jpg"><div class="cap">圖 6　只讀固定區域：主標題、時鐘、地點標；跑馬燈不讀（TVBS 12:09）。</div></div>
<div><img src="img/ftv_normal.jpg"><div class="cap">圖 7　民視標題區從左側推播框右邊開始讀，避免把別則推播混進標題（民視 12:03）。</div></div>
</div>
<p>資料格式：每秒一筆辨識紀錄（frames.jsonl）、時間與廣告分析（analysis.json）、每則新聞（stories.json，含開始時間、五字標、標題、地點、信心與理由）、事件命名表（event_registry.json）。</p>

<h3>3.4 施作方式 Implementation</h3>
<table class="keep">
<tr><th style="width:8%">步驟</th><th style="width:22%">輸入</th><th>處理機制與參數</th><th style="width:20%">輸出</th></tr>
<tr><td>1</td><td>四台 mp4</td><td>每秒抽一張畫面，讀取標題、時鐘、地點、包框特徵區的文字</td><td>每秒一筆辨識紀錄</td></tr>
<tr><td>2</td><td>辨識紀錄</td><td>時鐘推算偏移量；8 秒無新聞特徵進入廣告、破口至少 60 秒、間隔不到 60 秒合併；相似度 70% 以上合成文字段</td><td>時間、廣告區段、文字段</td></tr>
<tr><td>3</td><td>文字段</td><td>LLM 每 20 分鐘一批判斷同一則並寫五字標；規則檢查不合格就重寫；跨台統一命名</td><td>每則新聞與五字標</td></tr>
<tr><td>4</td><td>每則新聞、廣告</td><td>依 10/26 範例歸納的填法對到分鐘（見下表）</td><td>每分鐘的儲存格文字</td></tr>
<tr><td>5</td><td>範本 Excel</td><td>複製範本後只寫入 F、J、N、R 四欄，並產生驗證頁</td><td>Excel、驗證頁</td></tr>
</table>
<table class="keep">
<tr><th style="width:40%">10/26 範例中觀察到的寫法</th><th>系統的填寫規則</th></tr>
<tr><td>每台每小時 22–27 格，約每 2 分鐘一則</td><td>某分鐘有新聞開始才填，延續的分鐘留白；不到 30 秒的新聞（預告、快訊帶過）不記</td></tr>
<tr><td>同一格寫兩則的情況，每台至多一次，最多 2 則</td><td>同一分鐘有多則時以「/」連接，最多 2 則，保留播出最久的兩則</td></tr>
<tr><td>「廣告」都是單獨一格</td><td>有廣告開始的分鐘只寫「廣告」；若同一分鐘就回到新聞，寫「廣告/五字標」</td></tr>
</table>
<p>一鍵執行：<code>python pipeline/run.py</code>，即可從影片一路產出 Excel 與驗證頁。</p>

<h2>4. 評估結果與結論 Results &amp; Conclusion</h2>
<h3>4.1 評估結果</h3>
<p>以下為系統自動產出、未經人工修改的 Excel 片段（12:30–12:41）。四台各填 {cmin}–{cmax} 格，與範例的 22–27 格相近；廣告每台 3–4 次（範例 2–4 次）。程式比對範本後，四欄以外的儲存格差異為 0 處。</p>
{excel_excerpt(1230, 1241)}
<table>
<tr><th>指標（權重）</th><th style="width:11%">目標</th><th>實測結果（11/06 12:00–13:00，四台）</th><th style="width:9%">達標</th></tr>
<tr><td>五字標可辨識率（30%）</td><td>90%</td><td>首輪抽查民視與 TVBS 共 51 格，5 格有問題，約 90%；錯誤類型已改寫成規則並重跑</td><td>達標</td></tr>
<tr><td>分鐘對齊率（20%）</td><td>95%</td><td>逐格核對 112 格：系統判定時間前 6 秒的標題 bar 仍是前一則、後 4 秒已是本則才算正確，核對時不參考系統理由。正確 109 格（97.3%），3 格分段點偏早</td><td>達標</td></tr>
<tr><td>廣告破口正確率（20%）</td><td>100%</td><td>13 段全部正確（TVBS 3、東森 3、民視 3 段包框、華視 4）</td><td>達標</td></tr>
<tr><td>零人工補填（10%）</td><td>0 格</td><td>0 格；LLM 失敗會自動重試，不合格的五字標自動重寫</td><td>達標</td></tr>
<tr><td>格式正確（10%）</td><td>0 處</td><td>0 處，Excel 可正常開啟</td><td>達標</td></tr>
<tr><td>處理速度（10%）</td><td>60 分鐘</td><td>約 18 分鐘（抽取與辨識四台同時進行約 12.5 分鐘，LLM 約 5 分鐘）</td><td>達標</td></tr>
</table>
<p>加權總分 100%。另外驗證穩定度：同一份輸入連續執行兩次，Excel 差異 0 格。</p>
<p>實驗過程：每次抽查後把錯誤分類、改成規則再重跑。以下是本次實際發現並修正的問題：</p>
<table>
<tr><th style="width:30%">抽查發現</th><th style="width:24%">錯誤類型</th><th>修正方式與結果</th></tr>
<tr><td>TVBS「蘇志燮廣告」</td><td>五字標含「廣告」，易與破口混淆</td><td>規則檢查後重寫為「蘇志燮爆紅」</td></tr>
<tr><td>華視「黃仁勳涉諜」、民視「俊傑涉黑幫」</td><td>標題只寫「風波」「疑」卻寫成定論</td><td>加入保留字眼檢查，改為「黃仁勳風波」「俊傑涉黑疑雲」</td></tr>
<tr><td>社會新聞缺地點 26 則，如民視「縱火燒警車」</td><td>命題規定社會事件要有地點</td><td>加入地點檢查，改為「汐止燒警車」等；以人名辨識的「張俊傑求刑」經審稿保留</td></tr>
<tr><td>民視 12:33 記為「氣象」</td><td>保暖商機新聞被當成天氣</td><td>「氣象」只用於天氣預報，改為「保暖商機」；12:34 的天氣預報仍記「氣象」</td></tr>
<tr><td>民視 12:12「大言不慚」</td><td>主播圖卡上的引言被當成一則</td><td>信心低於 0.35 且不到 60 秒的段落併入前一則</td></tr>
<tr><td>12:59 開始的新聞消失；東森廣告中的快訊被記一格</td><td>時段與破口邊界處理</td><td>最後一則不以整點截斷；破口內的新聞不另記</td></tr>
<tr><td>跨台統一把「兒虐數據風波」改成「兒虐案」</td><td>統一命名改變原意</td><td>加入改名防護，保留原名</td></tr>
</table>
<p>Prototype 介面：驗證頁（output/驗證頁.html）。每一格列出開始畫面截圖、播出時間、秒數、LLM 信心與判斷理由，黃底為建議抽查的格子，抽查員不需重看影片即可判斷多數格子。</p>
<div class="fig"><img src="img/review_ui.png"><div class="cap">圖 8　驗證頁介面截圖（12:00–12:01）</div></div>

<h3>4.2 結論與選擇</h3>
<p>目前進度：完整流程已實作，並跑完 11/06 四台一小時，產出 Excel 與驗證頁。最終採用「規則處理時間與廣告、LLM 處理語意」的方案，理由是時間與廣告兩項用規則已達 100% 正確，而且可以解釋、可以重現。</p>
<table>
<tr><th style="width:28%">取捨</th><th>選擇與放棄</th></tr>
<tr><td>規則或全部交給 AI</td><td>放棄「多模態模型直接看影片填表」的簡便，換取可驗證、可追溯</td></tr>
<tr><td>每秒一張或更高頻率</td><td>表格只需要分鐘精度，每秒一張已足夠，放棄秒級細節以換取速度</td></tr>
<tr><td>語音辨識</td><td>本版未使用，標題 bar 已足以分段；列為下一階段處理難判片段的輔助</td></tr>
</table>
<table>
<tr><th style="width:36%">已知限制</th><th style="width:22%">影響</th><th>下一階段做法</th></tr>
<tr><td>分段點偶爾偏早（3/112），並發現漏記 1 則（民視 12:44 沈伯洋下廚被併入前一則）</td><td>少數格早一分鐘或漏記</td><td>加入主播語音判斷；試行期以人工對照組量測漏記率</td></tr>
<tr><td>新事件第一次出現時，命名由 LLM 決定</td><td>可能與人工習慣寫法不同</td><td>事件命名表每週由組長檢視；正式改用 DeepSeek 並固定隨機性參數</td></tr>
<tr><td>電視台改版或特殊節目版面</td><td>讀取區域失效</td><td>時鐘一致率低於 95% 或廣告段數異常時告警，由組長更新設定</td></tr>
</table>
<p>擴大到全天：單台處理 1 小時影片約需 7–12.5 分鐘，一台 Mac 即可即時處理四台。LLM 每小時四台約 12 次呼叫，輸入約 14 萬字、輸出約 3 萬字，以 DeepSeek 公開價格估算每小時約數元、全天約數十元（以實際帳單為準）。目前還缺少：直接接收側錄串流、全天各節目的版面設定、人工對照組與每週抽查制度、排程與告警。</p>

<h2>5. 推動 The Plan</h2>
<h3>5.1 前 90 天</h3>
<div class="fig">{diagrams.roadmap()}<div class="cap">圖 9　前 90 天落地路線圖（階段目標、交付物、驗收 KPI 與 Go/No-go 判斷點）</div></div>
<p>擴大推動或停損的條件：第 30 天時，若分鐘對齊率達 95% 且廣告破口全部正確，就擴大到全天；若五字標可辨識率低於 85% 或廣告判斷出錯，暫停擴大，只保留已證實穩定的時間與廣告自動化，五字標改由系統提供完整標題、人工改寫後再評估。</p>

<h3>5.2 潛在問題分析與預防</h3>
<table>
<tr><th style="width:28%">潛在問題</th><th style="width:9%">機率</th><th style="width:9%">衝擊</th><th>預防與應變</th></tr>
<tr><td>電視台改版，字卡位置變動</td><td>中</td><td>高</td><td>自動監控時鐘一致率與廣告段數並告警；區域設定集中在一個檔案，改版當天即可修正</td></tr>
<tr><td>出現新的包框樣式</td><td>中</td><td>高</td><td>廣告段數比平常少時告警；新增一條特徵設定即可</td></tr>
<tr><td>LLM 服務中斷或延遲</td><td>低</td><td>中</td><td>自動重試，可切換後端；仍失敗時以完整標題前段寫入並標低信心，不中斷流程</td></tr>
<tr><td>五字標寫法不一致</td><td>中</td><td>中</td><td>結果快取、事件命名表、每週抽查統一</td></tr>
<tr><td>資料外流疑慮</td><td>低</td><td>中</td><td>影片與截圖留在本機，只把標題文字送到 LLM</td></tr>
</table>

<h3>5.3 人與關係</h3>
<table>
<tr><th style="width:18%">利害關係人</th><th style="width:28%">關注與顧慮</th><th>溝通策略</th></tr>
<tr><td>當班工讀生</td><td>工作是否會被取代</td><td>角色轉為抽查與錯誤回報，工時下降，判斷經驗會被寫成規則保留下來</td></tr>
<tr><td>行政</td><td>格式是否改變、是否要重新學</td><td>Excel 與原範本完全相同，只是隔天一早就準備好</td></tr>
<tr><td>新聞部、業務主管</td><td>準不準、出錯誰負責</td><td>每一格都能在驗證頁查證，每週提供正確率報告；監看組長為負責人</td></tr>
<tr><td>IT、資安</td><td>成本與資料外流</td><td>文字辨識在本機執行，只送文字；LLM 全天費用約數十元</td></tr>
</table>
"""
    page = (f"<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'><title>新聞監看全自動填表提案</title>"
            f"<style>{CSS}</style></head><body>{body}</body></html>")
    out = REPORT / "提案報告.html"
    out.write_text(page, encoding="utf-8")
    pdf = REPORT / "提案報告.pdf"
    subprocess.run([str(CHROME), "--headless", "--no-pdf-header-footer", "--allow-file-access-from-files",
                    f"--print-to-pdf={pdf}", out.as_uri()], check=True, capture_output=True)
    return out, pdf


if __name__ == "__main__":
    print(*build())
