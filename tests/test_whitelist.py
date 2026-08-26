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

print(f"\n{'='*50}")
print(f"白名單測試結果：{_passed} 通過 / {_failed} 失敗")
if _failed:
    sys.exit(1)
