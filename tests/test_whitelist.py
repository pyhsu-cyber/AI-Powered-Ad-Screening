"""
tests/test_whitelist.py — 合法宣稱白名單回歸測試

用官方白名單反向檢驗關鍵字資料庫：**任何違規關鍵字命中法規明文允許的宣稱，
都是誤判**。這支測試的用意是讓「新增關鍵字」這件事有一道自動防線——
擴充關鍵字時最容易犯的錯，就是收了一個看起來很違規、實際上法規允許的用語。

白名單來源（測試資料/合法宣稱白名單.json）：
  - 化粧品標示宣傳廣告涉及虛偽誇大或醫療效能認定準則 附件二（通常得使用之詞句）
    與附件三（成分之生理機能詞句）
  - 食品認定準則所列得宣稱之詞句

品類專屬詞不算誤判：例如「美白」用於食品違規、用於化粧品合法，
已由 regulations.json 的 keyword_scope 分流，比對白名單時要跳過不適用的品類。

執行方式：
  python tests/test_whitelist.py
"""
import sys, os, io, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# 主控台預設 cp950，輸出中文與 ≥ 等符號會讓整支測試 crash，先轉成 UTF-8
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.path.join(os.path.dirname(__file__), '..')
_passed = _failed = 0


def check(label, cond, detail=""):
    global _passed, _failed
    if cond:
        print(f"  PASS  {label}")
        _passed += 1
    else:
        print(f"  FAIL  {label}" + (f"  [{detail}]" if detail else ""))
        _failed += 1


reg = json.loads(io.open(os.path.join(ROOT, 'regulations.json'), encoding='utf-8').read())
wl = json.loads(io.open(os.path.join(ROOT, '測試資料', '合法宣稱白名單.json'),
                        encoding='utf-8').read())

dk = reg['demo_keywords']
ALL = dk['medical_efficacy'] + dk['exaggeration']
scope = reg.get('keyword_scope', {})
COS_ONLY = set(scope.get('cosmetic_only', []))
FOOD_ONLY = set(scope.get('food_only', []))

print(f"\n關鍵字 {len(ALL)} 詞 ／ 化粧品合法語句 {len(wl['cosmetic_permitted'])} 句"
      f" ／ 食品合法用語 {len(wl['food_permitted'])} 個")

print("\n── 化粧品合法宣稱不得被判違規 ──")
cos_hits = []
for line in wl['cosmetic_permitted']:
    for k in ALL:
        if k in FOOD_ONLY:          # 食品專屬詞不套用於化粧品
            continue
        if k in line:
            # 白名單裡的否定敘述（例如「（非指增加髮量）」）不是允許該詞，是排除它
            if '非指' in line or '不得' in line:
                continue
            cos_hits.append((k, line))
check("化粧品合法宣稱零誤判", not cos_hits,
      "；".join(f"「{k}」← {l[:30]}" for k, l in cos_hits[:5]))

print("\n── 食品合法用語不得被判違規 ──")
food_hits = []
for phrase in wl['food_permitted']:
    for k in ALL:
        if k in COS_ONLY:           # 化粧品專屬詞不套用於食品
            continue
        if k in phrase:
            food_hits.append((k, phrase))

# 證據等級決定嚴重性：
#   c／o 級命中白名單 = 硬性失敗。陳情信會寫「業經主管機關實際裁處」或
#     「經主管機關明文列為違規詞句」，對法規明文允許的宣稱這樣寫就是誣指。
#   i 級命中 = 資訊性。信裡寫的是「疑似違規，惠請貴局本於職權認定」，
#     而這類詞的合法與否本來就取決於成分或許可證（例如維生素C得宣稱
#     「有助於傷口癒合」、領健字號者得宣稱「骨質保健」），標疑似正是誠實的處理。
_ev = reg.get('keyword_evidence', {}).get('map', {})
hard = [(k, p) for k, p in food_hits if _ev.get(k, ['i'])[0] in ('c', 'o')]
soft = [(k, p) for k, p in food_hits if _ev.get(k, ['i'])[0] == 'i']
if soft:
    print(f"  INFO  {len(soft)} 個「疑似」級關鍵字命中白名單（合法與否視成分／許可證而定）")
    for k, p in soft[:5]:
        print(f"          「{k}」← {p[:40]}")
check("無 c／o 級關鍵字命中食品合法用語（否則陳情信會誣指）", not hard,
      "；".join(f"「{k}」← {p[:30]}" for k, p in hard[:5]))

print("\n── 資料庫自身一致性 ──")
dupes = [k for k in set(ALL) if ALL.count(k) > 1]
check("無完全重複的關鍵字", not dupes, str(dupes[:8]))

cross = set(dk['medical_efficacy']) & set(dk['exaggeration'])
check("無跨類重複（會重複計算違規項數）", not cross, str(sorted(cross)[:8]))

# 巢狀關鍵字（長詞包含短詞）在 API 層會各回一筆，但前端 splitByScope 會先跑
# dedupeNested 保留較長者，畫面與陳情信只會出現一項，風險等級也由前端重算。
# 已實測：「本產品7天美白」API 回 2 項，畫面顯示「低 / 1 項」。
# 所以這裡只列出來供人檢視，不當作失敗——但巢狀關係必須是純子字串，
# 否則 dedupeNested 的判斷式（長詞 indexOf 短詞 >= 0）就收斂不了。
nested = [(k, o) for k in ALL for o in ALL if o != k and o in k]
print(f"  INFO  巢狀關鍵字 {len(nested)} 對（前端 dedupeNested 會收斂為一項）")
for k, o in nested[:5]:
    print(f"          「{k}」含「{o}」")
if len(nested) > 5:
    print(f"          …另有 {len(nested) - 5} 對")
check("巢狀關鍵字皆為純子字串（dedupeNested 才收斂得了）",
      all(o in k for k, o in nested))

blank = [k for k in ALL if not k.strip() or any(c in k for c in ' \t　、，。')]
check("關鍵字不含空白或標點", not blank, str(blank[:5]))

print("\n── 證據等級完整性 ──")
ev = reg.get('keyword_evidence', {})
m, srcs = ev.get('map', {}), ev.get('sources', [])
missing = [k for k in ALL if k not in m]
check("每個關鍵字都有證據等級", not missing, f"{len(missing)} 個缺漏：{missing[:5]}")

bad_idx = [k for k, v in m.items() if not (0 <= v[1] < len(srcs))]
check("證據來源索引皆有效", not bad_idx, str(bad_idx[:5]))

bad_lv = [k for k, v in m.items() if v[0] not in 'coi']
check("證據等級皆為 c/o/i", not bad_lv, str(bad_lv[:5]))

empty_src = [k for k, v in m.items() if not srcs[v[1]].strip()]
check("證據來源字串非空", not empty_src, str(empty_src[:5]))

print("\n── 法條完整性 ──")
for l in reg['laws']:
    pass
no_url = [l['id'] for l in reg['laws'] if not l.get('url')]
check("每條法條都有可查證的網址", not no_url, str(no_url))

vague = [l['id'] for l in reg['laws']
         if '請以主管機關' in l.get('penalty', '') or not l.get('penalty', '').strip()]
check("罰則皆已查明（無「請以主管機關為準」佔位）", not vague, str(vague))

print()
print("── 語境排除：法定警語與良性語境不得誤判 ──")
# 這些關鍵字（病名裸詞、殺菌、再生、磨損、雷射）確實是主管機關例示或有裁處
# 案例的違規用語，不能刪掉 —— 「糖尿病」全庫只有一個組合詞，拔掉裸詞等於放棄
# 整個病名的召回。但它們出現在法定警語與加工製程敘述裡時並非違規宣稱，
# 由 regulations.json 的 context_exclusions 負責排除。
from backend.analyzer import analyze_text, reload_regulations
reload_regulations()

BENIGN = [
    "糖尿病患者、孕婦及嬰幼兒食用前請諮詢醫師。",
    "高血壓、高血脂患者請依醫囑控制飲食。",
    "氣喘、心律不整患者請先諮詢醫師後再服用。",
    "痔瘡患者不宜食用。",
    "乳糖不耐症者請勿食用。",
    "偏頭痛患者請遵醫囑。",
    "本產品經135℃超高溫殺菌，無菌充填，開封前無需冷藏。",
    "採巴斯德殺菌法製造。",
    "外盒採用100%再生紙材。",
    "本器材採不鏽鋼刀頭，耐磨損不易鈍化。",
    "本品外包裝以雷射雕刻防偽標籤。",
]
for _text in BENIGN:
    _hits = [v.quote for v in analyze_text(_text).violations]
    check(f"良性語境無誤判：{_text[:22]}", not _hits, f"誤判 {_hits}")

print()
print("── 語境排除不得變成規避漏洞 ──")
STILL_VIOLATING = [
    ("本品可根治糖尿病，糖尿病患者請諮詢醫師。", "同句另有療效宣稱"),
    ("三個月改善高血壓，請諮詢醫師。", "警語當擋箭牌"),
    ("有效緩解咳嗽，請依醫囑服用。", "警語當擋箭牌"),
    ("擺脫偏頭痛困擾，孕婦請諮詢醫師。", "警語當擋箭牌"),
    ("糖尿病患者請諮詢醫師。本品可治療糖尿病。", "另一句是乾淨的違規"),
    ("殺菌消炎，體內環保。", "非製程語境"),
    ("促進細胞再生，肌膚再生。", "非包材語境"),
    ("媲美雷射的除斑效果。", "非防偽語境"),
    ("改善關節磨損疼痛。", "非耐用性語境"),
]
for _text, _why in STILL_VIOLATING:
    _hits = [v.quote for v in analyze_text(_text).violations]
    check(f"仍應命中（{_why}）：{_text[:22]}", bool(_hits), "被語境排除吃掉了")

print()
print("── 語境排除規則結構完整性 ──")
_ce = reg.get("context_exclusions", {})
check("context_exclusions 存在且有規則", bool(_ce.get("rules")))
_bad_kw = [k for r in _ce.get("rules", []) for k in r.get("keywords", []) if k not in ALL]
check("規則引用的關鍵字都存在於關鍵字表", not _bad_kw, str(_bad_kw))
_bad_grp = [r.get("group") for r in _ce.get("rules", [])
            if not r.get("context") and r.get("group") not in _ce.get("groups", {})]
check("規則引用的語境群組都存在", not _bad_grp, str(_bad_grp))
_empty = [r.get("keywords") for r in _ce.get("rules", [])
          if not (r.get("context") or _ce.get("groups", {}).get(r.get("group"), []))]
check("每條規則都有排除語境", not _empty, str(_empty))
_blk = _ce.get("claim_blockers", [])
check("療效動詞否決清單非空", bool(_blk), str(len(_blk)))
# 「控制」會出現在「請依醫囑控制飲食」、「有效」會出現在「有效期限」，
# 收進否決清單會讓警語排除整個失效
_risky = [b for b in _blk if b in ("控制", "有效", "注意", "建議", "期限")]
check("否決清單未收會出現在警語裡的詞", not _risky, str(_risky))

print(f"\n{'='*50}")
print(f"白名單測試結果：{_passed} 通過 / {_failed} 失敗")
# 直接執行時用結束碼回報失敗。pytest 下不能 exit —— 那會變成 collection
# error 而不是一筆乾淨的測試失敗，下面的 test_all_checks_passed 會接手。
if _failed and "pytest" not in sys.modules:
    sys.exit(1)


# ══════════════════════════════════════════════════════════
# pytest 進入點
# ══════════════════════════════════════════════════════════
# 這支檔案的測試邏輯寫在模組層，可以直接 `python <本檔>` 執行。
# 但 pytest 只 import 模組、不會把模組層的斷言當成 test item ——
# 補上這個函式之前，`python -m pytest backend tests` 回報的是
# "no tests ran"（exit 5），等於 README 記載的驗證指令什麼都沒驗。
def test_all_checks_passed():
    """模組層的檢查在 import 時已跑完，這裡把失敗數斷言出來。"""
    assert _failed == 0, f"{_failed} 項檢查失敗（詳見上方 FAIL 行）"
