#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全期間累積型・宝くじ当選番号自動収集スクリプト (fetch_lottery.py)
【みずほ銀行 公式個別回号CSV（A100〜A104）直結・高速並列取得版】

- みずほ銀行公式CSVエンドポイント:
  - ナンバーズ3・4 : https://www.mizuhobank.co.jp/retail/takarakuji/numbers/csv/A100{回号:04d}.CSV
  - ミニロト       : https://www.mizuhobank.co.jp/retail/takarakuji/loto/miniloto/csv/A101{回号:04d}.CSV
  - ロト6          : https://www.mizuhobank.co.jp/retail/takarakuji/loto/loto6/csv/A102{回号:04d}.CSV
  - ロト7          : https://www.mizuhobank.co.jp/retail/takarakuji/loto/loto7/csv/A103{回号:04d}.CSV
  - ビンゴ5        : https://www.mizuhobank.co.jp/retail/takarakuji/bingo/bingo5/csv/A104{回号:04d}.CSV

- 2分探索（バイナリサーチ）で現在の最新回号を瞬時に特定し、
  未取得の回号（初回は第1回〜最新回までの全期間、2回目以降は最新の差分のみ）を
  高速並列処理で取得して lottery_history.json に永久累積保存します。
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import io
import json
import os
import re
from datetime import datetime
import urllib.request

HISTORY_FILE = "lottery_history.json"
LOTTERY_TYPES = ["numbers3", "numbers4", "miniloto", "loto6", "loto7", "bingo5"]
WEEKDAYS_JP = ["月", "火", "水", "木", "金", "土", "日"]

CSV_ENDPOINTS = {
    "numbers": "https://www.mizuhobank.co.jp/retail/takarakuji/numbers/csv/A100{round:04d}.CSV",
    "miniloto": "https://www.mizuhobank.co.jp/retail/takarakuji/loto/miniloto/csv/A101{round:04d}.CSV",
    "loto6": "https://www.mizuhobank.co.jp/retail/takarakuji/loto/loto6/csv/A102{round:04d}.CSV",
    "loto7": "https://www.mizuhobank.co.jp/retail/takarakuji/loto/loto7/csv/A103{round:04d}.CSV",
    "bingo5": "https://www.mizuhobank.co.jp/retail/takarakuji/bingo/bingo5/csv/A104{round:04d}.CSV",
}

SEARCH_BOUNDS = {
    "numbers": (6400, 9500),
    "miniloto": (1250, 2500),
    "loto6": (1900, 3500),
    "loto7": (550, 1500),
    "bingo5": (370, 1200),
}


def load_existing_db():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                for t in LOTTERY_TYPES:
                    if t not in data or not isinstance(data[t], list):
                        data[t] = []
                data.setdefault("nextDates", {})
                data.setdefault("carryovers", {})
                return data
        except Exception:
            pass
    return {
        "updatedAt": "",
        "nextDates": {},
        "carryovers": {},
        "numbers3": [],
        "numbers4": [],
        "miniloto": [],
        "loto6": [],
        "loto7": [],
        "bingo5": [],
    }


def fetch_csv_text(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept": "text/csv,text/plain,*/*",
            "Referer": "https://www.mizuhobank.co.jp/retail/takarakuji/check/index.html",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            if resp.status != 200:
                return None
            raw = resp.read()
            if not raw or len(raw) < 25:
                return None
            for enc in ("shift_jis", "cp932", "utf-8"):
                try:
                    txt = raw.decode(enc)
                    if "第" in txt and "回" in txt:
                        return txt
                except UnicodeDecodeError:
                    continue
            txt = raw.decode("utf-8", errors="ignore")
            return txt if ("第" in txt and "回" in txt) else None
    except Exception:
        return None


def format_jp_date(y, m, d):
    dt = datetime(int(y), int(m), int(d))
    return f"{dt.year}/{dt.month:02d}/{dt.day:02d}({WEEKDAYS_JP[dt.weekday()]})"


def normalize_japanese_date(text):
    m = re.search(r"(\d{4})[/年.-](\d{1,2})[/月.-](\d{1,2})", text)
    if m:
        return format_jp_date(m.group(1), m.group(2), m.group(3))
    m_jp = re.search(r"(令和|R|平成|H)\s*(\d{1,2})[/年.-](\d{1,2})[/月.-](\d{1,2})", text)
    if m_jp:
        era, ey, em, ed = m_jp.group(1), int(m_jp.group(2)), int(m_jp.group(3)), int(m_jp.group(4))
        year = (2018 + ey) if era in ("令和", "R") else (1988 + ey)
        return format_jp_date(year, em, ed)
    return None


def format_compact_yen(yen):
    if not yen or yen <= 0:
        return None
    if yen >= 100000000:
        return f"{round(yen / 100000000, 1):.1f}億"
    return f"{yen // 10000:,}万"


def format_exact_yen(yen):
    if not yen or yen <= 0:
        return None
    return f"{yen:,}円"


def find_latest_round(category):
    low, high = SEARCH_BOUNDS[category]
    template = CSV_ENDPOINTS[category]

    while low < high:
        mid = (low + high + 1) // 2
        if fetch_csv_text(template.format(round=mid)) is not None:
            low = mid
        else:
            high = mid - 1

    # 念のため少し先まで連番確認
    latest = low
    for probe in range(latest + 1, latest + 5):
        if fetch_csv_text(template.format(round=probe)) is not None:
            latest = probe
        else:
            break
    return latest


def parse_single_draw_csv(category, round_num, csv_text):
    rows = list(csv.reader(io.StringIO(csv_text)))
    date_formatted = None

    for row in rows[:5]:
        joined = ",".join(row)
        d = normalize_japanese_date(joined)
        if d:
            date_formatted = d
            break

    if not date_formatted:
        return {}

    if category == "numbers":
        n3_nums = []
        n4_nums = []
        for row in rows:
            joined = "".join(row)
            if "ナンバーズ3" in joined or "ナンバーズ３" in joined:
                for cell in row:
                    digits = re.sub(r"[^\d]", "", cell)
                    if len(digits) == 3 and "第" not in cell and "回" not in cell:
                        n3_nums = [int(c) for c in digits]
                        break
                if not n3_nums:
                    single_digits = [int(c.strip()) for c in row if re.fullmatch(r"\d", c.strip())]
                    if len(single_digits) >= 3:
                        n3_nums = single_digits[:3]
            elif "ナンバーズ4" in joined or "ナンバーズ４" in joined:
                for cell in row:
                    digits = re.sub(r"[^\d]", "", cell)
                    if len(digits) == 4 and "第" not in cell and "回" not in cell and len(digits) != 4 or (len(digits) == 4 and not digits.startswith("20") and not digits.startswith("19")):
                        n4_nums = [int(c) for c in digits]
                        break
                if not n4_nums:
                    single_digits = [int(c.strip()) for c in row if re.fullmatch(r"\d", c.strip())]
                    if len(single_digits) >= 4:
                        n4_nums = single_digits[:4]

        out = {}
        if len(n3_nums) == 3:
            out["numbers3"] = {"round": round_num, "date": date_formatted, "numbers": n3_nums, "bonus": []}
        if len(n4_nums) == 4:
            out["numbers4"] = {"round": round_num, "date": date_formatted, "numbers": n4_nums, "bonus": []}
        return out

    # ロト6・ロト7・ミニロト・ビンゴ5
    main_nums = []
    bonus_nums = []
    carryover_yen = 0

    for row in rows:
        joined = ",".join(row)
        if "本数字" in joined or "抽せん数字" in joined:
            for cell in row:
                c = cell.strip()
                if re.fullmatch(r"\d{1,2}", c):
                    val = int(c)
                    if 1 <= val <= 43:
                        main_nums.append(val)
        elif "ボーナス" in joined:
            for cell in row:
                c = cell.strip()
                if re.fullmatch(r"\d{1,2}", c):
                    val = int(c)
                    if 1 <= val <= 43:
                        bonus_nums.append(val)
        elif "キャリーオーバー" in joined:
            for cell in row:
                digits = re.sub(r"[^\d]", "", cell)
                if digits and int(digits) > 0:
                    carryover_yen = int(digits)

    rec = None
    if category == "miniloto" and len(main_nums) >= 5 and len(bonus_nums) >= 1:
        rec = {"round": round_num, "date": date_formatted, "numbers": sorted(main_nums[:5]), "bonus": [bonus_nums[0]]}
    elif category == "loto6" and len(main_nums) >= 6 and len(bonus_nums) >= 1:
        rec = {"round": round_num, "date": date_formatted, "numbers": sorted(main_nums[:6]), "bonus": [bonus_nums[0]]}
    elif category == "loto7" and len(main_nums) >= 7 and len(bonus_nums) >= 2:
        rec = {"round": round_num, "date": date_formatted, "numbers": sorted(main_nums[:7]), "bonus": sorted(bonus_nums[:2])}
    elif category == "bingo5" and len(main_nums) >= 8:
        rec = {"round": round_num, "date": date_formatted, "numbers": main_nums[:8], "bonus": []}

    if not rec:
        return {}

    if carryover_yen > 0 and category in ("loto6", "loto7"):
        rec["carryover"] = format_compact_yen(carryover_yen)
        rec["carryoverExact"] = format_exact_yen(carryover_yen)

    return {category: rec}


def fetch_and_parse_round(category, round_num):
    url = CSV_ENDPOINTS[category].format(round=round_num)
    txt = fetch_csv_text(url)
    if not txt:
        return {}
    return parse_single_draw_csv(category, round_num, txt)


def merge_cumulative(existing_list, new_items):
    by_round = {item["round"]: item for item in existing_list}
    added = 0
    for item in new_items:
        if item["round"] not in by_round:
            added += 1
        by_round[item["round"]] = item
    merged = sorted(by_round.values(), key=lambda x: x["round"], reverse=True)
    return merged, added


def main():
    db = load_existing_db()
    db["updatedAt"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    categories = ["numbers", "miniloto", "loto6", "loto7", "bingo5"]
    collected_by_type = {t: [] for t in LOTTERY_TYPES}

    for cat in categories:
        latest_round = find_latest_round(cat)
        print(f"=== {cat}: 最新回号 第{latest_round}回 を検出 ===")

        if cat == "numbers":
            existing_rounds = {x["round"] for x in db["numbers3"]} & {x["round"] for x in db["numbers4"]}
        else:
            existing_rounds = {x["round"] for x in db[cat]}

        missing_rounds = [r for r in range(1, latest_round + 1) if r not in existing_rounds]
        print(f"  -> 未取得回号: {len(missing_rounds)}件 を並列ダウンロード中...")

        with ThreadPoolExecutor(max_workers=16) as executor:
            futures = {executor.submit(fetch_and_parse_round, cat, r): r for r in missing_rounds}
            for fut in as_completed(futures):
                res_map = fut.result()
                for ltype, rec in res_map.items():
                    collected_by_type[ltype].append(rec)

    for ltype in LOTTERY_TYPES:
        merged, added = merge_cumulative(db[ltype], collected_by_type[ltype])
        db[ltype] = merged
        if merged and ltype in ("loto6", "loto7"):
            latest_rec = merged[0]
            if latest_rec.get("carryoverExact"):
                db["carryovers"][ltype] = latest_rec["carryoverExact"]
            else:
                db["carryovers"].pop(ltype, None)
        print(f"[RESULT] {ltype}: 新規追加 {added}件 / 累積総数 {len(merged)}回分")

    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

    print(f"[DONE] 全期間累積データベース ({HISTORY_FILE}) の保存が完了しました。")


if __name__ == "__main__":
    main()
