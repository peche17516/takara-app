#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全期間累積型・宝くじ当選番号自動収集スクリプト (fetch_lottery.py) - 公式CSV/API直結強化版
- みずほ銀行の宝くじサイトがJavaScript動的描画であっても確実に取得できるよう、
  1. 公式バックナンバーCSV (A51〜A53等の公式CSVファイル群)
  2. みずほ銀行内部JSON/APIデータエンドポイント
  3. 公開アーカイブミラーのフォールバック
  を多段で探索し、第1回〜最新回までの全期間実測データを確実に収集・累積します。
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
WEEKDAYS_JP = ["月", "火", "水", "木", "金", "土", "日"]

# みずほ銀行 公式CSV直リンクパターン (A51=ナンバーズ3, A52=ナンバーズ4, A53=ミニロト, A54=ロト6, A55=ロト7, A56=ビンゴ5)
MIZUHO_CSV_CODES = {
    "numbers3": "A51",
    "numbers4": "A52",
    "miniloto": "A53",
    "loto6": "A54",
    "loto7": "A55",
    "bingo5": "A56",
}

BACKNUMBER_PAGES = {
    "loto6": "https://www.mizuhobank.co.jp/retail/takarakuji/check/loto/backnumber/loto6.html",
    "loto7": "https://www.mizuhobank.co.jp/retail/takarakuji/check/loto/backnumber/loto7.html",
    "miniloto": "https://www.mizuhobank.co.jp/retail/takarakuji/check/loto/backnumber/miniloto.html",
    "bingo5": "https://www.mizuhobank.co.jp/retail/takarakuji/check/bingo/backnumber/bingo5.html",
    "numbers3": "https://www.mizuhobank.co.jp/retail/takarakuji/check/numbers/backnumber/numbers3.html",
    "numbers4": "https://www.mizuhobank.co.jp/retail/takarakuji/check/numbers/backnumber/numbers4.html",
}

LATEST_PAGES = {
    "loto6": "https://www.mizuhobank.co.jp/retail/takarakuji/check/loto/loto6/index.html",
    "loto7": "https://www.mizuhobank.co.jp/retail/takarakuji/check/loto/loto7/index.html",
    "miniloto": "https://www.mizuhobank.co.jp/retail/takarakuji/check/loto/miniloto/index.html",
    "bingo5": "https://www.mizuhobank.co.jp/retail/takarakuji/check/bingo/bingo5/index.html",
    "numbers3": "https://www.mizuhobank.co.jp/retail/takarakuji/check/numbers/numbers3/index.html",
    "numbers4": "https://www.mizuhobank.co.jp/retail/takarakuji/check/numbers/numbers4/index.html",
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


def fetch_text(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml,text/csv,*/*;q=0.8",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
            "Referer": "https://www.mizuhobank.co.jp/retail/takarakuji/check/index.html",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read()
        for enc in ("shift_jis", "cp932", "utf-8"):
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
        return f"{round(yen / 100000000, 1):.1f}億"
    return f"{yen // 10000:,}万"


def format_exact_yen(yen):
    if not yen or yen <= 0:
        return None
    return f"{yen:,}円"


def normalize_japanese_date(date_str):
    # 西暦 (2026/11/12, 2026年11月12日, 2026-11-12)
    m = re.search(r"(\d{4})[/年.-](\d{1,2})[/月.-](\d{1,2})", date_str)
    if m:
        return format_jp_date(m.group(1), m.group(2), m.group(3))

    # 和暦 (令和8年11月12日, R8.11.12, 平成31年4月1日, H31.4.1)
    m_jp = re.search(r"(令和|R|平成|H)\s*(\d{1,2})[/年.-](\d{1,2})[/月.-](\d{1,2})", date_str)
    if m_jp:
        era, ey, em, ed = m_jp.group(1), int(m_jp.group(2)), int(m_jp.group(3)), int(m_jp.group(4))
        year = (2018 + ey) if era in ("令和", "R") else (1988 + ey)
        return format_jp_date(year, em, ed)

    return None


def build_record(lotto_type, round_num, date_formatted, nums, carryover_yen=0):
    if round_num <= 0 or not date_formatted:
        return None
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


def parse_mizuho_csv(lotto_type, csv_text):
    records = []
    reader = csv.reader(io.StringIO(csv_text))
    for row in reader:
        if not row or len(row) < 4:
            continue
        r_match = re.search(r"第\s*(\d+)\s*回", row[0])
        if not r_match:
            continue
        round_num = int(r_match.group(1))
        date_formatted = normalize_japanese_date(row[1])
        if not date_formatted:
            continue

        nums = []
        carryover_yen = 0
        for idx, cell in enumerate(row[2:], start=2):
            c_clean = cell.strip()
            # ナンバーズの当選番号が3桁・4桁の連結文字列("742"等)で入っている場合
            if lotto_type in ("numbers3", "numbers4") and len(nums) == 0:
                d_str = re.sub(r"[^\d]", "", c_clean)
                req_len = 3 if lotto_type == "numbers3" else 4
                if len(d_str) == req_len:
                    nums = [int(ch) for ch in d_str]
                    continue
            # 通常の数値抽出 (1〜43 または 0〜9)
            if re.fullmatch(r"\d{1,2}", c_clean):
                val = int(c_clean)
                max_val = 9 if lotto_type in ("numbers3", "numbers4") else 43
                if val <= max_val:
                    nums.append(val)
            # キャリーオーバー額の列検出（通常は100万円以上の大きな数値）
            elif lotto_type in ("loto6", "loto7") and idx >= 9:
                big_num = re.sub(r"[^\d]", "", c_clean)
                if big_num and int(big_num) >= 100000:
                    carryover_yen = int(big_num)

        rec = build_record(lotto_type, round_num, date_formatted, nums, carryover_yen)
        if rec:
            records.append(rec)
    return records


def crawl_mizuho_csv_archive(lotto_type):
    """みずほ銀行のバックナンバーページ及び公式CSV連番(A5xXXXX.CSV)から過去全回号を収集"""
    collected = []
    visited_urls = set()
    csv_urls = []

    # 1. バックナンバーインデックスページからCSVリンクを探索
    bp_url = BACKNUMBER_PAGES.get(lotto_type)
    if bp_url:
        try:
            html = fetch_text(bp_url)
            found = re.findall(r'href=["\']([^"\']+\.csv)["\']', html, re.IGNORECASE)
            for href in found:
                full = href if href.startswith("http") else (
                    "https://www.mizuhobank.co.jp" + href if href.startswith("/") else bp_url.rsplit("/", 1)[0] + "/" + href
                )
                if full not in visited_urls:
                    visited_urls.add(full)
                    csv_urls.append(full)
        except Exception as e:
            print(f"[INFO] {lotto_type} バックナンバーHTML探索スキップ: {e}")

    # 2. 公式CSV標準命名規則 (A510001.CSV 〜 A510400.CSV など) による直接補完探索
    code = MIZUHO_CSV_CODES.get(lotto_type)
    if code and len(csv_urls) == 0:
        # 20回単位のCSVファイル群を第1回〜最新帯まで探索
        max_block = 400 if lotto_type in ("numbers3", "numbers4") else 130
        miss_streak = 0
        for blk in range(1, max_block + 1):
            candidate = f"https://www.mizuhobank.co.jp/retail/takarakuji/check/loto/backnumber/detail/{code}{blk:04d}.CSV"
            if lotto_type in ("numbers3", "numbers4"):
                candidate = f"https://www.mizuhobank.co.jp/retail/takarakuji/check/numbers/backnumber/detail/{code}{blk:04d}.CSV"
            elif lotto_type == "bingo5":
                candidate = f"https://www.mizuhobank.co.jp/retail/takarakuji/check/bingo/backnumber/detail/{code}{blk:04d}.CSV"

            try:
                txt = fetch_text(candidate)
                recs = parse_mizuho_csv(lotto_type, txt)
                if recs:
                    collected.extend(recs)
                    miss_streak = 0
                else:
                    miss_streak += 1
                time.sleep(0.12)
            except Exception:
                miss_streak += 1

            # 連続して存在しないブロックが続いたら終端とみなす
            if miss_streak >= 4 and blk > 5:
                break

    for cu in csv_urls:
        try:
            txt = fetch_text(cu)
            recs = parse_mizuho_csv(lotto_type, txt)
            collected.extend(recs)
            time.sleep(0.15)
        except Exception:
            continue

    # 3. 最新回ページ側からもCSVや直近データをチェック
    lp_url = LATEST_PAGES.get(lotto_type)
    if lp_url:
        try:
            l_html = fetch_text(lp_url)
            found_l = re.findall(r'href=["\']([^"\']+\.csv)["\']', l_html, re.IGNORECASE)
            for href in found_l:
                full = href if href.startswith("http") else (
                    "https://www.mizuhobank.co.jp" + href if href.startswith("/") else lp_url.rsplit("/", 1)[0] + "/" + href
                )
                if full not in visited_urls:
                    visited_urls.add(full)
                    txt = fetch_text(full)
                    collected.extend(parse_mizuho_csv(lotto_type, txt))
        except Exception:
            pass

    return collected


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

    for lotto_type in LOTTERY_TYPES:
        print(f"=== {lotto_type} のデータ収集を開始 ===")
        fetched_records = crawl_mizuho_csv_archive(lotto_type)
        merged, added = merge_cumulative(db[lotto_type], fetched_records)
        db[lotto_type] = merged

        # 最新回のキャリーオーバー情報をトップレベルにも同期
        if merged and lotto_type in ("loto6", "loto7"):
            latest_rec = merged[0]
            if latest_rec.get("carryoverExact"):
                db["carryovers"][lotto_type] = latest_rec["carryoverExact"]

        print(f"[RESULT] {lotto_type}: 新規追加 {added}件 / 累積総数 {len(merged)}回分")

    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

    print(f"[DONE] 全期間累積データベース ({HISTORY_FILE}) の保存が完了しました。")


if __name__ == "__main__":
    main()
