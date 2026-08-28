# -*- coding: utf-8 -*-
"""從 TFDA 開放資料更新 ../健康食品許可證.json 快照。

為什麼要做成「建置期快照」而不是執行期查詢：
  1. TFDA 的回應沒有 Access-Control-Allow-Origin 標頭，瀏覽器直接 fetch 會被
     CORS 擋掉，線上版根本走不通。
  2. 這個工具的賣點之一是「圖片與檢舉人個資不會離開這台電腦」。執行期去查
     外部 API 會把產品名或字號送出去，破壞那個承諾。
  3. 精簡後只有約 150 KB（gzip 20 KB），內嵌成本極低。

用法（需要連網，平常不必跑）：
    python update_healthfood.py
    python update_healthfood.py --dry-run     # 只比對差異，不寫檔

資料來源：衛生福利部食品藥物管理署「健康食品資料集」（資料集編號 19）
授權：政府資料開放授權條款-第1版
"""
import io
import json
import os
import re
import sys
import zipfile
from urllib.request import urlopen

# 主控台預設 cp950，印出中文品名會讓整支腳本 crash，先轉成 UTF-8
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

DATASET_ID = 19
URL = 'https://data.fda.gov.tw/data/opendata/export/%d/json' % DATASET_ID
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), '健康食品許可證.json')

# 健康食品管理法第 3 條授權公告的法定保健功效項目。
# 資料裡同一個功效會有「調節血脂」與「調節血脂功能」兩種寫法，
# 也會出現「紅麴（規格標準）-調節血脂」這種帶成分前綴的，統一正規化成這 13 項。
CANON = ['調節血脂', '調節血糖', '輔助調節血壓', '護肝', '免疫調節', '抗疲勞',
         '延緩衰老', '骨質保健', '牙齒保健', '胃腸功能改善', '不易形成體脂肪',
         '輔助調整過敏體質', '促進鐵吸收']


def fetch():
    raw = urlopen(URL, timeout=120).read()
    # 大型資料集會壓成 ZIP 回傳（開頭是 PK），小的直接給 JSON
    if raw[:2] == b'PK':
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            raw = z.read(z.namelist()[0])
    for enc in ('utf-8-sig', 'utf-8', 'cp950'):
        try:
            return json.loads(raw.decode(enc))
        except (UnicodeDecodeError, ValueError):
            continue
    raise SystemExit('更新失敗：TFDA 回應無法解析（編碼或格式改了？）')


def norm_effects(s):
    """把「調節血脂功能」「紅麴（規格標準）-調節血脂」正規化成法定項目名稱。"""
    out = []
    for part in re.split(r'[,、;；]', str(s or '')):
        part = part.strip()
        if not part or part.lower() == 'none':
            continue
        part = re.sub(r'^.*?（規格標準）\s*-\s*', '', part)   # 去掉成分前綴
        if part.endswith('功能') and part not in CANON:
            part = part[:-2]
        if part in CANON and part not in out:
            out.append(part)
    return out


def key(no):
    """比對鍵：(是否規格標準, 英文字母, 去前導零的數字)。實測 565 筆無撞號。"""
    m = re.search(r'第\s*([A-Za-z]?)0*(\d+)\s*號', str(no or ''))
    if not m:
        return None
    return ('規' if '健食規字' in str(no) else '般') + '|' + (m.group(1) or '').upper() + m.group(2)


def slim(rows):
    out, seen, unparsed = [], set(), []
    for r in rows:
        k = key(r.get('許可證字號'))
        if not k:
            unparsed.append(r.get('許可證字號'))
            continue
        if k in seen:
            raise SystemExit('更新失敗：許可證字號撞號 %s —— 比對鍵需要重新設計' % k)
        seen.add(k)
        out.append({
            'k': k,
            'no': str(r.get('許可證字號') or '').strip(),
            'name': str(r.get('中文品名') or '').strip(),
            'co': str(r.get('申請商') or '').strip(),
            'st': str(r.get('證況') or '').strip(),
            'date': str(r.get('核可日期') or '').strip(),
            'eff': norm_effects(r.get('保健功效')),
            'claim': str(r.get('保健功效宣稱') or '').strip(),
            'warn': str(r.get('警語') or '').strip(),
        })
    if unparsed:
        raise SystemExit('更新失敗：%d 筆許可證字號無法解析，例如 %r' % (len(unparsed), unparsed[:3]))
    return out


def main():
    print('下載 %s …' % URL)
    rows = fetch()
    recs = slim(rows)

    old = {}
    if os.path.exists(OUT):
        prev = json.loads(io.open(OUT, encoding='utf-8').read())
        old = {r['k']: r for r in prev.get('records', [])}

    added = [r for r in recs if r['k'] not in old]
    changed = [r for r in recs if r['k'] in old and r != old[r['k']]]
    removed = [k for k in old if k not in {r['k'] for r in recs}]
    print('  共 %d 筆　新增 %d　異動 %d　消失 %d' % (len(recs), len(added), len(changed), len(removed)))
    for r in added[:5]:
        print('    + %s %s' % (r['no'], r['name'][:24]))
    for r in changed[:5]:
        print('    ~ %s %s（證況 %s → %s）' % (r['no'], r['name'][:20], old[r['k']]['st'], r['st']))
    for k in removed[:5]:
        print('    - %s %s' % (old[k]['no'], old[k]['name'][:24]))

    valid = sum(1 for r in recs if r['st'] == '核可')
    print('  證況：核可 %d、其餘 %d' % (valid, len(recs) - valid))
    if len(recs) < 400:
        raise SystemExit('更新失敗：只拿到 %d 筆，明顯不對（過去約 565 筆），不覆蓋既有快照' % len(recs))

    if '--dry-run' in sys.argv:
        print('（--dry-run，未寫檔）')
        return

    # 快照日期由呼叫端指定，避免每次跑都因為日期不同而產生假異動
    stamp = None
    for i, a in enumerate(sys.argv):
        if a == '--date' and i + 1 < len(sys.argv):
            stamp = sys.argv[i + 1]
    if not stamp:
        import datetime
        stamp = datetime.date.today().isoformat()

    doc = {
        '_note': '衛福部食藥署「健康食品資料集」快照。由 實作作業/update_healthfood.py 產生，'
                 '請不要手改。欄位 eff 是正規化後的法定保健功效項目，claim 是核准的'
                 '保健功效宣稱原文——那段原文才是判斷廣告有沒有逾越核准範圍的依據。',
        '_source': 'https://data.fda.gov.tw/data/opendata/export/%d/json' % DATASET_ID,
        '_dataset': '衛生福利部食品藥物管理署　健康食品資料集（編號 %d）' % DATASET_ID,
        '_license': '政府資料開放授權條款-第1版',
        '_snapshot_date': stamp,
        '_count': len(recs),
        '_canonical_effects': CANON,
        'records': recs,
    }
    io.open(OUT, 'w', encoding='utf-8', newline='').write(
        json.dumps(doc, ensure_ascii=False, indent=1))
    print('已寫入 %s（%.0f KB）' % (OUT, os.path.getsize(OUT) / 1024.0))
    print('提醒：接著要跑 build.py 把快照注入前端。')


if __name__ == '__main__':
    main()
