/* AI 違規廣告快篩 — 前端邏輯
   OCR（Windows 內建 / 瀏覽器 tesseract.js）、法規比對、陳情信生成
   改完請執行 build.py 重新產生 ../static/index.html */
const $ = id => document.getElementById(id);

/* 頁面內訊息（取代 alert）：type = err / warn / ok */
/* action（選用）：{ label, onClick } —— 在訊息下方多一顆按鈕。
   目前用在「換圖清掉了你手打的文字」時提供還原，不要讓使用者的輸入默默消失。 */
function notify(slot, text, type, autoHideMs, action) {
  const el = $(slot);
  if (!el) return;
  if (el._t) { clearTimeout(el._t); el._t = null; }
  el.className = 'notice show ' + (type || 'err');
  el.innerHTML = '<button class="x" type="button" title="關閉">✕</button>'
               + esc(text).replace(/\n/g, '<br>')
               + (action ? '<button class="mini act" type="button">' + esc(action.label) + '</button>' : '');
  el.querySelector('.x').onclick = () => clearNotice(slot);
  if (action) el.querySelector('.act').onclick = () => { clearNotice(slot); action.onClick(); };
  if (autoHideMs) el._t = setTimeout(() => clearNotice(slot), autoHideMs);
}
function clearNotice(slot) {
  const el = $(slot);
  if (!el) return;
  if (el._t) { clearTimeout(el._t); el._t = null; }
  el.className = 'notice';
  el.innerHTML = '';
}

/* 按鈕載入中狀態：停用 + 轉圈 + 文字替換 */
function setBusy(btn, busyText) {
  if (!btn) return;
  if (busyText) {
    if (!btn.dataset.label) btn.dataset.label = btn.textContent;
    btn.innerHTML = '<span class="btnspin"></span>' + esc(busyText);
    btn.disabled = true;
  } else {
    if (btn.dataset.label) btn.textContent = btn.dataset.label;
    btn.disabled = false;
  }
}

/* 使用者手動編輯過的文字不可被機器覆蓋 */
$('adText').addEventListener('input', () => { textIsMachine = false; });
$('fProduct').addEventListener('input', () => { productIsMachine = false; });

/* 發現日期預設今天。不能用 toISOString()——那是 UTC，台灣清晨時段會變成昨天 */
(function initToday() {
  const el = $('fDate');
  if (!el || el.value) return;
  const d = new Date(), pad = n => String(n).padStart(2, '0');
  el.value = d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
})();

/* 頂部步驟指示：跟著流程點亮 */
function markStep(n) {
  document.querySelectorAll('#steps .st').forEach(el => {
    el.classList.toggle('on', Number(el.dataset.step) <= n);
  });
}

/* ============ 狀態 ============ */
let imageB64 = null, mediaType = null, analysis = null;
let rawDataUrl = null, aiEnabled = false;
let lastOcrText = '', ocrBusy = false;
/* L1：文字框內容是不是機器（OCR）產生的。用旗標而不是字串比對——
   交叉比對會把兩套引擎的結果串接起來，字串永遠對不上，舊寫法等於從不清空。 */
let textIsMachine = false;
let productIsMachine = false;   // 產品名稱是不是自動帶入的
/* L2/L4：每次換圖遞增，讓飛行中的非同步結果知道自己已經過期 */
let runToken = 0;
let analyzing = false;
/* 這支 exe 的後端能不能自己用 Windows 內建 OCR 讀圖：null=還沒試過，true/false=已知 */
let serverOcr = null;

/* ============ 免費 AI（Gemini）設定 ============ */
const GEMINI_MODELS = ['gemini-2.5-flash', 'gemini-2.0-flash', 'gemini-flash-latest'];
const gKeyGet = () => (localStorage.getItem('gemini_key') || '').trim();

/* @generated-from-regulations
   以下兩份資料由 build.py 從 ../regulations.json 自動產生並覆寫，請不要手改。
   直接開這個檔開發時，用的是下面這份預設值。 */
const KEYWORD_SCOPE = { cosmetic_only: [], food_only: [], drug_only: [] };
const KEYWORD_EVIDENCE = { sources: [], map: {} };
const PRE_APPROVAL = {};
const OUT_OF_SCOPE = {};
const LAWS = {
  'fsa-28-1': {law_name:'食品安全衛生管理法', article:'第28條第1項',
    summary:'食品、食品添加物、食品用洗潔劑及經中央主管機關公告之食品器具、容器或包裝，其標示、宣傳或廣告，不得有不實、誇張或易生誤解之情形。',
    penalty:'依同法第45條第1項，處新臺幣4萬元以上400萬元以下罰鍰。',
    url:'https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=L0040001&flno=28'},
  'fsa-28-2': {law_name:'食品安全衛生管理法', article:'第28條第2項',
    summary:'食品不得為醫療效能之標示、宣傳或廣告。',
    penalty:'依同法第45條第1項，處新臺幣60萬元以上500萬元以下罰鍰。',
    url:'https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=L0040001&flno=28'},
  'cos-10-1': {law_name:'化粧品衛生安全管理法', article:'第10條第1項',
    summary:'化粧品之標示、宣傳及廣告內容，不得有虛偽或誇大之情事。',
    penalty:'依同法第20條第1項，處新臺幣4萬元以上20萬元以下罰鍰。',
    url:'https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=L0030013&flno=10'},
  'cos-10-2': {law_name:'化粧品衛生安全管理法', article:'第10條第2項',
    summary:'化粧品不得為醫療效能之標示、宣傳或廣告。',
    penalty:'依同法第20條第1項，處新臺幣60萬元以上500萬元以下罰鍰。',
    url:'https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=L0030013&flno=10'},
  'hf-14-1': {law_name:'健康食品管理法', article:'第14條第1項',
    summary:'健康食品之標示或廣告不得有虛偽不實、誇張之內容，其宣稱之保健效能不得超過許可範圍，並應依中央主管機關查驗登記之內容。',
    penalty:'依同法第24條規定處罰（罰鍰額度請以主管機關裁處及現行條文為準）。',
    url:'https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=L0040012&flno=14'},
  'hf-14-2': {law_name:'健康食品管理法', article:'第14條第2項',
    summary:'健康食品之標示或廣告，不得涉及醫療效能之內容。',
    penalty:'依同法第24條規定處罰（罰鍰額度請以主管機關裁處及現行條文為準）。',
    url:'https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=L0040012&flno=14'},
  'pha-69': {law_name:'藥事法', article:'第69條',
    summary:'非本法所稱之藥物（非藥品、非醫療器材），不得為醫療效能之標示或宣傳。',
    penalty:'依同法第91條第2項，處新臺幣60萬元以上2,500萬元以下罰鍰。',
    url:'https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=L0030001&flno=69'},
  'pha-66': {law_name:'藥事法', article:'第66條',
    summary:'藥商刊播藥物廣告時，應於刊播前申請中央或直轄市衛生主管機關核准，並向傳播業者送驗核准文件；經核准之廣告內容不得變更。',
    penalty:'依同法第92條，處新臺幣20萬元以上500萬元以下罰鍰。',
    url:'https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=L0030001&flno=66'},
  'md-46': {law_name:'醫療器材管理法', article:'第46條',
    summary:'非醫療器材，不得為醫療效能之標示或宣傳。',
    penalty:'依同法第65條，處新臺幣60萬元以上2,500萬元以下罰鍰。',
    url:'https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=L0030106&flno=46'},
  'md-41': {law_name:'醫療器材管理法', article:'第41條第1項',
    summary:'醫療器材廣告應由許可證所有人或登錄者於刊播前，檢具廣告所有文字、圖畫或言詞申請核准，並向傳播業者送驗核准文件後始得刊播；廣告內容不得逾越核准範圍。',
    penalty:'依同法第65條，處新臺幣20萬元以上500萬元以下罰鍰。',
    url:'https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=L0030106&flno=41'}
};
/* @end-generated */

/* 依「產品類別」挑正確法條 —— 示範模式的後端一律回食安法，
   但化粧品應引化粧品衛生安全管理法、健康食品應引健康食品管理法。 */
const LAW_BY_TYPE = {
  '食品':     { '宣稱醫療效能': 'fsa-28-2', '誇大不實': 'fsa-28-1' },
  '健康食品': { '宣稱醫療效能': 'hf-14-2',  '誇大不實': 'hf-14-1'  },
  '化粧品':   { '宣稱醫療效能': 'cos-10-2', '誇大不實': 'cos-10-1' },
  // 藥品與醫療器材本來就可以宣稱療效，違規點在「廣告未經核准或逾越核准範圍」
  '藥品':     { '宣稱醫療效能': 'pha-66',   '誇大不實': 'pha-66'   },
  '醫療器材': { '宣稱醫療效能': 'md-41',    '誇大不實': 'md-41'    }
};
function lawFor(v, productType) {
  const map = LAW_BY_TYPE[productType];
  const id = map && map[v.violation_type];
  if (id && LAWS[id]) return Object.assign({ id: id }, LAWS[id]);
  return v.law || {};
}
/* L6：藥品／醫療器材本得宣稱療效，違規點在「廣告未經核准」。
   只換法條而理由仍寫「非藥物不得宣稱」會前後矛盾，理由也要跟著換。 */
function reasonFor(v, productType) {
  if (productType === '藥品' || productType === '醫療器材') {
    return '廣告內容涉及療效宣稱，請查核該廣告是否經事前核准，以及有無逾越核准範圍。'
         + '（原比對結果：' + (v.reason || '') + '）';
  }
  return v.reason || '';
}

/* 關鍵字的品類維度：化粧品專屬的詞（漢方、療程、雷射）不該套到食品廣告上，
   反之亦然。沒選類別時不過濾——寧可多列也不要漏抓。 */
const FOODISH = ['食品', '健康食品'];
const DRUGGISH = ['藥品', '醫療器材'];
function scopeOf(kw) {
  if (KEYWORD_SCOPE.cosmetic_only.indexOf(kw) >= 0) return '化粧品';
  if (KEYWORD_SCOPE.food_only.indexOf(kw) >= 0) return '食品';
  if ((KEYWORD_SCOPE.drug_only || []).indexOf(kw) >= 0) return '藥物';
  return '';
}
function applicable(v, productType) {
  const sc = scopeOf(v.quote);
  if (!sc) return true;                                    // 通用詞
  if (sc === '化粧品') return productType === '化粧品';
  if (sc === '食品') return FOODISH.indexOf(productType) >= 0;
  // 藥物廣告專屬的禁止手法（藉報導宣傳、列舉服用對象、危言聳聽），
  // 食品或化粧品這樣寫並不當然違規，套過去會誤判
  if (sc === '藥物') return DRUGGISH.indexOf(productType) >= 0;
  return true;
}
/* 只有明確選了食品類或化粧品才過濾。
   藥品／醫材本身就能宣稱療效，違規點在核准與否，我們無從判斷哪些詞不適用，
   所以維持不過濾、全部列出讓人工判斷——寧可多列也不要漏抓。
   （食品／化粧品廣告仍會由 applicable() 濾掉藥物專屬的手法性詞句。） */
function shouldFilter(productType) {
  return productType === '化粧品' || FOODISH.indexOf(productType) >= 0;
}
/* 同一段文字被長短兩個關鍵字都命中時（例如「美白」與「7天美白」），
   只留較長、較具體的那一個，避免同一句被計成兩筆違規。
   有了這層，長短詞就能並存——短詞負責廣泛涵蓋，長詞負責精確描述。 */
function dedupeNested(vios) {
  return vios.filter(v => !vios.some(o =>
    o !== v && o.quote.length > v.quote.length && o.quote.indexOf(v.quote) >= 0));
}

/* 順序很重要：必須先過濾品類、再去重巢狀。
   顛倒過來時，「短詞通用、長詞品類專屬」的組合會兩步各砍掉一個而變成 0 命中——
   例如選「食品」的廣告寫「三週消除橘皮組織」：長詞「消除橘皮組織」是化粧品專屬、
   會被 applicable() 濾掉，而通用短詞「橘皮組織」早在 dedupeNested() 就被當成
   已被長詞涵蓋而刪除。實測這樣確定漏抓 10 組（消除法令紋、消除魚尾紋、
   修復受損肌膚、減少孕斑…，以及化粧品類的「根除糖尿病」）。 */
function splitByScope(vios, productType) {
  if (!shouldFilter(productType)) return { keep: dedupeNested(vios), drop: [] };
  const keep = [], drop = [];
  vios.forEach(v => (applicable(v, productType) ? keep : drop).push(v));
  return { keep: dedupeNested(keep), drop: dedupeNested(drop) };
}

/* 關鍵字的證據等級：
     c 有實際裁處案例 ／ o 主管機關認定基準明文例示 ／ i 僅依法規條文推論
   推論來的只能標示「疑似」，不能講得像已經定讞。 */
const EV_LABEL = { c: '有裁處案例', o: '法規明文例示', i: '疑似・待認定' };
function evidenceOf(kw) {
  const e = (KEYWORD_EVIDENCE.map || {})[kw];
  if (!e) return { level: 'i', source: '' };
  return { level: e[0], source: (KEYWORD_EVIDENCE.sources || [])[e[1]] || '' };
}

function currentType() {
  const sel = $('fType');
  return (sel && sel.value) || (analysis && analysis.product_type) || '';
}

/* 以 OCR 第一行猜產品名稱。第一行通常是品名，但也可能是促銷標語或整句廣告詞，
   所以要排除：含句讀（品名不會有逗號句號）、或本身就是促銷用語的行。 */
const PROMO = /限時|優惠|買一送一|買二送一|熱銷|第一名|免運|特價|下殺|團購|加購|試用/;
function guessProductName(text) {
  const first = String(text || '').split('\n').map(x => x.trim()).filter(Boolean)[0] || '';
  if (first.length < 2 || first.length > 30) return '';
  if (/[，,。.！!？?；;、]/.test(first)) return '';   // 是句子不是品名
  if (PROMO.test(first)) return '';                   // 是促銷標語不是品名
  return first;
}

/* ============ 執行模式偵測 ============
   exe 模式：/api/analyze 由本機程式處理（Windows OCR + 關鍵字比對）
   純瀏覽器模式：GitHub Pages 上沒有後端，前端自己讀 regulations.json 做比對 */
let standalone = false;
let REGS = null;

function loadLocalRegulations() {
  return fetch('regulations.json', { cache: 'no-cache' })
    .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(j => { REGS = j; });
}

function enterStandalone() {
  standalone = true;
  serverOcr = false;                       // 沒有後端 OCR，直接走瀏覽器 OCR
  if (document.body) document.body.classList.add('standalone');
  return loadLocalRegulations().catch(e =>
    notify('noticeStep1', '無法載入法規資料庫（regulations.json）：' + e.message
         + '\n請確認檔案與網頁放在同一個目錄。', 'err'));
}

fetch('/api/status')
  .then(r => { if (!r.ok) throw new Error('no backend'); return r.json(); })
  .then(s => { aiEnabled = !!s.ai_enabled; })
  .catch(() => enterStandalone());

/* 純瀏覽器模式的比對引擎。對應 exe 示範模式的行為，但多做兩件事：
   產品名稱取 OCR 第一行（exe 一律回「示範模式無法辨識」）、
   風險等級依嚴重度分級（exe 一律回「中」）。 */
/* 語境排除。這些關鍵字確實是主管機關例示或有裁處案例的違規用語，不能刪
   （「糖尿病」全庫只有一個組合詞，拔掉裸詞等於放棄整個病名的召回），但在法定
   警語與加工製程敘述裡出現時並非違規宣稱，硬判下去就是誣告。
   兩種排除方式：
     吸收型 —— 命中只是良性長詞的一部分（再生紙裡的「再生」、耐磨損裡的
                「磨損」、超高溫殺菌裡的「殺菌」），無條件排除。
     語境型 —— 同句有警語片語才排除，且同句不能有療效動詞、也不能有其他
                「無法被語境排除」的違規命中。
   後端 backend/analyzer.py 的 _apply_context_guard 是同一套邏輯，兩邊要一起改。 */
const SENT_SPLIT = /[。！？；.!?;\n\r]+/;
function ctxGuardTable() {
  const ce = (typeof CONTEXT_EXCLUSIONS !== 'undefined' && CONTEXT_EXCLUSIONS) || {};
  const groups = ce.groups || {}, guard = {};
  (ce.rules || []).forEach(r => {
    const ctx = (r.context && r.context.length) ? r.context : (groups[r.group] || []);
    (r.keywords || []).forEach(kw => { guard[kw] = (guard[kw] || []).concat(ctx); });
  });
  return guard;
}
function absorbedBy(sent, kw, ctx) {
  const longer = ctx.filter(c => c !== kw && c.indexOf(kw) >= 0);
  if (!longer.length) return false;
  const spans = [];
  longer.forEach(c => {
    for (let i = sent.indexOf(c); i >= 0; i = sent.indexOf(c, i + 1)) spans.push([i, i + c.length]);
  });
  if (!spans.length) return false;
  for (let i = sent.indexOf(kw); i >= 0; i = sent.indexOf(kw, i + 1))
    if (!spans.some(s => s[0] <= i && i + kw.length <= s[1])) return false;
  return true;
}
function applyContextGuard(text, vios) {
  const guard = ctxGuardTable();
  if (!Object.keys(guard).length) return vios;
  const ce = (typeof CONTEXT_EXCLUSIONS !== 'undefined' && CONTEXT_EXCLUSIONS) || {};
  const blockers = ce.claim_blockers || [];
  const sents = String(text || '').split(SENT_SPLIT).filter(s => s);
  const blocked = sent => blockers.some(b => sent.indexOf(b) >= 0);
  const suppressible = (sent, kw) => {
    const ctx = guard[kw];
    if (!ctx) return false;
    if (absorbedBy(sent, kw, ctx)) return true;
    if (blocked(sent)) return false;
    return ctx.some(c => sent.indexOf(c) >= 0);
  };
  return vios.filter(v => {
    const kw = v.quote, ctx = guard[kw];
    if (!ctx) return true;
    const hosts = sents.filter(s => s.indexOf(kw) >= 0);
    if (!hosts.length) return true;
    return !hosts.every(sent => {
      if (absorbedBy(sent, kw, ctx)) return true;
      if (blocked(sent)) return false;
      if (!ctx.some(c => sent.indexOf(c) >= 0)) return false;
      return !vios.some(o => o !== v && o.quote !== kw
        && sent.indexOf(o.quote) >= 0 && !suppressible(sent, o.quote));
    });
  });
}

function analyzeLocal(text) {
  if (!REGS) throw new Error('法規資料庫尚未載入完成，請稍候再試。');
  const dk = REGS.demo_keywords || {};
  const laws = {};
  (REGS.laws || []).forEach(l => { laws[l.id] = l; });
  const vios = [];
  const add = (kw, type, lawId, reason) => vios.push({
    quote: kw, violation_type: type, reason: reason, confidence: '中',
    law_id: lawId, law: Object.assign({}, laws[lawId] || {})
  });
  (dk.medical_efficacy || []).forEach(kw => {
    if (text.indexOf(kw) >= 0)
      add(kw, '宣稱醫療效能', 'fsa-28-2', '「' + kw + '」屬醫療效能用語，非藥物不得宣稱。');
  });
  (dk.exaggeration || []).forEach(kw => {
    if (text.indexOf(kw) >= 0)
      add(kw, '誇大不實', 'fsa-28-1', '「' + kw + '」屬誇大或易生誤解之用語。');
  });
  const kept = applyContextGuard(text, vios);
  return {
    mode: 'standalone',
    product_name: guessProductName(text) || '（未標示）',
    product_type: '無法判定',
    ad_text: text,
    violations: kept,
    risk_level: calcRisk(kept),
    overall_assessment: summarize(kept)
  };
}

/* ============ 圖片載入（點選 / 拖曳 / 貼上） ============ */
const drop = $('drop'), fileInput = $('file');
drop.onclick = () => fileInput.click();
fileInput.onchange = () => {
  if (fileInput.files[0]) loadFile(fileInput.files[0]);
  fileInput.value = '';        // 不清掉的話，再挑同一個檔名不會觸發 change
};

/* 拖曳收在整個 window，不只收在 #drop。
   出結果後 Step 2~4 的卡片會把 #drop 擠到畫面外，使用者要換第二張圖時幾乎一定是
   丟在結果區——那裡沒有 handler，瀏覽器就走預設行為「直接開啟那張圖」，整頁狀態
   連同已填的檢舉人資料一起沒了。這正是「無法拖曳第二張圖片接著分析」的成因。
   window 層的 dragover 一定要 preventDefault，否則 drop 事件根本不會觸發。 */
const dropOverlay = $('dropOverlay');
let dragDepth = 0;

function draggingFiles(e) {
  const dt = e.dataTransfer;
  if (!dt || !dt.types) return false;
  return [].slice.call(dt.types).indexOf('Files') >= 0;   // 純文字拖曳不要跳提示
}
function showDropHint(on) {
  dropOverlay.classList.toggle('hidden', !on);
  if (!on) drop.classList.remove('over');
}

window.addEventListener('dragenter', e => {
  if (!draggingFiles(e)) return;
  e.preventDefault();
  dragDepth++;                    // 經過子元素會連發 enter/leave，用計數才不會閃爍
  showDropHint(true);
});
window.addEventListener('dragover', e => {
  if (!draggingFiles(e)) return;
  e.preventDefault();
  e.dataTransfer.dropEffect = 'copy';
});
window.addEventListener('dragleave', e => {
  if (!draggingFiles(e)) return;
  dragDepth = Math.max(0, dragDepth - 1);
  if (!dragDepth) showDropHint(false);
});
window.addEventListener('drop', e => {
  e.preventDefault();             // 少了這行，瀏覽器會導航到那張圖，整頁狀態全丟
  dragDepth = 0;
  showDropHint(false);
  const f = e.dataTransfer && e.dataTransfer.files[0];
  if (f) loadFile(f);
});
/* 保險絲。上面的計數器理論上會歸零，但實務上 dragleave 不保證會發：
   拖曳中按 Esc 取消、把檔案拖出視窗外放開、或瀏覽器自己漏發事件，都會讓
   遮罩留在畫面上。原生拖曳進行中不會有 mouse / key 事件，所以只要收到
   其中任何一個，就代表拖曳早就結束了 —— 直接強制收掉。 */
function forceHideDropHint() {
  if (dropOverlay.classList.contains('hidden')) return;
  dragDepth = 0;
  showDropHint(false);
}
window.addEventListener('dragend', forceHideDropHint);
window.addEventListener('mousemove', forceHideDropHint);
window.addEventListener('pointerdown', forceHideDropHint);
window.addEventListener('keydown', forceHideDropHint);
window.addEventListener('blur', forceHideDropHint);

drop.ondragover = e => { e.preventDefault(); drop.classList.add('over'); };
document.addEventListener('paste', e => {
  const items = (e.clipboardData && e.clipboardData.items) || [];
  const item = [].slice.call(items).find(i => i.type.indexOf('image/') === 0);
  if (item) { e.preventDefault(); loadFile(item.getAsFile()); }
});

initRegionPicker();

const MAX_MB = 10;
const OK_TYPES = ['image/png', 'image/jpeg', 'image/webp', 'image/gif', 'image/bmp'];

function loadFile(f) {
  if (!f) return;
  if (analyzing) {                                   // L4：分析中不讓換圖，否則圖文不符
    notify('noticeStep1', '分析進行中，請等結果出來再換圖。', 'warn', 4000);
    return;
  }
  clearNotice('noticeStep1');

  const type = (f.type || '').toLowerCase();
  if (type && OK_TYPES.indexOf(type) < 0) {
    notify('noticeStep1', '不支援的檔案格式：' + (type || '未知') + '\n'
         + '請改用 JPG、PNG、WebP、GIF 或 BMP 圖片檔。', 'err');
    return;
  }
  const mb = (f.size || 0) / 1048576;
  if (mb > MAX_MB) {
    notify('noticeStep1', '圖片太大：' + mb.toFixed(1) + ' MB（上限 ' + MAX_MB + ' MB）\n'
         + '請先裁切或壓縮後再上傳，過大的圖也會讓辨識變慢。', 'err');
    return;
  }

  mediaType = type || 'image/png';
  const reader = new FileReader();
  reader.onerror = () => notify('noticeStep1', '圖片讀取失敗，請換一張試試。', 'err');
  reader.onload = () => {
    rawDataUrl = reader.result;
    imageB64 = rawDataUrl.split(',')[1];
    const img = $('preview');
    $('previewWrap').classList.remove('hidden');
    img.style.display = 'block';
    img.onload = () => {
      const w = img.naturalWidth, h = img.naturalHeight;
      // 只覆寫 #dropMain —— 以前是整個 drop.innerHTML 覆寫，第一次上傳後
      // 「支援哪些格式、可以拖曳」的提示就永久消失了
      $('dropMain').innerHTML = '已選擇：<b>' + esc(f.name || '剪貼簿圖片') + '</b>'
        + '<br><small>' + esc((type || 'image/png').replace('image/', '').toUpperCase())
        + '　·　' + w + ' × ' + h + ' px　·　' + mb.toFixed(1) + ' MB'
        + '　·　點擊、拖曳或 Ctrl + V 都可以直接換下一張</small>';
      if (Math.min(w, h) < 600) {
        notify('noticeStep1', '這張圖解析度偏低（' + w + ' × ' + h + ' px），文字辨識可能不準。\n'
             + '建議改用原圖或放大後的截圖；辨識完成後請務必檢查「廣告文字」欄位。', 'warn');
      }
    };
    img.src = rawDataUrl;
    // L1：換圖時清掉上一張留下的機器文字與分析結果，只保留使用者自己打的字
    runToken++;
    const ta = $('adText');
    // 換圖一律清掉上一張留下的文字。以前只清機器辨識的結果、保留使用者手打的字，
    // 結果是丟了新圖卻還拿舊文字去分析 —— 陳情信會引錄 A 圖的文字、附上 B 圖的
    // 截圖，送出去只會被承辦人剔除。使用者回報的症狀是「要重新整理才會辨識新圖」。
    // 手打的字不是不重要，所以清掉之後給一顆還原按鈕，而不是默默丟掉。
    const prevTyped = (!textIsMachine && ta.value.trim()) ? ta.value : '';
    ta.value = ''; lastOcrText = ''; textIsMachine = false;
    if (productIsMachine) { $('fProduct').value = ''; productIsMachine = false; }
    analysis = null;
    ['resultCard', 'letterCard', 'previewCard'].forEach(id => $(id).classList.add('hidden'));
    clearNotice('noticeStep3'); clearNotice('noticeStep4');
    markStep(1);
    if (aiEnabled || gKeyGet()) {
      $('ocrBar').classList.add('hidden');    // AI 模式直接看圖，不需要 OCR
    } else if (serverOcr === false) {
      runOCR(true);                           // 已知 Windows OCR 不能用 → 直接跑瀏覽器 OCR
    } else {
      ocrMsg(standalone
        ? '圖片已載入 — 正在你的瀏覽器裡辨識圖上的文字（首次需下載辨識模型約 9 MB）。'
        : '圖片已載入 — 正在用 Windows 內建 OCR 讀取圖上的文字。');
    }

    // 載入完直接分析，不用再捲回上面按按鈕。三個入口（拖曳／Ctrl+V／點選檔案）
    // 都會走到這裡，所以換下一張圖就是「丟進來」這一個動作。
    //
    // 但只在「廣告文字」是空的時候自動跑。欄位有字而且不是機器填的，代表使用者
    // 自己打過或改過（L1：機器不覆蓋使用者的字），上面的清空邏輯就不會動它；
    // 這時自動分析會拿「上一張圖的文字」去配「這一張圖」，產出的陳情信是錯的。
    // 還原提示要等分析跑完再出 —— runAnalysis() 開頭會 clearNotice('noticeStep1')，
    // 先貼會被立刻清掉。分析途中若出錯，那則錯誤訊息比還原提示重要，不要蓋掉它。
    const afterAnalysis = () => {
      if (!prevTyped) return;
      if ($('noticeStep1').classList.contains('show')) return;
      notify('noticeStep1',
             '已清掉上一張圖留下的文字，改用這張新圖重新辨識。'
             + '（你剛才手動輸入或修改過的內容沒有被丟掉，需要的話按下面還原。）',
             'ok', 20000,
             { label: '還原剛才的文字', onClick: () => {
                 ta.value = prevTyped; textIsMachine = false;
                 notify('noticeStep1', '已還原剛才的文字。注意：這段文字對應的是上一張圖，'
                      + '若要改用新圖重新辨識，把欄位清空後再按「開始快篩分析」。', 'warn', 12000);
               } });
    };
    Promise.resolve(runAnalysis()).then(afterAnalysis, afterAnalysis);
  };
  reader.readAsDataURL(f);
}

/* ============ 免費 OCR：tesseract.js，全程在瀏覽器內執行 ============ */
const TESS_CDN = 'https://cdn.jsdelivr.net/npm/tesseract.js@5.1.1/dist/tesseract.min.js';
let tessWorkerP = null, tessProgress = null;

function ocrMsg(text, busy) {
  $('ocrBar').classList.remove('hidden');
  $('ocrStatus').innerHTML = (busy ? '<span class="spin"></span>' : '') + esc(text);
}

function loadScript(src) {
  return new Promise((ok, err) => {
    const s = document.createElement('script');
    s.src = src;
    s.onload = ok;
    s.onerror = () => err(new Error('無法載入辨識元件，請確認這台電腦可以連上網際網路'));
    document.head.appendChild(s);
  });
}

/* 縮放圖片。實測「無條件放大」反而會讓辨識變差（插補會把筆畫糊掉），
   所以預設 1 倍原圖；只有在字太少、疑似小圖時才放大重試一次。 */
const MAX_CANVAS_PX = 12e6;   // 放大後的總像素上限，見 prepare()
const MAX_SIDE = 4000;   // 超過這個尺寸才縮小，純粹避免超大圖跑太慢

function loadImg(dataUrl) {
  return new Promise((res, rej) => {
    const img = new Image();
    img.onerror = () => rej(new Error('圖片無法讀取'));
    img.onload = () => res(img);
    img.src = dataUrl;
  });
}


const charCount = s => String(s || '').replace(/\s/g, '').length;

/* 對比拉伸：取 2%~98% 分位做線性伸展。
   單獨用會讓乾淨的圖變差，所以只在「再補一次」時當第二種讀法，靠聯集提升涵蓋。 */
function stretchContrast(canvas) {
  const ctx = canvas.getContext('2d');
  const d = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const a = d.data, n = a.length / 4;
  const gray = new Uint8Array(n), hist = new Uint32Array(256);
  for (let i = 0, j = 0; i < a.length; i += 4, j++) {
    const g = (a[i] * 0.299 + a[i + 1] * 0.587 + a[i + 2] * 0.114) | 0;
    gray[j] = g; hist[g]++;
  }
  let lo = 0, hi = 255, acc = 0;
  for (let v = 0; v < 256; v++) { acc += hist[v]; if (acc > n * 0.02) { lo = v; break; } }
  acc = 0;
  for (let v = 255; v >= 0; v--) { acc += hist[v]; if (acc > n * 0.02) { hi = v; break; } }
  const span = Math.max(1, hi - lo);
  for (let i = 0, j = 0; i < a.length; i += 4, j++) {
    const g = Math.max(0, Math.min(255, ((gray[j] - lo) * 255 / span) | 0));
    a[i] = a[i + 1] = a[i + 2] = g;
  }
  ctx.putImageData(d, 0, 0);
  return canvas;
}

/* 縮放並選擇性套用前處理，回傳 dataURL */
function prepare(img, scale, enhance) {
  // 放大受總像素上限約束。4000×3000 的原圖乘 2 就是 9600 萬像素、約 384 MB 的
  // RGBA，再 toDataURL 會產出上百 MB 的字串——分頁直接 OOM，iOS Safari 更是
  // 超過 1670 萬像素就回空白 canvas。縮小（scale<1）不受影響。
  const px = img.naturalWidth * img.naturalHeight;
  if (scale > 1 && px * scale * scale > MAX_CANVAS_PX)
    scale = Math.max(1, Math.sqrt(MAX_CANVAS_PX / px));
  const c = document.createElement('canvas');
  c.width = Math.round(img.naturalWidth * scale);
  c.height = Math.round(img.naturalHeight * scale);
  const ctx = c.getContext('2d');
  ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high';
  ctx.drawImage(img, 0, 0, c.width, c.height);
  if (enhance) stretchContrast(c);
  return c.toDataURL('image/png');
}

/* 從辨識結果的行框量出中位數字高，用來判斷圖上的字是不是太小。
   取中位數而非平均，避免單行雜訊（例如把整塊背景誤判成一行）拉歪。 */
function medianLineHeight(data) {
  const hs = ((data && data.lines) || [])
    .filter(l => l.bbox && l.text && l.text.trim())
    .map(l => l.bbox.y1 - l.bbox.y0)
    .filter(h => h > 0)
    .sort((a, b) => a - b);
  return hs.length ? hs[Math.floor(hs.length / 2)] : 0;
}

/* OCR 會在中文字之間插入空白，會讓關鍵字比對失效，這裡還原。
   另外把全形英數轉半形 —— 後端是純子字串比對，「７天美白」比對不到「7天美白」。 */
const CJK = '\\u3000-\\u303f\\u4e00-\\u9fff\\uf900-\\ufaff\\uff00-\\uffef';
function toHalfWidth(s) {
  return s.replace(/[０-９Ａ-Ｚａ-ｚ]/g,
                   c => String.fromCharCode(c.charCodeAt(0) - 0xfee0));
}

/* 規避手法與 OCR 雜訊的正規化。
   食藥署115年食品廣告合規輔導指引已明文把「錯別字、諧音」列為可裁處態樣，
   業者也確實會插入零寬字元把「治療」拆成「治<U+200B>療」來閃避字串比對。

   這裡只收「在正常廣告文案中幾乎不可能出現」的字元，不做形近字猜測——
   猜測會把合法的「使排便順暢」變成違規的「使小便順暢」，那是誣告。 */
const NOISE_MAP = {
  '丶': '、',   // 丶 OCR 常把頓號讀成這個
  '囗': '口',   // 囗 圍字框，實務上不會出現在廣告文案
  '､': '、',   // ｦ 半形頓號
  '‧': '‧', '·': '‧',   // 各種間隔號統一
};
function denoise(s) {
  return String(s || '')
    // 零寬字元／控制字元：純粹用來規避比對，一律移除
    .replace(/[​-‏‪-‮⁠-⁤﻿­]/g, '')
    .replace(/[丶囗､‧·]/g, c => NOISE_MAP[c] || c);
}
function tidyCJK(s) {
  return toHalfWidth(denoise(s))
    .replace(/\r/g, '')
    .replace(/[ \t\u00a0]+/g, ' ')
    .replace(new RegExp('([' + CJK + ']) (?=[' + CJK + '0-9A-Za-z])', 'g'), '$1')
    .replace(new RegExp('([0-9A-Za-z]) (?=[' + CJK + '])', 'g'), '$1')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

function getTessWorker() {
  if (!tessWorkerP) {
    tessWorkerP = (async () => {
      if (!window.Tesseract) await loadScript(TESS_CDN);
      return await Tesseract.createWorker('chi_tra', 1, {
        logger: m => { if (tessProgress) tessProgress(m); }
      });
    })().catch(e => { tessWorkerP = null; throw e; });
  }
  return tessWorkerP;
}

/* 已經有一輪 OCR 在跑時，回傳「同一個」進行中的 promise 讓呼叫端等它完成。
   舊寫法直接 return，導致：上傳時自動啟動的 OCR 還在跑，使用者就按了分析，
   analyzeFree 的 await 立刻返回、文字框還是空的 → 誤報「沒有辨識出文字」。 */
let ocrPromise = null;
function runOCR(auto, enhance) {
  if (!rawDataUrl) return Promise.resolve();
  if (ocrBusy && ocrPromise) return ocrPromise;
  ocrBusy = true;
  ocrPromise = doOCR(auto, enhance).finally(() => { ocrBusy = false; ocrPromise = null; });
  return ocrPromise;
}

/* tesseract 偶爾會對同一塊區域吐出兩個互相競爭的行假設：一個正確、一個完全
   憑空，而 data.text 會把兩個都印出來。實測「合法2_食品_穀物飲」在標題那一帶
   就多出一行 conf=0 的「3繼下台夫愧全」，跟 conf=91 的「台灣黑豆穀物飲」
   bbox 100% 重疊；「R1_關捷挺固立」也有一行 conf=0 的「Le朵」壓在 conf=95 的
   「關節保健膠囊」上。

   只用信心值當門檻會出事 —— 實測有一批真實內容的信心也很低：
   「SPF50+PA++++」只有 7、「延年益壽、青春永凡」只有 18、「苦瓜勝采複方膠囊」
   只有 12。那些砍掉就會漏抓違規，比多一行亂碼嚴重得多。

   真正的判別訊號是「重疊」：幻覺行必定壓在另一個信心高很多的行上面，
   而低信心的真實行都是獨立存在的。用 bbox 交集而不是只看 y 範圍，
   否則雙欄排版會把其中一欄誤殺。

   實測 15 張測試圖共 88 行，這條規則剛好只丟掉那 2 行幻覺，其餘一行未動；
   交集門檻 0.4~0.7、信心差 30~60 的每一組參數結果都相同，邊界很寬。 */
const PHANTOM_MIN_OVERLAP = 0.6;   // bbox 交集要佔較小那個框多少比例
const PHANTOM_MIN_GAP     = 40;    // 壓制者的信心要高出多少
const PHANTOM_MAX_CONF    = 60;    // 只有本身信心夠低的才可能被丟
/* 兩行都讀爛時（信心相當、都很低），信心差判不出誰是幻覺。這時改看範圍：
   幻覺是同一塊區域的「子假設」，框一定比真的那行小而且被包在裡面。
   實測 R6：conf 0 的「可寺咆合」(3850 px²) 完全落在同樣 conf 0 的
   「黑豆玥物飲」(11250 px²) 裡面，面積比 2.92。 */
const PHANTOM_TIE_CONF    = 20;    // 信心差在這個範圍內才算「相當」
const PHANTOM_AREA_RATIO  = 2;     // 對方框要大這麼多倍才判它是本尊

function bboxArea(b) {
  return Math.max(0, b.x1 - b.x0) * Math.max(0, b.y1 - b.y0);
}

function bboxOverlap(a, b) {
  const w = Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0);
  const h = Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0);
  if (w <= 0 || h <= 0) return 0;
  const smaller = Math.min((a.x1 - a.x0) * (a.y1 - a.y0), (b.x1 - b.x0) * (b.y1 - b.y0));
  return smaller > 0 ? (w * h) / smaller : 0;
}

/* 回傳去掉幻覺行之後的文字。拿不到逐行資料時原樣回傳，不要因此少讀到東西。 */
function textWithoutPhantomLines(data) {
  const lines = (data && data.lines) || [];
  if (lines.length < 2) return (data && data.text) || '';
  const keep = lines.filter(l => {
    if (!l.bbox || l.confidence >= PHANTOM_MAX_CONF) return true;
    return !lines.some(o => {
      if (o === l || !o.bbox) return false;
      if (bboxOverlap(l.bbox, o.bbox) < PHANTOM_MIN_OVERLAP) return false;
      if (o.confidence - l.confidence >= PHANTOM_MIN_GAP) return true;
      // 信心分不出高下時看範圍。差距中等（20~40）就兩個都留著，寧可多一行亂碼
      if (Math.abs(o.confidence - l.confidence) > PHANTOM_TIE_CONF) return false;
      return bboxArea(o.bbox) >= bboxArea(l.bbox) * PHANTOM_AREA_RATIO;
    });
  });
  if (keep.length === lines.length) return data.text || '';
  return keep.map(l => (l.text || '').replace(/\s+$/, '')).join('\n');
}

/* ============ 框選辨識 ============
   整張圖一起讀，常常會把不相干的區塊（頁尾、浮水印、旁邊的留言）也讀進來；
   密集的資訊圖表更是整片糊掉（R9 那張整體信心只有 44）。
   用左鍵在預覽圖上拖出一塊，就只辨識那一塊 —— 而且裁切後可以單獨放大到
   tesseract 對 CJK 的舒適區，準確度通常比整張讀好很多。
   同一張圖可以重複框選，每次的結果各自成一行接在「廣告文字」後面。 */
let selStart = null, selBusy = false;

function selPointOf(e) {
  const r = $('preview').getBoundingClientRect();
  return { x: Math.min(Math.max(e.clientX - r.left, 0), r.width),
           y: Math.min(Math.max(e.clientY - r.top, 0), r.height),
           dw: r.width, dh: r.height };
}
function selDraw(a, b) {
  const box = $('selBox');
  const x = Math.min(a.x, b.x), y = Math.min(a.y, b.y);
  const w = Math.abs(a.x - b.x), h = Math.abs(a.y - b.y);
  box.style.left = x + 'px'; box.style.top = y + 'px';
  box.style.width = w + 'px'; box.style.height = h + 'px';
  box.classList.remove('hidden');
  return { x: x, y: y, w: w, h: h, dw: a.dw, dh: a.dh };
}

function initRegionPicker() {
  const wrap = $('previewWrap');
  if (!wrap) return;
  wrap.addEventListener('dragstart', e => e.preventDefault());   // 別觸發原生圖片拖曳
  wrap.addEventListener('pointerdown', e => {
    if (e.button !== 0 || !rawDataUrl || selBusy) return;         // 只收滑鼠左鍵
    e.preventDefault();
    selStart = selPointOf(e);
    wrap.classList.add('picking');
    try { wrap.setPointerCapture(e.pointerId); } catch (_) {}
  });
  wrap.addEventListener('pointermove', e => {
    if (selStart) selDraw(selStart, selPointOf(e));
  });
  const finish = e => {
    if (!selStart) return;
    const start = selStart;
    selStart = null;
    wrap.classList.remove('picking');
    try { wrap.releasePointerCapture(e.pointerId); } catch (_) {}
    const r = selDraw(start, selPointOf(e));
    $('selBox').classList.add('hidden');
    // 太小的多半是誤觸或想點一下，不是要框選
    if (r.w < 16 || r.h < 12) return;
    ocrRegion(r);
  };
  wrap.addEventListener('pointerup', finish);
  wrap.addEventListener('pointercancel', () => {
    selStart = null; wrap.classList.remove('picking'); $('selBox').classList.add('hidden');
  });
}

async function ocrRegion(r) {
  if (selBusy) return;
  selBusy = true;
  const myToken = runToken;
  try {
    ocrMsg('辨識框選區域…', true);
    const img = await loadImg(rawDataUrl);
    // 顯示座標 → 原圖座標
    const fx = img.naturalWidth / r.dw, fy = img.naturalHeight / r.dh;
    const cx = Math.round(r.x * fx), cy = Math.round(r.y * fy);
    const cw = Math.round(r.w * fx), ch = Math.round(r.h * fy);
    if (cw < 4 || ch < 4) { ocrMsg('框選範圍太小，請框大一點。'); return; }
    // 小塊放大到約 900px 寬，但受總像素上限約束（大圖放大會把分頁吃爆）
    let scale = Math.max(1, Math.min(4, Math.round(900 / cw)));
    scale = Math.max(1, Math.min(scale, Math.sqrt(12e6 / (cw * ch))));
    const c = document.createElement('canvas');
    c.width = Math.round(cw * scale); c.height = Math.round(ch * scale);
    const g = c.getContext('2d');
    g.imageSmoothingQuality = 'high';
    g.drawImage(img, cx, cy, cw, ch, 0, 0, c.width, c.height);
    const url = c.toDataURL('image/png');
    c.width = c.height = 0;                       // 及早釋放，別留著上億像素的 canvas

    const worker = await getTessWorker();
    tessProgress = m => {
      if (m.status === 'recognizing text')
        ocrMsg('辨識框選區域… ' + Math.round((m.progress || 0) * 100) + '%', true);
    };
    const { data } = await worker.recognize(url);
    tessProgress = null;
    if (myToken !== runToken) return;             // 辨識途中換過圖，結果作廢
    const got = tidyCJK(textWithoutPhantomLines(data));
    if (!got) {
      ocrMsg('這一塊沒有辨識到文字 — 框大一點，或改框字比較清楚的地方。');
      return;
    }
    const added = appendAdText(got);
    ocrMsg((added ? '✅ 框選區域辨識出 ' + charCount(got) + ' 個字，已接在「廣告文字」後面'
                  : '這一塊的文字剛才已經加過了，沒有重複加入')
         + '（辨識信心 ' + Math.round(data.confidence) + '）。可以繼續框下一塊，'
         + '框完按「開始快篩分析」。');
  } catch (e) {
    tessProgress = null;
    ocrMsg('框選辨識失敗：' + e.message);
  } finally {
    selBusy = false;
  }
}

/* 每次框選的結果各自成一行接在後面。重複框到同一塊就不重覆加。 */
function appendAdText(text) {
  const ta = $('adText');
  const cur = ta.value.replace(/[ \t\n]+$/, '');
  const t = text.trim();
  if (!t) return false;
  if (cur && cur.split('\n').some(l => l.trim() === t)) return false;
  ta.value = cur ? cur + '\n' + t : t;
  lastOcrText = ta.value;
  // 框選是使用者主動挑的，背景補讀不要把它蓋掉
  textIsMachine = false;
  return true;
}

async function doOCR(auto, enhance) {
  const myToken = runToken;
  const ta = $('adText');
  try {
    ocrMsg('讀取圖片…', true);
    const img = await loadImg(rawDataUrl);
    const longSide = Math.max(img.naturalWidth, img.naturalHeight);
    const shrink = longSide > MAX_SIDE ? MAX_SIDE / longSide : 1;
    const first = (enhance || shrink !== 1) ? prepare(img, shrink, enhance) : rawDataUrl;

    ocrMsg('載入中文辨識模型…（第一次約需下載 6 MB，之後瀏覽器會自動快取）', true);
    tessProgress = m => {
      if (m.status === 'recognizing text') ocrMsg('辨識文字中… ' + Math.round((m.progress || 0) * 100) + '%', true);
      else if (m.status) ocrMsg(m.status + '…', true);
    };
    const worker = await getTessWorker();
    const pass1 = await worker.recognize(first);
    lastOcrConfidence = pass1.data.confidence;   // 引擎自評的辨識信心（0~100）
    let text = tidyCJK(textWithoutPhantomLines(pass1.data));

    // 依實際量到的字高決定要不要放大。真實廣告截圖的字往往只有 10~15px，
    // tesseract 對 CJK 的舒適區約 34px，差距大就整數倍放大重讀一次。
    const lh = medianLineHeight(pass1.data);
    const scale = lh > 0 ? Math.min(3, Math.max(1, Math.round(34 / lh))) : 1;
    if (scale > 1) {
      ocrMsg('圖上的字偏小（約 ' + lh + 'px），放大 ' + scale + ' 倍重新辨識…', true);
      const t2 = tidyCJK(textWithoutPhantomLines(
        (await worker.recognize(prepare(img, scale, enhance))).data));
      // 放大版通常較準；只有在明顯讀更少時才退回原尺寸的結果
      if (charCount(t2) >= charCount(text) * 0.5) text = t2;
    }
    tessProgress = null;
    if (!text) {
      ocrMsg('⚠ 沒有辨識到文字 — 請把廣告文案手動貼到下方欄位（或用 Win + Shift + S 截圖後，在「剪取工具」按「文字動作」直接複製圖上的字）。');
      return;
    }
    // L2：這一輪如果已經過期（換過圖），或使用者中途自己改了字，就不要寫回去
    if (myToken !== runToken) return;
    if (!textIsMachine && ta.value.trim()) {
      ocrMsg('（辨識完成，但你已手動修改文字，保留你的版本不覆蓋）');
      return;
    }
    const cur = ta.value.trim();
    let note = '';
    if (!cur) {
      ta.value = text;
    } else if (auto) {
      ta.value = text;                                   // 自動重跑：換掉上一次的辨識結果
    } else if (cur.indexOf(text) < 0) {
      ta.value = cur + '\n' + text;                      // 手動補一次：兩個引擎的結果併起來
      note = '（已附加在原本的文字後面，重複的詞不會重複計算）';
    }
    lastOcrText = text;
    textIsMachine = true;
    ocrMsg('✅ 瀏覽器 OCR 辨識出 ' + charCount(text) + ' 個字' + note
         + ' — 請確認下方文字是否正確，可自行修正後再按「開始快篩分析」。');
    // 字實在太小時，放大也救不回來，直接告訴使用者怎麼拿到更好的來源圖
    if (lh > 0 && lh < 13) {
      notify('noticeStep1', '這張圖上的字只有約 ' + lh + 'px 高，已自動放大 ' + scale
           + ' 倍辨識，但仍可能有不少錯字。\n'
           + '想要更準的話：改用廣告的原圖（不要截圖再截圖）、'
           + '截圖前先把網頁放大、或只截取有文字的區域。\n'
           + '也可以用 Win + Shift + S 截圖後，在「剪取工具」按「文字動作」直接複製文字貼上。',
             'warn', 15000);
    }
  } catch (e) {
    tessProgress = null;
    ocrMsg('⚠ 圖片辨識失敗：' + e.message + ' — 請把廣告文案手動貼到下方欄位。');
  }
}
$('ocrBtn').onclick = async () => {
  const btn = $('ocrBtn');
  clearNotice('noticeStep1');
  setBusy(btn, '辨識中…');
  setBusy($('analyzeBtn'), '請稍候…');
  try {
    await runOCR(false, true);   // 第二讀改用對比拉伸，補出來的才有意義
  } finally {
    setBusy(btn, null);
    setBusy($('analyzeBtn'), null);
  }
};

/* ============ 免費 AI 分析（Google Gemini 免費額度） ============ */
function geminiPrompt() {
  const lawList = Object.keys(LAWS).map(id =>
    '- ' + id + '：《' + LAWS[id].law_name + '》' + LAWS[id].article + ' — ' + LAWS[id].summary).join('\n');
  return '你是台灣食品藥物管理法規的稽查專員。請檢視這張廣告截圖，找出違反下列法規的宣傳字句。\n\n'
    + '可引用的法條：\n' + lawList + '\n\n'
    + '請只輸出 JSON（不要加任何說明文字或 markdown 標記），格式如下：\n'
    + '{\n'
    + '  "product_name": "廣告中的產品名稱，看不出來就填「未標示」",\n'
    + '  "product_type": "食品／健康食品／化粧品／藥品／醫療器材／其他／無法判定 擇一",\n'
    + '  "ad_text": "圖片中所有可見的廣告文字，逐字抄錄",\n'
    + '  "risk_level": "高／中／低／無明顯違規 擇一",\n'
    + '  "overall_assessment": "2-3 句整體說明",\n'
    + '  "violations": [\n'
    + '    {\n'
    + '      "quote": "廣告中的原句，務必逐字引用不要改寫",\n'
    + '      "violation_type": "誇大不實 或 宣稱醫療效能 擇一",\n'
    + '      "reason": "為什麼違規，一到兩句",\n'
    + '      "law_id": "上面清單中的其中一個 id",\n'
    + '      "confidence": "高／中／低 擇一"\n'
    + '    }\n'
    + '  ]\n'
    + '}\n\n'
    + '判斷原則：\n'
    + '1. 只列出廣告中真實出現的字句，絕對不要杜撰。\n'
    + '2. 暗示性用語（如「告別藥罐子」「不必再吃藥」「醫美級」）也要列入。\n'
    + '3. 依產品類別挑選正確法條：食品用 fsa-*、健康食品用 hf-*、化粧品用 cos-*；非藥物卻宣稱療效可另引 pha-69。\n'
    + '4. 若完全沒有違規，violations 給空陣列、risk_level 填「無明顯違規」。\n\n'
    + '使用者補充的廣告文字（可能為空）：\n' + ($('adText').value.trim() || '（無）');
}

async function analyzeWithGemini() {
  const key = gKeyGet();
  const body = {
    contents: [{ role: 'user', parts: [
      { text: geminiPrompt() },
      { inline_data: { mime_type: mediaType || 'image/png', data: imageB64 } }
    ]}],
    generationConfig: { temperature: 0, responseMimeType: 'application/json' }
  };
  let lastErr = null;
  for (const model of GEMINI_MODELS) {
    let r, j;
    try {
      r = await fetch('https://generativelanguage.googleapis.com/v1beta/models/' + model +
                      ':generateContent?key=' + encodeURIComponent(key),
                      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      j = await r.json();
    } catch (e) {
      throw new Error('無法連線 Google API（請確認網路連線）：' + e.message);
    }
    if (!r.ok) {
      const msg = (j && j.error && j.error.message) || ('HTTP ' + r.status);
      lastErr = new Error(msg);
      if (r.status === 404 || /not found|not supported|unsupported/i.test(msg)) continue;   // 換下一個模型再試
      if (r.status === 400 && /API key/i.test(msg)) throw new Error('Gemini 金鑰無效，請到上方「進階設定」重新貼一次。');
      if (r.status === 429) throw new Error('已超過 Gemini 免費額度上限，請稍後再試，或清除金鑰改用免費 OCR 模式。');
      throw lastErr;
    }
    const cand = (j.candidates && j.candidates[0]) || {};
    const parts = (cand.content && cand.content.parts) || [];
    const raw = parts.map(p => p.text || '').join('')
                     .replace(/^```(?:json)?\s*/i, '').replace(/```\s*$/, '').trim();
    if (!raw) { lastErr = new Error('AI 沒有回傳內容'); continue; }
    return normalizeAI(JSON.parse(raw), model);
  }
  throw new Error('免費 AI 分析失敗：' + (lastErr ? lastErr.message : '未知錯誤'));
}

function normalizeAI(d, model) {
  const vios = (d.violations || []).map(v => {
    const law = LAWS[v.law_id] || LAWS['fsa-28-1'];
    return {
      quote: v.quote || '',
      reason: v.reason || '',
      violation_type: v.violation_type === '誇大不實' ? '誇大不實' : '宣稱醫療效能',
      confidence: v.confidence || '中',
      law: Object.assign({ id: v.law_id }, law)
    };
  });
  if (d.ad_text && !$('adText').value.trim()) $('adText').value = d.ad_text;
  return {
    mode: 'gemini',
    product_name: d.product_name || '未標示',
    product_type: d.product_type || '無法判定',
    risk_level: d.risk_level || (vios.length ? '中' : '無明顯違規'),
    overall_assessment: (d.overall_assessment || '') + '（本結果由 Google Gemini 免費額度分析，模型：' + model + '）',
    violations: vios
  };
}

/* ============ 開始分析 ============ */
async function runAnalysis() {
  const btn = $('analyzeBtn'), ta = $('adText');
  clearNotice('noticeStep1');
  if (!imageB64 && !ta.value.trim()) {
    notify('noticeStep1', '還沒有東西可以分析。\n'
         + '請先上傳廣告截圖（或按 Ctrl + V 貼上），也可以直接把廣告文字貼到下方欄位。', 'warn');
    return;
  }
  setBusy(btn, '分析中…');
  setBusy($('ocrBtn'), '請稍候…');
  showSpinner('準備分析…', '');
  analyzing = true;
  const myToken = runToken, myImage = imageB64;
  try {
    if (!aiEnabled && gKeyGet() && imageB64) {
      showSpinner('AI 分析中…', '正在把圖片送給 Google Gemini 判讀，約需 10～30 秒');
      analysis = await analyzeWithGemini();
    } else if (aiEnabled) {
      showSpinner('AI 分析中…', '正在把圖片送給 Claude 判讀，約需 10～60 秒，請勿關閉視窗');
      analysis = await postAnalyze(imageB64, mediaType, ta.value);
    } else {
      analysis = await analyzeFree(ta);
    }
    if (myToken !== runToken || myImage !== imageB64) {   // L4：分析途中換過圖，結果作廢
      notify('noticeStep1', '圖片已更換，剛才那次分析的結果已捨棄，請重新分析。', 'warn', 6000);
      return;
    }
    renderResult(analysis);
    crossCheckWithBrowserOCR();      // 不 await：先讓使用者看到結果
  } catch (e) {
    notify('noticeStep1', e.message, 'err');
  } finally {
    analyzing = false;
    setBusy(btn, null);
    setBusy($('ocrBtn'), null);
    showSpinner(false);
  }
}
$('analyzeBtn').onclick = runAnalysis;

let _bgToken = 0;
function myTokenStale() { return _bgToken !== runToken; }

/* 低於此信心值就提醒使用者辨識結果不可靠。
   實測 tesseract 自評：清晰廣告圖 83~86、低解析小字 61、密集資訊圖表 44。
   （先前用「多趟結果的字元集合重疊」當訊號，實測分不出來——
     亂碼裡也有大量常用字，清晰圖 0.95 對亂碼圖 0.86，門檻無從設起。） */
const UNSTABLE_OCR_CONF = 70;

/* 這一行有沒有帶來目前還沒看到的違規關鍵字。
   關鍵字表在 KEYWORD_EVIDENCE.map，前端本來就有整份。 */
function newKeywordsIn(line, seenText) {
  const map = (KEYWORD_EVIDENCE && KEYWORD_EVIDENCE.map) || {};
  for (const kw in map) {
    if (kw.length >= 2 && line.indexOf(kw) >= 0 && seenText.indexOf(kw) < 0) return true;
  }
  return false;
}

/* 把補讀的結果併進主要文字。
   只併「帶來新關鍵字」的行——多趟補讀的目的就是補抓漏掉的違規詞，
   沒帶來新詞的行對使用者只是雜訊。密集圖表每趟的誤認方式都不同，
   全部併起來會塞進數十行亂碼，反而讓人無法核對 OCR 結果。 */
function mergeOcrText(base, extra) {
  let out = String(base || '').trim();
  const added = [];
  String(extra || '').split('\n').forEach(raw => {
    const line = raw.trim();
    if (line.replace(/\s/g, '').length < 2) return;
    if (out.indexOf(line) >= 0) return;
    if (!newKeywordsIn(line, out + '\n' + added.join('\n'))) return;
    added.push(line);
  });
  return added.length ? (out + '\n' + added.join('\n')) : out;
}

/* 用不同前處理再讓 Windows OCR 讀一次。
   實測：小圖放大能把 0 項變 2 項；大圖盲目放大反而更差，但加對比可以救回被吃掉的字。
   沒有單一組合全贏，所以跑多趟取聯集——合法圖在所有變體下都是 0 項，不會製造誤判。 */
let lastOcrConfidence = null;   // 瀏覽器 OCR 上一次的信心值
async function serverOcrVariants(baseText) {
  if (!rawDataUrl || standalone) return baseText;
  const img = await loadImg(rawDataUrl);
  const small = Math.min(img.naturalWidth, img.naturalHeight) < 700;
  const passes = small ? [[2, false], [2, true]] : [[2, true]];
  let merged = baseText;
  for (const [scale, enhance] of passes) {
    if (myTokenStale()) return merged;
    try {
      const dataUrl = prepare(img, scale, enhance);
      const d = await postAnalyze(dataUrl.split(',')[1], 'image/png', '');
      const got = tidyCJK(d.ad_text || '');
      if (charCount(got) >= 4) merged = mergeOcrText(merged, got);
    } catch (e) { /* 單一變體失敗不影響其他趟 */ }
  }
  return merged;
}

/* 純瀏覽器模式的多趟補讀。
   exe 模式靠 serverOcrVariants 用 Windows OCR 對不同前處理各讀一趟；線上版
   沒有那條路，這裡用同一套前處理讓 tesseract 再讀，補回第一趟漏掉的字。

   實測 17 張圖：六張合成測試圖原圖就讀滿了，多跑兩趟一個關鍵字都沒多；
   但使用者實際丟進來的真實廣告截圖有兩張是 0 → 1
   （「不易形成體脂肪」靠 2 倍放大讀到、「漢方」靠對比拉伸讀到）。
   真實廣告版面雜、對比差、字疊在照片上，正是需要補讀的那一群。
   代價是每張多約 1.5 秒（大圖到 4.5 秒），所以放在背景、出結果之後才跑。 */
async function browserOcrVariants(baseText) {
  if (!rawDataUrl) return baseText;
  const img = await loadImg(rawDataUrl);
  const small = Math.min(img.naturalWidth, img.naturalHeight) < 700;
  const passes = small ? [[2, false], [2, true]] : [[2, true]];
  let merged = baseText;
  const worker = await getTessWorker();
  for (let i = 0; i < passes.length; i++) {
    if (myTokenStale()) return merged;
    const scale = passes[i][0], enhance = passes[i][1];
    try {
      ocrMsg('背景補讀中：換一種影像處理再辨識（' + (i + 1) + '/' + passes.length + '）…', true);
      const d = await worker.recognize(prepare(img, scale, enhance));
      if (myTokenStale()) return merged;
      const got = tidyCJK(textWithoutPhantomLines(d.data));
      if (charCount(got) >= 4) merged = mergeOcrText(merged, got);
    } catch (e) { /* 單一變體失敗不影響其他趟 */ }
  }
  return merged;
}

/* 分析完成後，背景再用瀏覽器 OCR 讀一次做交叉比對。
   Windows OCR 有時會把關鍵字吃掉（例如「改善心血管疾病」讀成「改」），
   兩套引擎互補可以把漏掉的違規補回來。 */
async function crossCheckWithBrowserOCR() {
  if (aiEnabled || gKeyGet()) return;          // AI 模式直接看圖，不需要
  if (!rawDataUrl) return;                     // 純文字輸入沒有圖可以補讀
  if (!standalone && serverOcr !== true) return;  // exe 模式：只有走過 Windows OCR 才需要補
  const ta = $('adText');
  if (!textIsMachine) return;                  // 使用者已經自己改過字，不要動
  const myToken = runToken;
  _bgToken = runToken;
  const beforeText = ta.value.trim();
  const before = (analysis && analysis.violations || []).length;
  // 補讀途中會把狀態列改成「背景補讀中…」，跑完要還原，否則轉圈會一直留著
  const ocrBarBefore = $('ocrStatus').innerHTML;
  let touchedBar = false;

  try {
    if (standalone) {
      // 線上版只有 tesseract 一套引擎，沒有「換另一套引擎」可比對，
      // 改用不同前處理多讀幾趟來補。
      touchedBar = true;
      const widened = await browserOcrVariants(ta.value);
      if (myToken !== runToken || !textIsMachine) return;
      if (widened !== ta.value) { ta.value = widened; lastOcrText = widened; }
    } else {
      // 先用不同前處理讓 Windows OCR 再讀幾趟——比下載瀏覽器辨識模型快得多
      touchedBar = true;
      ocrMsg('背景補讀中：調整圖片後再辨識一次…', true);
      const widened = await serverOcrVariants(ta.value);
      if (myToken !== runToken || !textIsMachine) return;
      if (widened !== ta.value) { ta.value = widened; lastOcrText = widened; }

      ocrMsg('背景交叉比對中：用瀏覽器 OCR 再讀一次，避免漏字…', true);
      await runOCR(false);
      if (myToken !== runToken || !textIsMachine) return;   // 換過圖、或使用者中途改了字
    }
    if (ta.value.trim() === beforeText) return;           // 沒有補到新文字
    const data = await postAnalyze(null, null, ta.value);
    if (myToken !== runToken) return;
    const after = (data.violations || []).length;
    if (after > before) {
      analysis = data;
      renderResult(data, { noScroll: true, keepType: true });
      // L3：信已經生成了就一起更新，不要讓畫面與產出物不一致
      const letterShown = !$('previewCard').classList.contains('hidden');
      if (letterShown) buildLetter();
      notify('noticeStep1', '交叉比對完成：又補抓到 ' + (after - before)
           + ' 項違規（合計 ' + after + ' 項），上方結果已更新'
           + (letterShown ? '，下方陳情信也已重新生成。' : '。'), 'ok', 9000);
    }
  } catch (e) {
    ocrMsg('（背景補讀未完成：' + e.message + '，不影響上方結果）');
    touchedBar = false;
  } finally {
    // 不論從哪一條路徑離開，都不能讓「背景補讀中…」的轉圈留在畫面上。
    // 這個函式有多處提早 return（換過圖、使用者改了字、沒補到新文字），
    // 以前那些路徑都會把 spinner 留著轉，看起來像卡住。
    if (touchedBar && myToken === runToken) $('ocrStatus').innerHTML = ocrBarBefore;
    // 辨識本身不可靠時一定要講。以前這段寫在函式尾端，而 standalone 在第一行
    // 就 return 了——線上版（唯一 100% 靠瀏覽器 OCR 的那一版）反而永遠看不到。
    if (myToken === runToken && lastOcrConfidence !== null
        && lastOcrConfidence < UNSTABLE_OCR_CONF) {
      notify('noticeStep1',
        '這張圖的文字辨識不可靠（辨識信心 ' + Math.round(lastOcrConfidence) + '%，'
        + '一般清晰的廣告圖在 80% 以上）。圖上的字太小或太密，'
        + '下方「廣告文字」很可能有大量錯字。\n'
        + '建議：用滑鼠左鍵在預覽圖上框選要看的那一塊單獨辨識，通常準得多；'
        + '或改用解析度較高的原圖；或直接把廣告文案貼到「廣告文字」欄位。\n'
        + '★ 陳情信會引述這段文字當作違規事證，請務必核對後再送件。',
        'warn');
    }
  }
}

function postAnalyze(img, mime, text) {
  if (standalone) {                        // 純瀏覽器模式：不打後端，本地比對
    try { return Promise.resolve(analyzeLocal(text || '')); }
    catch (e) { return Promise.reject(e); }
  }
  return fetch('/api/analyze', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ image_base64: img || null, media_type: img ? mime : null, text: text || '' })
  }).then(async res => {
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || ('HTTP ' + res.status));
    return data;
  });
}

/* 免費模式：先讓 exe 用 Windows 內建 OCR 讀圖；讀不到或不支援才改用瀏覽器 OCR。
   注意：文字框裡已經有字就直接拿去分析，不再重跑 OCR —— 否則會蓋掉使用者的修正。 */
async function analyzeFree(ta) {
  if (imageB64 && !ta.value.trim() && serverOcr !== false) {
    showSpinner('步驟 1／2　讀取圖片上的文字…', 'Windows 內建 OCR 處理中，通常 1～2 秒');
    try {
      const data = await postAnalyze(imageB64, mediaType, ta.value);
      serverOcr = true;
      const got = tidyCJK(data.ad_text);
      if (charCount(got) >= 10) {
        ta.value = got; lastOcrText = got; textIsMachine = true;   // L1：主引擎路徑也要標記
        ocrMsg('✅ 已由 Windows 內建 OCR 辨識出 ' + charCount(got) + ' 個字 — 請確認下方文字，'
             + '有錯可直接修正後重新分析；覺得漏字可按右邊按鈕用瀏覽器 OCR 再補一次。');
        return data;
      }
      ocrMsg('Windows OCR 幾乎沒讀到字，改用瀏覽器 OCR 再試…', true);   // 換引擎重試
    } catch (e) {
      serverOcr = false;   // 這支 exe 不支援圖片（舊版），或 ocr.ps1 被擋下
      ocrMsg('Windows OCR 無法使用（' + e.message + '），改用瀏覽器 OCR…', true);
    }
  }

  if (imageB64 && !ta.value.trim()) {
    showSpinner('步驟 1／2　讀取圖片上的文字…',
                '改用瀏覽器 OCR；第一次使用需下載中文辨識模型約 9 MB，之後會快取');
    await runOCR(true);
  }
  if (!ta.value.trim()) {
    throw new Error('圖片沒有辨識出文字，無法分析。\n\n'
      + '請把廣告文案手動貼到「廣告文字」欄位後再按一次分析。\n'
      + '（小技巧：用 Win + Shift + S 截圖後，在「剪取工具」視窗按「文字動作」，可直接複製圖片上的文字。）');
  }
  showSpinner('步驟 2／2　比對違規關鍵字…', '對照 regulations.json 的法規資料庫，馬上就好');
  return postAnalyze(null, null, ta.value);
}

function showSpinner(text, sub) {
  $('spinner').style.display = text ? 'block' : 'none';
  if (text) {
    $('spinnerText').textContent = text;
    $('spinnerSub').textContent = sub || '';
  }
}

/* L11：後端不論命中 1 項還是 30 項都回「中」，分不出輕重。
   免費模式改由前端依「有無醫療效能項 + 項數」重算。 */
function calcRisk(vios) {
  if (!vios.length) return '無明顯違規';
  const med = vios.filter(v => v.violation_type !== '誇大不實').length;
  if (med > 0 || vios.length >= 5) return '高';
  if (vios.length >= 2) return '中';
  return '低';
}

/* L13：後端回的是與這則廣告無關的罐頭文字，改成真的在講這則廣告 */
function summarize(vios) {
  if (!vios.length) return '未比對到違規用語。仍建議人工檢視廣告整體表現，暗示性用語無法以關鍵字偵測。';
  const med = vios.filter(v => v.violation_type !== '誇大不實').length;
  const exa = vios.length - med;
  const parts = [];
  if (med) parts.push('宣稱醫療效能 ' + med + ' 項');
  if (exa) parts.push('誇大不實 ' + exa + ' 項');
  return '共比對到 ' + vios.length + ' 項疑似違規用語（' + parts.join('、') + '）。'
       + '本結果為關鍵字比對之初篩，請逐項人工複核後再送件。';
}

/* ============ 健康食品許可證比對 ============
   領有衛福部健康食品許可證（健字號）者，得在核准範圍內合法標示該項保健功效
   ——「調節血脂」「護肝」這類詞對持證產品不是違規，對沒證的產品才是。
   在有這份快照之前，工具只能把這 13 項法定保健功效一律標成「疑似・待認定」
   （測試資料 R7 就是為此列的已知限制）。現在可以直接比對。

   兩件事刻意不做：
     1. 不判斷「宣稱有沒有逾越核准範圍」。那要語意比對，不是字串比對做得到的。
        面板改成把 TFDA 核准的宣稱原文原封不動列出來，讓人自己對照。
     2. 查無字號時不寫「未經核准」。快照是每週更新的靜態檔，且廣告本來就常常
        不印字號；措辭一律是「本快照查無此字號」並附上官方查詢連結。 */

/* 健字號寫法很多：衛部健食字第A00235號、衛署健食字第A00235號、衛部健食規字第000123號，
   OCR 還可能吃掉「衛部」或把空白插進去。抓得寬一點，比對鍵才嚴格。 */
const HF_NO_RE = /健\s*食\s*(規)?\s*字\s*第?\s*([A-Za-z])?\s*0*(\d{1,6})\s*號?/g;

function hfKey(isSpec, letter, digits) {
  return (isSpec ? '規' : '般') + '|' + (letter || '').toUpperCase() + String(parseInt(digits, 10));
}

/* 從廣告文字裡找出健字號，回傳 {rec, raw} 或 {raw} （查無）或 null（沒寫字號）。 */
/* 查證用的副本：把空白全部拿掉（換行保留，避免跨行把兩段數字接在一起）。
   OCR 很常把「衛部健食字第A00237號」讀成「衛 部 健 食 字 第 A 0 0 2 3 7 號」，
   而 tidyCJK 只處理中文之間的空白，數字之間的它不會動。 */
function hfNormalize(s) {
  return String(s || '').replace(/[^\S\n]+/g, '');
}

function findHealthFoodPermit(text) {
  if (typeof HEALTH_FOOD === 'undefined' || !HEALTH_FOOD || !HEALTH_FOOD.records) return null;
  const s = hfNormalize(text);
  HF_NO_RE.lastIndex = 0;
  let m;
  while ((m = HF_NO_RE.exec(s))) {
    const k = hfKey(m[1], m[2], m[3]);
    const rec = HEALTH_FOOD.records.find(r => r.k === k);
    if (rec) return { rec: rec, raw: m[0].replace(/\s+/g, '') };
    if (!m[2] && !m[1]) continue;                  // 純數字太容易誤抓，要有字母或「規」才算
    return { raw: m[0].replace(/\s+/g, '') };
  }
  return null;
}

/* 把「已取得許可、且在核准功效範圍內」的命中挑出來，不列為違規。
   只有證況是「核可」才放行——失效／註銷／廢止／併証都不算。 */
function splitByLicence(vios, hit) {
  if (!hit || !hit.rec || hit.rec.st !== '核可') return { keep: vios, licensed: [] };
  const eff = hit.rec.eff || [];
  const keep = [], licensed = [];
  vios.forEach(v => (eff.indexOf(v.quote) >= 0 ? licensed : keep).push(v));
  return { keep: keep, licensed: licensed };
}

const HF_QUERY_URL = 'https://consumer.fda.gov.tw/Food/InfoHealthFood.aspx?nodeID=162';

function renderHealthFoodCard(hit, licensed) {
  const box = $('hfCard');
  box.className = '';
  if (!hit) { box.className = 'hidden'; return; }
  const date = (HEALTH_FOOD && HEALTH_FOOD.date) || '';

  if (!hit.rec) {
    box.classList.add('miss');
    box.innerHTML = '<h4>⚠ 廣告寫了健字號，但本快照查不到</h4>'
      + '<dl><dt>廣告上的字號</dt><dd>' + esc(hit.raw) + '</dd></dl>'
      + '<div class="src">本工具內建的是 ' + esc(date) + ' 的 TFDA 快照（565 筆）。'
      + '查不到可能是字號有誤、OCR 讀錯、該證不在本快照涵蓋範圍，'
      + '<b>也可能是廣告冒用不存在的字號</b>。請至 '
      + '<a href="' + HF_QUERY_URL + '" target="_blank">食藥署健康食品查詢 ↗</a> 確認後再判斷，'
      + '陳情信不會逕自主張「未經核准」。</div>';
    return;
  }

  const r = hit.rec, ok = r.st === '核可';
  box.classList.add(ok ? '' : 'bad');
  let h = '<h4>' + (ok ? '✅ 查得健康食品許可證' : '⚠ 查得許可證，但證況為「' + esc(r.st) + '」') + '</h4>'
    + '<dl>'
    + '<dt>許可證字號</dt><dd>' + esc(r.no) + '</dd>'
    + '<dt>中文品名</dt><dd>' + esc(r.name) + '</dd>'
    + '<dt>申請商</dt><dd>' + esc(r.co) + '</dd>'
    + '<dt>核可日期</dt><dd>' + esc(r.date || '—') + '</dd>'
    + '<dt>證況</dt><dd>' + esc(r.st) + '</dd>'
    + '<dt>核准保健功效</dt><dd>' + esc((r.eff || []).join('、') || '—') + '</dd>'
    + '</dl>';
  if (r.claim) h += '<div class="claim"><b>TFDA 核准的保健功效宣稱原文：</b>\n' + esc(r.claim) + '</div>';
  if (r.warn)  h += '<div class="claim"><b>核准的警語：</b>\n' + esc(r.warn) + '</div>';

  if (!ok) {
    h += '<div class="src">⚠ 這張證的證況不是「核可」。以健康食品名義販售或標示保健功效，'
       + '須為領有有效許可證者（健康食品管理法第6條），這一點請一併請主管機關查核。</div>';
  } else if (licensed && licensed.length) {
    h += '<div class="src">已排除 ' + licensed.length + ' 項在核准範圍內的用語（'
       + licensed.map(v => '「' + esc(v.quote) + '」').join('、') + '）'
       + ' —— 持證產品得於許可範圍內標示這些保健功效，列進陳情信會被承辦人員剔除。</div>';
  }
  h += '<div class="src">資料來源：衛福部食藥署健康食品資料集（快照 ' + esc(date) + '，政府資料開放授權條款-第1版）。'
     + '<b>核准 ≠ 廣告全部合法</b>：宣稱逾越上列核准範圍、或涉及醫療效能，仍違反健康食品管理法第14條。'
     + '請自行比對上面的宣稱原文與廣告實際寫法。</div>';
  box.innerHTML = h;
}

function renderResult(d, opts) {
  opts = opts || {};
  const isDemo = !aiEnabled && d.mode !== 'gemini';
  $('rProduct').textContent = d.product_name;
  $('rType').textContent = d.product_type;
  const risk = $('rRisk');
  const list = $('vioList');
  list.innerHTML = '';
  const pType = currentType();
  const split = splitByScope(d.violations || [], pType);
  // 有健字號就查許可證，核准範圍內的保健功效不列為違規
  const hit = findHealthFoodPermit(d.ad_text || $('adText').value);
  const lic = splitByLicence(split.keep, hit);
  const shown = lic.keep;
  renderHealthFoodCard(hit, lic.licensed);
  const lvl = isDemo ? calcRisk(shown) : d.risk_level;
  risk.textContent = lvl; risk.className = 'risk ' + lvl;
  $('rSummary').textContent = isDemo ? summarize(shown) : d.overall_assessment;
  if (!shown.length)
    list.innerHTML = '<p style="color:var(--ok)">未偵測到明顯違規字句。</p>';
  d._shown = shown;                       // 陳情信要用同一份
  d._hf = hit;
  if (split.drop.length) {
    notify('noticeStep1', '已依產品類別「' + pType + '」排除 ' + split.drop.length + ' 項不適用的用語（'
         + split.drop.map(v => '「' + v.quote + '」').join('、') + '）。\n'
         + '這些詞出自另一類產品的法規認定基準，列進陳情信容易被承辦人員剔除。', 'ok', 12000);
  }
  shown.forEach((v, i) => {
    const law = lawFor(v, pType);
    const ev = evidenceOf(v.quote);
    const div = document.createElement('div');
    div.className = 'vio type-' + v.violation_type;
    div.innerHTML = `
      <div class="quote">${i+1}. 「${esc(v.quote)}」<span class="tag">${esc(v.violation_type)}</span></div>
      <div style="font-size:.88rem;margin-top:5px">${esc(reasonFor(v, pType))}</div>
      <div class="law">📖 <b>${esc(law.law_name||'')} ${esc(law.article||'')}</b>：${esc(law.summary||'')}<br>
        ⚖ ${esc(law.penalty||'')}　<a href="${esc(law.url||'#')}" target="_blank">全國法規資料庫原文 ↗</a></div>
      <div class="conf">${isDemo ? '比對方式：關鍵字命中'
                            : 'AI 信心程度：' + esc(v.confidence)}
        <span class="ev ev-${ev.level}" title="${esc(ev.source)}">${EV_LABEL[ev.level]}</span>
        ${ev.source ? '<span class="evsrc">' + esc(ev.source) + '</span>' : ''}</div>`;
    list.appendChild(div);
  });
  // 帶入陳情信欄位（已經有值就不覆蓋，避免蓋掉使用者填的內容）
  const known = d.product_name && !/無法辨識|無法判定|未標示/.test(d.product_name);
  const nameBox = $('fProduct'), typeSel = $('fType');
  if (nameBox && !nameBox.value.trim()) {
    nameBox.value = known ? d.product_name
                          : guessProductName(d.ad_text || $('adText').value);
    productIsMachine = !!nameBox.value;
  }
  if (typeSel && typeSel.options && !opts.keepType &&
      [].some.call(typeSel.options, o => o.value === d.product_type)) typeSel.value = d.product_type;

  preApprovalNotice(currentType());
  outOfScopeNotice($('adText').value);
  $('resultCard').classList.remove('hidden');
  $('letterCard').classList.remove('hidden');
  markStep(3);
  if (!opts.noScroll) $('resultCard').scrollIntoView({behavior:'smooth'});
}

/* 偵測廣告是否根本不屬本工具涵蓋的 6 部法規。
   寵物食品歸農業部依動物保護法（罰3萬~15萬）、電子煙歸菸害防制法——
   用本工具的信會引到食安法、寫錯罰則級距、還送錯機關。
   引錯法條比漏抓嚴重得多，所以偵測到就要明確擋下。 */
function outOfScopeHit(text) {
  const t = String(text || '');
  for (const name in OUT_OF_SCOPE) {
    if (name.charAt(0) === '_') continue;
    const c = OUT_OF_SCOPE[name];
    const hit = (c.indicators || []).filter(w => t.indexOf(w) >= 0);
    if (hit.length) return { name: name, cfg: c, words: hit };
  }
  return null;
}

function outOfScopeNotice(text) {
  const r = outOfScopeHit(text);
  if (!r) { clearNotice('noticeStep4'); return null; }
  notify('noticeStep4',
    '這則廣告出現「' + r.words.join('」「') + '」，可能屬於「' + r.name + '」。\n'
    + r.name + '不適用本工具引用的法條——應依《' + r.cfg.law + '》，'
    + '主管機關為' + r.cfg.authority + '，' + r.cfg.penalty + '。\n'
    + '請勿直接使用本工具產出的陳情信送件，否則會引到錯誤的法條與罰則級距。',
    'err');
  return r;
}

/* 藥品與醫療器材是事前核准制，最常見的違規是「未經核准擅自刊播」。
   那件事無法從廣告文字判斷，得查核准文號——使用者若以為篩過就沒問題，
   等於被工具誤導，所以選到這兩類時要把邊界講清楚。 */
function preApprovalNotice(pType) {
  const pa = PRE_APPROVAL[pType];
  if (!pa) { clearNotice('noticeStep3'); return; }
  notify('noticeStep3',
    pType + '廣告採事前核准制：依' + pa.law + '，' + pa.requirement + '。\n'
    + '也就是說，這類廣告最常見的違規是「未經核准就刊播」——'
    + '本工具只比對廣告文字，看不出有沒有核准文號。\n'
    + '請自行確認廣告上是否載明核准文號；陳情信已代為請主管機關一併查明。',
    'warn');
}

/* 換產品類別要即時換掉引用的法條 */
$('fType').onchange = () => {
  preApprovalNotice($('fType').value);
  if (analysis) renderResult(analysis, { noScroll: true, keepType: true });
};

/* ============ 陳情信 ============ */
/* L14：把命中的關鍵字按「廣告原句」聚合。
   陳情書的違規事實單位應該是廣告中的一句話，不是資料庫裡的一個詞——
   承辦人員看到「廣告宣稱『化瘀』」得自己回原圖找上下文才看得懂。 */
function groupBySentence(vios, adText) {
  const lines = String(adText || '')
    .split(/[\n。！!？?；;]/).map(s => s.trim()).filter(s => s.length > 1);
  const groups = [];
  const orphan = [];
  vios.forEach(v => {
    const line = lines.find(l => l.indexOf(v.quote) >= 0);
    if (!line) { orphan.push(v); return; }
    let g = groups.find(x => x.line === line);
    if (!g) { g = { line: line, vios: [] }; groups.push(g); }
    g.vios.push(v);
  });
  orphan.forEach(v => groups.push({ line: v.quote, vios: [v] }));
  return groups;
}

/* 同一句裡若同時命中兩種分類，依較重的（醫療效能）敘述 */
function heaviest(vios) {
  return vios.find(v => v.violation_type !== '誇大不實') || vios[0];
}

function buildLetter() {
  clearNotice('noticeStep3');
  if (!analysis) {
    notify('noticeStep3', '請先完成 Step 2 的快篩分析，才能生成陳情信。', 'warn');
    return false;
  }
  const g = id => $(id).value.trim();
  const today = new Date();
  const rocDate = d => d ? `民國 ${new Date(d).getFullYear()-1911} 年 ${new Date(d).getMonth()+1} 月 ${new Date(d).getDate()} 日` : '（未填）';
  const pType = g('fType') || analysis.product_type;
  // 陳情信要跟 Step 2 顯示的是同一份：品類過濾之後，再扣掉健字號核准範圍內的用語。
  // 把持證產品合法標示的保健功效寫進陳情信，等於誣指，承辦人一查就會整份剔除。
  const hfHit = findHealthFoodPermit(analysis.ad_text || $('adText').value);
  const licSplit = splitByLicence(splitByScope(analysis.violations || [], pType).keep, hfHit);
  const usable = licSplit.keep;
  if (licSplit.licensed.length) {
    notify('noticeStep3', '已排除 ' + licSplit.licensed.length + ' 項在健康食品許可證核准範圍內的用語（'
         + licSplit.licensed.map(v => '「' + v.quote + '」').join('、') + '）。\n'
         + '該產品領有 ' + (hfHit.rec ? hfHit.rec.no : '') + '，得於許可範圍內標示這些保健功效。', 'ok', 12000);
  }
  if (!usable.length) {
    notify('noticeStep3', '依產品類別「' + pType + '」過濾後沒有適用的違規項目，無法生成陳情信。\n'
         + '請確認產品類別是否選對。', 'warn');
    return false;
  }
  const groups = groupBySentence(usable, analysis.ad_text || $('adText').value);
  const suspected = [];      // 只能標「疑似」的項次
  const vioText = groups.map((grp, i) => {
    const lead = heaviest(grp.vios);
    const law = lawFor(lead, pType);
    const words = grp.vios.map(v => '「' + v.quote + '」').join('、');
    const kinds = [].filter.call(
      ['宣稱醫療效能', '誇大不實'],
      k => grp.vios.some(v => v.violation_type === k)).join('、');

    // 逐詞列出依據。不可用整段最強的證據涵蓋整段——
    // 那會讓只是推論的用語看起來也有裁處前例，形同過度主張。
    const basisLines = grp.vios.map(v => {
      const e = evidenceOf(v.quote);
      const head = `　　　・「${v.quote}」（${v.violation_type}）`;
      if (e.level === 'c') return head + `：同類用語業經主管機關實際裁處。案例：${e.source}`;
      if (e.level === 'o') return head + `：經主管機關明文列為違規詞句。依據：${e.source}`;
      suspected.push(`第${i + 1}項「${v.quote}」`);
      return head + `：屬檢舉人依法規條文研判之疑似違規，尚無明文例示或裁處案例可稽，`
                  + `惠請貴局本於職權認定。研判依據：${e.source}`;
    }).join('\n');

    return `　（${i+1}）廣告宣稱：「${grp.line}」\n`
         + `　　　其中 ${words} 涉${kinds}。${reasonFor(lead, pType)}\n`
         + `　　　涉違反《${law.law_name}》${law.article}：「${law.summary}」\n`
         // 承辦人要能一鍵查證條文，而不是自己去翻法規資料庫
         + (law.url ? `　　　條文出處：${law.url}\n` : '')
         + `　　　罰則：${law.penalty}\n`
         + `　　　個別用語之依據：\n` + basisLines;
  }).join('\n\n');
  const suspectNote = suspected.length
    ? `\n\n　　※ 上開 ${suspected.join('、')} 係檢舉人依法規條文研判之疑似違規用語，`
      + `並非既有裁處前例，是否構成違規請貴局本於職權認定；`
      + `其餘各項均有主管機關明文例示或實際裁處案例可稽。`
    : '';

  // L8：必填檢核，不要讓「（姓名）」「（未填）」這種佔位符被印出去寄給衛生局
  const missing = [];
  if (!g('fName')) missing.push('檢舉人姓名');
  if (!g('fContact')) missing.push('聯絡電話或 Email');
  if (!g('fUrl') && !g('fPlatform')) missing.push('廣告網址或刊登平台（至少填一項）');
  if (!g('fDate')) missing.push('發現日期');
  if (missing.length) {
    notify('noticeStep3', '這幾個欄位還沒填，衛生局需要它們才能受理與聯繫：\n・'
         + missing.join('\n・'), 'warn');
    const first = ['fName', 'fContact', 'fUrl', 'fDate'].find(id => !g(id));
    if (first) $(first).focus();
    return false;
  }
  // L5：免費模式的後端永遠回「無法判定」，不提醒就會引到錯的法
  if (pType === '無法判定' || pType === '其他') {
    if (!buildLetter._typeOK) {
      notify('noticeStep3', '「產品類別」目前是「' + pType + '」，陳情信會引用食安法第28條。\n'
           + '若這是化粧品、藥品或醫療器材廣告，請先選對類別，否則會引到錯誤的法條與罰鍰級距。\n'
           + '確認無誤的話，再按一次「生成陳情信」即可。', 'warn');
      buildLetter._typeOK = true;
      return false;
    }
  } else {
    buildLetter._typeOK = false;
  }

  // 獎勵辦法要跟著產品類別走，化粧品不能引食安法的獎勵辦法
  const rewardRule = (pType === '食品' || pType === '健康食品')
    ? '「檢舉違反食品安全衛生管理法案件獎勵辦法」等相關規定'
    : '檢舉獎勵之相關規定';
  const pName = g('fProduct') || (/無法辨識|無法判定|未標示/.test(analysis.product_name) ? '（產品名稱未標示）' : analysis.product_name);
  // L16：「其他」「無法判定」都不要寫進主旨，讀起來會很怪
  const typeWord = (pType === '無法判定' || pType === '其他') ? '' : pType;
  const seller = g('fSeller');
  const adFull = String(analysis.ad_text || $('adText').value || '').trim();

  const pa = PRE_APPROVAL[pType];
  const paNote = pa
    ? `\n\n　　另，${pType}廣告依${pa.law}規定，應於刊播前經主管機關核准並載明核准文號。`
      + `檢舉人自廣告內容無從查證本件是否經核准，併請貴局一併查明有無未經核准擅自刊播之情事。`
    : '';

  // 使用者可能忽略畫面上的提示直接列印，信裡也要帶警語
  const oos = outOfScopeHit(adFull);
  const oosNote = oos
    ? `\n\n　　※※ 注意：本件廣告出現「${oos.words.join('」「')}」，可能屬於「${oos.name}」，`
      + `不適用本件所引法條。${oos.name}應依《${oos.cfg.law}》辦理，`
      + `主管機關為${oos.cfg.authority}。送件前請先確認產品類別，`
      + `或改向該主管機關陳情。 ※※`
    : '';
  const letter = `受文者：${g('fOrg') || '（縣市）政府衛生局'}

主旨：檢舉疑似違規之${typeWord}廣告「${pName}」，涉有誇大不實或宣稱醫療效能情事，請惠予查處。

說明：

一、檢舉人於 ${rocDate(g('fDate'))} 在「${g('fPlatform') || '（未載明平台）'}」發現旨揭廣告${seller ? `，刊登者為「${seller}」` : ''}，網址為：${g('fUrl') || '（未載明網址，詳如檢附截圖）'}。

二、旨揭廣告內容如下：

${adFull ? adFull.split('\n').map(l => '　　' + l).join('\n') : '　　（詳如檢附截圖）'}

三、上開廣告經初步檢視，疑有下列違規情事：

${vioText || '　（無）'}${suspectNote}${paNote}${oosNote}

四、上開廣告用語已逾越一般商業宣傳範圍，恐使消費者誤信產品具有醫療或誇大之效能，影響國民健康與消費權益，爰依相關法規檢舉，請貴局依法查處。

五、${imageB64 ? '檢附廣告截圖 1 份為證（隨本件另附）。' : '本件未檢附截圖，廣告內容如說明二所載。'}如需補充資料，請與檢舉人聯繫。

六、請貴局依${rewardRule}，於查處屬實後核發檢舉獎金，並依法保密檢舉人身分。

檢舉人：${g('fName') || '（姓名）'}
聯絡方式：${g('fContact') || '（電話/Email）'}
陳情日期：民國 ${today.getFullYear()-1911} 年 ${today.getMonth()+1} 月 ${today.getDate()} 日

（本檢舉內容由 AI 快篩系統輔助生成，違規事證之最終認定以主管機關調查結果為準。）`;

  $('letterPreview').textContent = letter;
  // L9：列印時把截圖當附件印出來，信裡才不會宣稱檢附卻沒有東西
  if (rawDataUrl) { $('attachImg').src = rawDataUrl; $('printAttach').classList.remove('hidden'); }
  else $('printAttach').classList.add('hidden');
  $('previewCard').classList.remove('hidden');
  markStep(4);
  return true;
}

$('genBtn').onclick = () => {
  if (buildLetter()) $('previewCard').scrollIntoView({ behavior: 'smooth' });
};

$('copyBtn').onclick = () => {
  navigator.clipboard.writeText($('letterPreview').textContent)
    .then(() => notify('noticeStep4', '陳情信全文已複製到剪貼簿。', 'ok', 2600))
    .catch(() => notify('noticeStep4',
      '瀏覽器不允許自動複製。請直接在上方選取文字後按 Ctrl + C。', 'warn', 6000));
};

function esc(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
