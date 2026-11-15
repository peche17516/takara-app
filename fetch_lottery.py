#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全期間累積型・宝くじ当選番号自動収集スクリプト (fetch_lottery.py)
- 初回セットアップ時（蓄積数が少ない場合）は、みずほ銀行のバックナンバー・過去アーカイブCSV等を
  自動的に遡って一括取得（フルブートストラップ）し、第1回〜最新回までの全期間データを初期格納します。
- 2回目以降の定期実行時は、既存の全期間データを保持したまま最新回号だけを差分追加し、
  101回、102回…と永遠に累積進化させ続けます。
- キャリーオーバー金額は、一覧用の簡略表記（例: 3.4億）と公式詳細バナー用の正確な1円単位表記
  （例: 342,185,400円）の双方を記録します。
"""

import csv
import io
import json
import os
import re
import time
from datetime import datetime
import urllib.request

HISTORY_FILE = "lottery_history.json"
LOTTERY_TYPES = ["numbers3", "numbers4", "miniloto", "loto6", "loto7", "bingo5"]

LATEST_SOURCES = {
    "loto6": "https://www.mizuhobank.co.jp/retail/takarakuji/check/loto/loto6/index.html",
    "loto7": "https://www.mizuhobank.co.jp/retail/takarakuji/check/loto/loto7/index.html",
    "miniloto": "https://www.mizuhobank.co.jp/retail/takarakuji/check/loto/miniloto/index.html",
    "bingo5": "https://www.mizuhobank.co.jp/retail/takarakuji/check/bingo/bingo5/index.html",
    "numbers3": "https://www.mizuhobank.co.jp/retail/takarakuji/check/numbers/numbers3/index.html",
    "numbers4": "https://www.mizuhobank.co.jp/retail/takarakuji/check/numbers/numbers4/index.html",
}

BACKNUMBER_INDEX_SOURCES = {
    "loto6": "https://www.mizuhobank.co.jp/retail/takarakuji/check/loto/backnumber/loto6.html",
    "loto7": "https://www.mizuhobank.co.jp/retail/takarakuji/check/loto/backnumber/loto7.html",
    "miniloto": "https://www.mizuhobank.co.jp/retail/takarakuji/check/loto/backnumber/miniloto.html",
    "bingo5": "https://www.mizuhobank.co.jp/retail/takarakuji/check/bingo/backnumber/bingo5.html",
    "numbers3": "https://www.mizuhobank.co.jp/retail/takarakuji/check/numbers/backnumber/numbers3.html",
    "numbers4": "https://www.mizuhobank.co.jp/retail/takarakuji/check/numbers/backnumber/numbers4.html",
}

WEEKDAYS_JP = ["月", "火", "水", "木", "金", "土", "日"]


def load_existing_cumulative_db():
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
        except Exception as e:
            print(f"[WARN] 既存JSON読み込みエラーのため新規初期化: {e}")

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


def fetch_bytes(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) LotteryCumulativeBot/3.0"
        },
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        return resp.read()


def fetch_text(url):
    raw = fetch_bytes(url)
    for enc in ("utf-8", "shift_jis", "cp932"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def format_jp_date(y, m, d):
    dt = datetime(int(y), int(m), int(d))
    return f"{dt.year}/{dt.month:02d}/{dt.day:02d}({WEEKDAYS_JP[dt.weekday()]})"


def format_compact_yen(yen):
    if not yen or yen <= 0:
        return None
    if yen >= 100000000:
        oku_float = round(yen / 100000000, 1)
        return f"{oku_float:.1f}億"
    return f"{yen // 10000:,}万"


def format_exact_yen(yen):
    if not yen or yen <= 0:
        return None
    return f"{yen:,}円"


def build_record(lotto_type, round_num, date_formatted, nums, carryover_yen=None):
    rec = None
    if lotto_type == "numbers3" and len(nums) >= 3:
        rec = {"round": round_num, "date": date_formatted, "numbers": nums[:3], "bonus": []}
    elif lotto_type == "numbers4" and len(nums) >= 4:
        rec = {"round": round_num, "date": date_formatted, "numbers": nums[:4], "bonus": []}
    elif lotto_type == "miniloto" and len(nums) >= 6:
        rec = {"round": round_num, "date": date_formatted, "numbers": sorted(nums[:5]), "bonus": [nums[5]]}
    elif lotto_type == "loto6" and len(nums) >= 7:
        rec = {"round": round_num, "date": date_formatted, "numbers": sorted(nums[:6]), "bonus": [nums[6]]}
    elif lotto_type == "loto7" and len(nums) >= 9:
        rec = {"round": round_num, "date": date_formatted, "numbers": sorted(nums[:7]), "bonus": sorted(nums[7:9])}
    elif lotto_type == "bingo5" and len(nums) >= 8:
        rec = {"round": round_num, "date": date_formatted, "numbers": nums[:8], "bonus": []}

    if rec and carryover_yen and carryover_yen > 0 and lotto_type in ("loto6", "loto7"):
        rec["carryover"] = format_compact_yen(carryover_yen)
        rec["carryoverExact"] = format_exact_yen(carryover_yen)
    return rec


def parse_draws_from_html(lotto_type, html_text):
    extracted = []
    carryover = None

    co_match = re.search(r"キャリーオーバー[^\d]*([\d,]+)円", html_text)
    if co_match:
        yen = int(co_match.group(1).replace(",", ""))
        if yen > 0:
            carryover = f"{yen:,}円"

    round_blocks = re.findall(
        r"第(\d+)回.*?(\d{4})年(\d{1,2})月(\d{1,2})日(.*?)(?=第\d+回|</tr>|$)",
        html_text,
        re.DOTALL,
    )

    for r_str, y_str, m_str, d_str, body in round_blocks:
        round_num = int(r_str)
        date_formatted = format_jp_date(y_str, m_str, d_str)
        nums = [int(x) for x in re.findall(r">\s*(\d{1,2})\s*<", body)]
        block_co_match = re.search(r"キャリーオーバー[^\d]*([\d,]+)円", body)
        block_co_yen = int(block_co_match.group(1).replace(",", "")) if block_co_match else None
        rec = build_record(lotto_type, round_num, date_formatted, nums, block_co_yen)
        if rec:
            extracted.append(rec)

    return extracted, carryover


def parse_draws_from_csv(lotto_type, csv_text):
    extracted = []
    reader = csv.reader(io.StringIO(csv_text))
    for row in reader:
        if not row or len(row) < 5:
            continue
        r_match = re.search(r"第(\d+)回", row[0])
        d_match = re.search(r"(\d{4})[/年-](\d{1,2})[/月-](\d{1,2})", row[1])
        if not r_match or not d_match:
            continue
        round_num = int(r_match.group(1))
        date_formatted = format_jp_date(d_match.group(1), d_match.group(2), d_match.group(3))

        nums = []
        for cell in row[2:]:
            for tok in re.findall(r"\d+", cell):
                nums.append(int(tok))
        rec = build_record(lotto_type, round_num, date_formatted, nums)
        if rec:
            extracted.append(rec)
    return extracted


def bootstrap_full_archive(lotto_type):
    all_records = []
    index_url = BACKNUMBER_INDEX_SOURCES.get(lotto_type)
    if not index_url:
        return all_records

    print(f"[BOOTSTRAP] {lotto_type} の過去全期間アーカイブを一括探索中...")
    try:
        index_html = fetch_text(index_url)
        links = re.findall(r'href=["\']([^"\']*(?:backnumber|detail|csv)[^"\']*\.(?:html|csv))["\']', index_html, re.IGNORECASE)
        base_domain = "https://www.mizuhobank.co.jp"
        visited = set()

        for href in links:
            if href.startswith("http"):
                full_url = href
            elif href.startswith("/"):
                full_url = base_domain + href
            else:
                full_url = index_url.rsplit("/", 1)[0] + "/" + href

            if full_url in visited:
                continue
            visited.add(full_url)

            try:
                content = fetch_text(full_url)
                if full_url.lower().endswith(".csv"):
                    recs = parse_draws_from_csv(lotto_type, content)
                else:
                    recs, _ = parse_draws_from_html(lotto_type, content)
                all_records.extend(recs)
                time.sleep(0.25)
            except Exception:
                continue

        idx_recs, _ = parse_draws_from_html(lotto_type, index_html)
        all_records.extend(idx_recs)
    except Exception as e:
        print(f"[WARN] {lotto_type} アーカイブ一括取得中に一部スキップ: {e}")

    return all_records


def merge_cumulative(existing_list, new_items):
    by_round = {item["round"]: item for item in existing_list}
    added_count = 0
    for item in new_items:
        if item["round"] not in by_round:
            added_count += 1
        by_round[item["round"]] = item

    merged = sorted(by_round.values(), key=lambda x: x["round"], reverse=True)
    return merged, added_count


def main():
    db = load_existing_cumulative_db()
    db["updatedAt"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for lotto_type, url in LATEST_SOURCES.items():
        if len(db[lotto_type]) < 50:
            archive_draws = bootstrap_full_archive(lotto_type)
            if archive_draws:
                db[lotto_type], boot_added = merge_cumulative(db[lotto_type], archive_draws)
                print(f"[BOOTSTRAP完了] {lotto_type}: 過去アーカイブ {boot_added}回分を初期格納しました")

        try:
            html = fetch_text(url)
            new_draws, carryover = parse_draws_from_html(lotto_type, html)
            merged, added = merge_cumulative(db[lotto_type], new_draws)
            db[lotto_type] = merged
            if carryover is not None:
                db["carryovers"][lotto_type] = carryover
            print(f"[OK] {lotto_type}: 新規追加 {added}件 / 累積総数 {len(merged)}回分")
        except Exception as e:
            print(f"[INFO] {lotto_type} 最新取得スキップ（既存累積 {len(db[lotto_type])}回分を保持）: {e}")

    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

    print(f"[DONE] 全期間累積データベース ({HISTORY_FILE}) の更新が完了しました。")


if __name__ == "__main__":
    main()
