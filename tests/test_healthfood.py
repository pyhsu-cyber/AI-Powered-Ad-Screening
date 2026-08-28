"""
tests/test_healthfood.py — 健康食品許可證快照與比對邏輯

領有衛福部健康食品許可證（健字號）者，得在核准範圍內合法標示該項保健功效。
「調節血脂」「護肝」這 13 個詞對持證產品不是違規，對沒證的產品才是。
在有這份快照之前工具無法查證，只能一律標成「疑似・待認定」
（測試資料 R7 就是為此列的已知限制）。

這支測試守兩件事：
  1. 快照資料本身的完整性（欄位、比對鍵唯一、功效值都在法定 13 項內）
  2. 快照確實被 build.py 注入到出貨的 static/index.html

前端的比對邏輯（字號辨識、核准範圍排除、證況判斷）用 node 直接跑**出貨產物裡
的那份程式碼**驗證；機器上沒有 node 就跳過那一段，不讓它變成硬相依。

執行方式：
  python tests/test_healthfood.py
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# 主控台預設 cp950，輸出中文會讓整支測試 crash，先轉成 UTF-8
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.path.join(os.path.dirname(__file__), '..')
_passed = _failed = 0


def check(label, cond, detail=""):
    global _passed, _failed
    if cond:
        print("  PASS  " + label)
        _passed += 1
    else:
        print("  FAIL  " + label + (("  [" + detail + "]") if detail else ""))
        _failed += 1


def info(label, detail=""):
    print("  INFO  " + label + (("  [" + detail + "]") if detail else ""))


snap = json.loads(io.open(os.path.join(ROOT, '健康食品許可證.json'), encoding='utf-8').read())
reg = json.loads(io.open(os.path.join(ROOT, 'regulations.json'), encoding='utf-8').read())
built = io.open(os.path.join(ROOT, 'static', 'index.html'), encoding='utf-8').read()

recs = snap.get('records', [])
CANON = snap.get('_canonical_effects', [])

print("── 快照資料完整性 ──")
check("快照有記錄", len(recs) > 400, "%d 筆" % len(recs))
check("筆數與 _count 相符", len(recs) == snap.get('_count'),
      "%s vs %s" % (len(recs), snap.get('_count')))
check("有快照日期", bool(re.match(r'^\d{4}-\d{2}-\d{2}$', snap.get('_snapshot_date', ''))),
      str(snap.get('_snapshot_date')))
check("有標明資料來源與授權", bool(snap.get('_source')) and bool(snap.get('_license')))
check("法定保健功效恰為 13 項", len(CANON) == 13, str(len(CANON)))

miss_field = [r.get('no') for r in recs
              if not all(k in r for k in ('k', 'no', 'name', 'co', 'st', 'eff', 'claim'))]
check("每筆都有必要欄位", not miss_field, str(miss_field[:3]))

keys = [r['k'] for r in recs]
check("比對鍵唯一（撞號會查到錯的產品）", len(set(keys)) == len(keys),
      "%d 個重複" % (len(keys) - len(set(keys))))
bad_key = [k for k in keys if not re.match(r'^[般規]\|[A-Z]?\d+$', k)]
check("比對鍵格式正確", not bad_key, str(bad_key[:3]))

bad_eff = sorted({e for r in recs for e in r.get('eff', []) if e not in CANON})
check("所有保健功效都在法定 13 項內", not bad_eff, str(bad_eff))

valid = [r for r in recs if r['st'] == '核可']
check("核可筆數合理", 300 < len(valid) < len(recs),
      "核可 %d / 共 %d" % (len(valid), len(recs)))
info("證況分布", str({s: sum(1 for r in recs if r['st'] == s) for s in {r['st'] for r in recs}}))

no_claim = [r['no'] for r in valid if not r.get('claim')]
check("核可的證幾乎都有保健功效宣稱原文（那是比對的依據）",
      len(no_claim) < len(valid) * 0.1, "%d 筆缺宣稱原文" % len(no_claim))

print("\n── 與關鍵字表的對應 ──")
allkw = set(reg['demo_keywords']['medical_efficacy']) | set(reg['demo_keywords']['exaggeration'])
missing_kw = [e for e in CANON if e not in allkw]
check("13 項法定保健功效都是關鍵字（沒證而宣稱才抓得到）", not missing_kw, str(missing_kw))

evmap = reg['keyword_evidence']['map']
wrong_lv = [e for e in CANON if e in evmap and evmap[e][0] != 'i']
check("這 13 項的證據等級都是 i（合法與否取決於有無許可證）", not wrong_lv, str(wrong_lv))

print("\n── build.py 是否真的把快照注入出貨檔 ──")
check("static/index.html 含 HEALTH_FOOD", 'const HEALTH_FOOD' in built)
m = re.search(r'const HEALTH_FOOD = (\{.*?\});\n', built, re.S)
check("HEALTH_FOOD 可解析", bool(m))
if m:
    inj = json.loads(m.group(1))
    check("注入筆數與快照相符", len(inj.get('records', [])) == len(recs),
          "%s vs %s" % (len(inj.get('records', [])), len(recs)))
    check("注入的快照日期相符", inj.get('date') == snap.get('_snapshot_date'))
    check("底線註解沒有被打包進去（省體積）",
          not any(k.startswith('_') for k in inj.keys()), str(list(inj.keys())))
check("前端有字號辨識與核准範圍排除",
      all(s in built for s in ('findHealthFoodPermit', 'splitByLicence', 'renderHealthFoodCard')))
check("陳情信也用同一份濾過的清單", 'licSplit.keep' in built)

print("\n── 前端比對邏輯（用 node 跑出貨產物裡的程式碼）──")
_node = shutil.which('node')
if not _node:
    info("找不到 node，略過前端邏輯測試", "資料層測試不受影響")
else:
    _sample = next(r for r in recs if r['st'] == '核可' and len(r['eff']) >= 2)
    _dead = next((r for r in recs if r['st'] != '核可' and r['eff']), None)
    _harness = r'''
const fs = require('fs');
const js = fs.readFileSync(process.argv[2], 'utf8').match(/<script>([\s\S]*)<\/script>/)[1];
const grab = n => { const i = js.indexOf('function ' + n + '('); if (i < 0) throw new Error(n);
  let d = 0, s = false;
  for (let j = i; j < js.length; j++) { if (js[j] === '{') { d++; s = true; }
    else if (js[j] === '}') { d--; if (s && !d) return js.slice(i, j + 1); } } };
const ctx = {};
new Function('g',
  js.match(/const HEALTH_FOOD = [\s\S]*?;\n/)[0] + js.match(/const HF_NO_RE = [^\n]*\n/)[0] +
  grab('hfNormalize') + grab('hfKey') + grab('findHealthFoodPermit') + grab('splitByLicence') +
  '\ng.find = findHealthFoodPermit; g.split = splitByLicence;')(ctx);
const A = JSON.parse(process.argv[3]);
const core = A.sample.no.replace(/\(.*\)/, '');
const out = [];
const t = (l, c, x) => out.push([l, !!c, x || '']);
for (const [lbl, txt] of [['完整寫法', core], ['去掉衛部', core.replace(/^衛[部署]/, '')],
     ['夾雜空白（OCR 常見）', core.split('').join(' ')],
     ['夾在句子裡', '本產品 ' + core + ' 通過審核']]) {
  const h = ctx.find(txt);
  t('字號辨識：' + lbl, h && h.rec && h.rec.k === A.sample.k, h && h.rec ? h.rec.no : String(h));
}
t('沒寫字號回傳 null', ctx.find('本產品調節血脂，護肝') === null);
const fake = ctx.find('衛部健食字第A00000號');
t('假字號（R7 用的 A00000）回報查無而非誤配', fake && !fake.rec, fake ? fake.raw : 'null');
const hit = ctx.find(core);
const r = ctx.split(A.sample.eff.map(e => ({quote: e})).concat([{quote: '治療糖尿病'}]), hit);
t('核准範圍內的功效不列為違規', r.licensed.length === A.sample.eff.length,
  r.licensed.map(v => v.quote).join('、'));
t('醫療效能仍然保留（持證也不得宣稱）',
  r.keep.length === 1 && r.keep[0].quote === '治療糖尿病');
if (A.dead) {
  const hd = ctx.find(A.dead.no.replace(/\(.*\)/, ''));
  const rd = ctx.split(A.dead.eff.map(e => ({quote: e})), hd);
  t('證況「' + A.dead.st + '」不放行任何項', rd.licensed.length === 0);
}
t('hit 為 null 時全部保留', ctx.split([{quote: '護肝'}], null).keep.length === 1);
t('全域 regex 連續呼叫結果一致（lastIndex 不會卡住）',
  JSON.stringify(ctx.find(core)) === JSON.stringify(ctx.find(core)));
console.log(JSON.stringify(out));
'''
    _f = tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8')
    _f.write(_harness)
    _f.close()
    try:
        _args = json.dumps({'sample': _sample, 'dead': _dead}, ensure_ascii=False)
        _p = subprocess.run([_node, _f.name, os.path.join(ROOT, 'static', 'index.html'), _args],
                            capture_output=True, text=True, encoding='utf-8', timeout=60)
        if _p.returncode != 0:
            check("node 測試執行成功", False, (_p.stderr or '')[:200].replace('\n', ' '))
        else:
            for _label, _ok, _detail in json.loads(_p.stdout.strip().split('\n')[-1]):
                check(_label, _ok, _detail)
    finally:
        os.unlink(_f.name)

print("\n" + "=" * 50)
print("健康食品許可證測試結果：%d 通過 / %d 失敗" % (_passed, _failed))
# 直接執行時用結束碼回報失敗。pytest 下不能 exit —— 那會變成 collection
# error 而不是一筆乾淨的測試失敗，下面的 test_all_checks_passed 會接手。
if _failed and "pytest" not in sys.modules:
    sys.exit(1)


# ══════════════════════════════════════════════════════════
# pytest 進入點
# ══════════════════════════════════════════════════════════
def test_all_checks_passed():
    """模組層的檢查在 import 時已跑完，這裡把失敗數斷言出來。"""
    assert _failed == 0, f"{_failed} 項檢查失敗（詳見上方 FAIL 行）"
