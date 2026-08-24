/* AI 違規廣告快篩 — 前端邏輯
   OCR（Windows 內建 / 瀏覽器 tesseract.js）、法規比對、陳情信生成
   改完請執行 build.py 重新產生 ../static/index.html */
const $ = id => document.getElementById(id);

/* 頁面內訊息（取代 alert）：type = err / warn / ok */
function notify(slot, text, type, autoHideMs) {
  const el = $(slot);
  if (!el) return;
  if (el._t) { clearTimeout(el._t); el._t = null; }
  el.className = 'notice show ' + (type || 'err');
  el.innerHTML = '<button class="x" type="button" title="關閉">✕</button>'
               + esc(text).replace(/\n/g, '<br>');
  el.querySelector('.x').onclick = () => clearNotice(slot);
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
/* 這支 exe 的後端能不能自己用 Windows 內建 OCR 讀圖：null=還沒試過，true/false=已知 */
let serverOcr = null;

/* ============ 免費 AI（Gemini）設定 ============ */
const GEMINI_MODELS = ['gemini-2.5-flash', 'gemini-2.0-flash', 'gemini-flash-latest'];
const gKeyGet = () => (localStorage.getItem('gemini_key') || '').trim();

/* 法規對照表 — 內容與同資料夾的 regulations.json 相同，僅「免費 AI 模式」會用到。
   若你改了 regulations.json 的法條，請一併更新這裡。 */
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
function currentType() {
  const sel = $('fType');
  return (sel && sel.value) || (analysis && analysis.product_type) || '';
}

/* 以 OCR 第一行猜產品名稱（廣告文案第一行通常就是品名） */
function guessProductName(text) {
  const first = String(text || '').split('\n').map(x => x.trim()).filter(Boolean)[0] || '';
  return (first.length >= 2 && first.length <= 30) ? first : '';
}

/* ============ 系統狀態 ============ */
fetch('/api/status').then(r => r.json())
  .then(s => { aiEnabled = !!s.ai_enabled; })
  .catch(() => {});

/* ============ 圖片載入（點選 / 拖曳 / 貼上） ============ */
const drop = $('drop'), fileInput = $('file');
drop.onclick = () => fileInput.click();
drop.ondragover = e => { e.preventDefault(); drop.classList.add('over'); };
drop.ondragleave = () => drop.classList.remove('over');
drop.ondrop = e => { e.preventDefault(); drop.classList.remove('over'); if (e.dataTransfer.files[0]) loadFile(e.dataTransfer.files[0]); };
fileInput.onchange = () => { if (fileInput.files[0]) loadFile(fileInput.files[0]); };
document.addEventListener('paste', e => {
  const items = (e.clipboardData && e.clipboardData.items) || [];
  const item = [].slice.call(items).find(i => i.type.indexOf('image/') === 0);
  if (item) { e.preventDefault(); loadFile(item.getAsFile()); }
});

const MAX_MB = 10;
const OK_TYPES = ['image/png', 'image/jpeg', 'image/webp', 'image/gif', 'image/bmp'];

function loadFile(f) {
  if (!f) return;
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
    img.style.display = 'block';
    img.onload = () => {
      const w = img.naturalWidth, h = img.naturalHeight;
      drop.innerHTML = '已選擇：<b>' + esc(f.name || '剪貼簿圖片') + '</b>'
        + '<br><small>' + esc((type || 'image/png').replace('image/', '').toUpperCase())
        + '　·　' + w + ' × ' + h + ' px　·　' + mb.toFixed(1) + ' MB　·　點擊可更換</small>';
      if (Math.min(w, h) < 600) {
        notify('noticeStep1', '這張圖解析度偏低（' + w + ' × ' + h + ' px），文字辨識可能不準。\n'
             + '建議改用原圖或放大後的截圖；辨識完成後請務必檢查「廣告文字」欄位。', 'warn');
      }
    };
    img.src = rawDataUrl;
    // 換圖時清掉上一張的辨識結果，但保留使用者自己打的字
    const ta = $('adText');
    if (lastOcrText && ta.value.trim() === lastOcrText) { ta.value = ''; lastOcrText = ''; }
    if (aiEnabled || gKeyGet()) {
      $('ocrBar').classList.add('hidden');    // AI 模式直接看圖，不需要 OCR
    } else if (serverOcr === false) {
      runOCR(true);                           // 已知 Windows OCR 不能用 → 直接跑瀏覽器 OCR
    } else {
      ocrMsg('圖片已載入 — 按「開始快篩分析」，會用 Windows 內建 OCR 讀取圖上的文字。');
    }
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
const MAX_SIDE = 4000;   // 超過這個尺寸才縮小，純粹避免超大圖跑太慢

function loadImg(dataUrl) {
  return new Promise((res, rej) => {
    const img = new Image();
    img.onerror = () => rej(new Error('圖片無法讀取'));
    img.onload = () => res(img);
    img.src = dataUrl;
  });
}

function rescale(img, scale) {
  if (Math.abs(scale - 1) < 0.01) return img.src;
  const c = document.createElement('canvas');
  c.width = Math.round(img.naturalWidth * scale);
  c.height = Math.round(img.naturalHeight * scale);
  const ctx = c.getContext('2d');
  ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high';
  ctx.drawImage(img, 0, 0, c.width, c.height);
  return c.toDataURL('image/png');
}

const charCount = s => String(s || '').replace(/\s/g, '').length;

/* OCR 會在中文字之間插入空白，會讓關鍵字比對失效，這裡還原。
   另外把全形英數轉半形 —— 後端是純子字串比對，「７天美白」比對不到「7天美白」。 */
const CJK = '\\u3000-\\u303f\\u4e00-\\u9fff\\uf900-\\ufaff\\uff00-\\uffef';
function toHalfWidth(s) {
  return s.replace(/[０-９Ａ-Ｚａ-ｚ]/g,
                   c => String.fromCharCode(c.charCodeAt(0) - 0xfee0));
}
function tidyCJK(s) {
  return toHalfWidth(String(s || ''))
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
      return await Tesseract.createWorker('chi_tra+eng', 1, {
        logger: m => { if (tessProgress) tessProgress(m); }
      });
    })().catch(e => { tessWorkerP = null; throw e; });
  }
  return tessWorkerP;
}

async function runOCR(auto) {
  if (!rawDataUrl || ocrBusy) return;
  ocrBusy = true;
  const ta = $('adText');
  try {
    ocrMsg('讀取圖片…', true);
    const img = await loadImg(rawDataUrl);
    const longSide = Math.max(img.naturalWidth, img.naturalHeight);
    const shortSide = Math.min(img.naturalWidth, img.naturalHeight);
    const first = longSide > MAX_SIDE ? rescale(img, MAX_SIDE / longSide) : rawDataUrl;

    ocrMsg('載入中文辨識模型…（第一次約需下載 9 MB，之後瀏覽器會自動快取）', true);
    tessProgress = m => {
      if (m.status === 'recognizing text') ocrMsg('辨識文字中… ' + Math.round((m.progress || 0) * 100) + '%', true);
      else if (m.status) ocrMsg(m.status + '…', true);
    };
    const worker = await getTessWorker();
    let text = tidyCJK((await worker.recognize(first)).data.text);

    // 幾乎沒讀到字，而且原圖偏小 → 放大兩倍再試一次，取較長的結果
    if (charCount(text) < 10 && shortSide < 1000) {
      ocrMsg('文字太少，放大後再試一次…', true);
      const retry = tidyCJK((await worker.recognize(rescale(img, 2))).data.text);
      if (charCount(retry) > charCount(text)) text = retry;
    }
    tessProgress = null;
    if (!text) {
      ocrMsg('⚠ 沒有辨識到文字 — 請把廣告文案手動貼到下方欄位（或用 Win + Shift + S 截圖後，在「剪取工具」按「文字動作」直接複製圖上的字）。');
      return;
    }
    const cur = ta.value.trim();
    let note = '';
    if (!cur) {
      ta.value = text;
    } else if (auto) {
      if (cur === lastOcrText) ta.value = text;          // 自動重跑：換掉上一次的辨識結果
    } else if (cur.indexOf(text) < 0) {
      ta.value = cur + '\n' + text;                      // 手動補一次：兩個引擎的結果併起來
      note = '（已附加在原本的文字後面，重複的詞不會重複計算）';
    }
    lastOcrText = text;
    ocrMsg('✅ 瀏覽器 OCR 辨識出 ' + charCount(text) + ' 個字' + note
         + ' — 請確認下方文字是否正確，可自行修正後再按「開始快篩分析」。');
  } catch (e) {
    tessProgress = null;
    ocrMsg('⚠ 圖片辨識失敗：' + e.message + ' — 請把廣告文案手動貼到下方欄位。');
  } finally {
    ocrBusy = false;
  }
}
$('ocrBtn').onclick = async () => {
  const btn = $('ocrBtn');
  clearNotice('noticeStep1');
  setBusy(btn, '辨識中…');
  setBusy($('analyzeBtn'), '請稍候…');
  try {
    await runOCR(false);
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
$('analyzeBtn').onclick = async () => {
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
    renderResult(analysis);
    crossCheckWithBrowserOCR();      // 不 await：先讓使用者看到結果
  } catch (e) {
    notify('noticeStep1', e.message, 'err');
  } finally {
    setBusy(btn, null);
    setBusy($('ocrBtn'), null);
    showSpinner(false);
  }
};

/* 分析完成後，背景再用瀏覽器 OCR 讀一次做交叉比對。
   Windows OCR 有時會把關鍵字吃掉（例如「改善心血管疾病」讀成「改」），
   兩套引擎互補可以把漏掉的違規補回來。 */
async function crossCheckWithBrowserOCR() {
  if (aiEnabled || gKeyGet()) return;          // AI 模式直接看圖，不需要
  if (!imageB64 || serverOcr !== true) return; // 只有走過 Windows OCR 才需要補
  const ta = $('adText');
  if (ta.value.trim() !== lastOcrText) return; // 使用者已經自己改過字，不要動

  const before = (analysis && analysis.violations || []).length;
  try {
    ocrMsg('背景交叉比對中：用瀏覽器 OCR 再讀一次，避免漏字…', true);
    await runOCR(false);
    if (ta.value.trim() === lastOcrText) return;   // 沒有補到新文字
    const data = await postAnalyze(null, null, ta.value);
    const after = (data.violations || []).length;
    if (after > before) {
      analysis = data;
      renderResult(data, { noScroll: true, keepType: true });
      notify('noticeStep1', '交叉比對完成：瀏覽器 OCR 又補抓到 ' + (after - before)
           + ' 項違規（合計 ' + after + ' 項），上方結果已更新。', 'ok', 9000);
    }
  } catch (e) {
    ocrMsg('（背景交叉比對未完成：' + e.message + '，不影響上方結果）');
  }
}

function postAnalyze(img, mime, text) {
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
        ta.value = got; lastOcrText = got;
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

function renderResult(d, opts) {
  opts = opts || {};
  $('rProduct').textContent = d.product_name;
  $('rType').textContent = d.product_type;
  const risk = $('rRisk');
  risk.textContent = d.risk_level; risk.className = 'risk ' + d.risk_level;
  $('rSummary').textContent = d.overall_assessment;
  const list = $('vioList');
  list.innerHTML = '';
  if (!d.violations.length) list.innerHTML = '<p style="color:var(--ok)">未偵測到明顯違規字句。</p>';
  const pType = currentType();
  d.violations.forEach((v, i) => {
    const law = lawFor(v, pType);
    const div = document.createElement('div');
    div.className = 'vio type-' + v.violation_type;
    div.innerHTML = `
      <div class="quote">${i+1}. 「${esc(v.quote)}」<span class="tag">${esc(v.violation_type)}</span></div>
      <div style="font-size:.88rem;margin-top:5px">${esc(v.reason)}</div>
      <div class="law">📖 <b>${esc(law.law_name||'')} ${esc(law.article||'')}</b>：${esc(law.summary||'')}<br>
        ⚖ ${esc(law.penalty||'')}　<a href="${esc(law.url||'#')}" target="_blank">全國法規資料庫原文 ↗</a></div>
      <div class="conf">AI 信心程度：${esc(v.confidence)}</div>`;
    list.appendChild(div);
  });
  // 帶入陳情信欄位（已經有值就不覆蓋，避免蓋掉使用者填的內容）
  const known = d.product_name && !/無法辨識|無法判定|未標示/.test(d.product_name);
  const nameBox = $('fProduct'), typeSel = $('fType');
  if (nameBox && !nameBox.value.trim()) {
    nameBox.value = known ? d.product_name
                          : guessProductName(d.ad_text || $('adText').value);
  }
  if (typeSel && typeSel.options && !opts.keepType &&
      [].some.call(typeSel.options, o => o.value === d.product_type)) typeSel.value = d.product_type;

  $('resultCard').classList.remove('hidden');
  $('letterCard').classList.remove('hidden');
  markStep(3);
  if (!opts.noScroll) $('resultCard').scrollIntoView({behavior:'smooth'});
}

/* 換產品類別要即時換掉引用的法條 */
$('fType').onchange = () => {
  if (analysis) renderResult(analysis, { noScroll: true, keepType: true });
};

/* ============ 陳情信 ============ */
$('genBtn').onclick = () => {
  clearNotice('noticeStep3');
  if (!analysis) {
    notify('noticeStep3', '請先完成 Step 2 的快篩分析，才能生成陳情信。', 'warn');
    return;
  }
  const g = id => $(id).value.trim();
  const today = new Date();
  const rocDate = d => d ? `民國 ${new Date(d).getFullYear()-1911} 年 ${new Date(d).getMonth()+1} 月 ${new Date(d).getDate()} 日` : '（未填）';
  const pType = g('fType') || analysis.product_type;
  const vioText = analysis.violations.map((v,i) => {
    const law = lawFor(v, pType);
    return `　（${i+1}）廣告宣稱「${v.quote}」（${v.violation_type}）：${v.reason}\n　　　涉違反《${law.law_name}》${law.article}：「${law.summary}」\n　　　罰則：${law.penalty}`;
  }).join('\n\n');

  // 獎勵辦法要跟著產品類別走，化粧品不能引食安法的獎勵辦法
  const rewardRule = (pType === '食品' || pType === '健康食品')
    ? '「檢舉違反食品安全衛生管理法案件獎勵辦法」等相關規定'
    : '檢舉獎勵之相關規定';
  const pName = g('fProduct') || (/無法辨識|無法判定|未標示/.test(analysis.product_name) ? '（產品名稱未標示）' : analysis.product_name);

  const letter = `受文者：${g('fOrg') || '（縣市）政府衛生局'}

主旨：檢舉疑似違規之${pType !== '無法判定' ? pType : ''}廣告「${pName}」，涉有誇大不實或宣稱醫療效能情事，請惠予查處。

說明：

一、檢舉人於 ${rocDate(g('fDate'))} 在「${g('fPlatform') || '（平台）'}」發現旨揭廣告，網址為：${g('fUrl') || '（網址）'}。

二、該廣告內容經初步檢視，疑有下列違規情事：

${vioText || '　（無）'}

三、上開廣告用語已逾越一般商業宣傳範圍，恐使消費者誤信產品具有醫療或誇大之效能，影響國民健康與消費權益，爰依相關法規檢舉，請貴局依法查處。

四、檢附廣告截圖 ${imageB64 ? '1' : '0'} 份為證。如需補充資料，請與檢舉人聯繫。

五、請貴局依${rewardRule}，於查處屬實後核發檢舉獎金，並依法保密檢舉人身分。

檢舉人：${g('fName') || '（姓名）'}
聯絡方式：${g('fContact') || '（電話/Email）'}
陳情日期：民國 ${today.getFullYear()-1911} 年 ${today.getMonth()+1} 月 ${today.getDate()} 日

（本檢舉內容由 AI 快篩系統輔助生成，違規事證之最終認定以主管機關調查結果為準。）`;

  $('letterPreview').textContent = letter;
  $('previewCard').classList.remove('hidden');
  markStep(4);
  $('previewCard').scrollIntoView({behavior:'smooth'});
};

$('copyBtn').onclick = () => {
  navigator.clipboard.writeText($('letterPreview').textContent)
    .then(() => notify('noticeStep4', '陳情信全文已複製到剪貼簿。', 'ok', 2600))
    .catch(() => notify('noticeStep4',
      '瀏覽器不允許自動複製。請直接在上方選取文字後按 Ctrl + C。', 'warn', 6000));
};

function esc(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
