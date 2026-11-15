#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全期間累積型・宝くじ当選番号自動収集スクリプト (fetch_lottery.py)
【海外IPブロック回避・国内公開アーカイブ直結・全期間累積版】

データソース:
- ロト6 / ロト7 / ミニロト / ナンバーズ3 / ナンバーズ4: 楽天×宝くじ 公開アーカイブ（第1回〜最新回）
- ビンゴ5: 数字選択式宝くじアーカイブ（第1回〜最新回）
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import re
import time
from datetime import datetime
import urllib.request

HISTORY_FILE = "lottery_history.json"
LOTTERY_TYPES = ["numbers3", "numbers4", "miniloto", "loto6", "loto7", "bingo5"]
WEEKDAYS_JP = ["月", "火", "水", "木", "金", "土", "日"]

RAKUTEN_CONFIG = {
    "loto6": {
        "latest_url": "https://takarakuji.rakuten.co.jp/backnumber/loto6/",
        "past_index_url": "https://takarakuji.rakuten.co.jp/backnumber/loto6_past/",
        "detail_pattern": r"/backnumber/loto6_detail/\d{4}-\d{4}/",
        "main_count": 6,
        "has_bonus": True,
    },
    "loto7": {
        "latest_url": "https://takarakuji.rakuten.co.jp/backnumber/loto7/",
        "past_index_url": "https://takarakuji.rakuten.co.jp/backnumber/loto7_past/",
        "detail_pattern": r"/backnumber/loto7_detail/\d{4}-\d{4}/",
        "main_count": 7,
        "has_bonus": True,
    },
    "miniloto": {
        "latest_url": "https://takarakuji.rakuten.co.jp/backnumber/miniloto/",
        "past_index_url": "https://takarakuji.rakuten.co.jp/backnumber/miniloto_past/",
        "detail_pattern": r"/backnumber/miniloto_detail/\d{4}-\d{4}/",
        "main_count": 5,
        "has_bonus": True,
    },
    "numbers3": {
        "latest_url": "https://takarakuji.rakuten.co.jp/backnumber/numbers3/",
        "past_index_url": "https://takarakuji.rakuten.co.jp/backnumber/numbers3_past/",
        "detail_pattern": r"/backnumber/numbers3_detail/\d{4}-\d{4}/",
        "main_count": 3,
        "has_bonus": False,
    },
    "numbers4": {
        "latest_url": "https://takarakuji.rakuten.co.jp/backnumber/numbers4/",
        "past_index_url": "https://takarakuji.rakuten.co.jp/backnumber/numbers4_past/",
        "detail_pattern": r"/backnumber/numbers4_detail/\d{4}-\d{4}/",
        "main_count": 4,
        "has_bonus": False,
    },
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


def fetch_html(url, retries=2):
    for attempt in range(retries + 1):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                if resp.status != 200:
                    continue
                raw = resp.read()
                for enc in ("utf-8", "cp932", "shift_jis", "euc_jp"):
                    try:
                        return raw.decode(enc)
                    except UnicodeDecodeError:
                        continue
                return raw.decode("utf-8", errors="ignore")
        except Exception:
            if attempt < retries:
                time.sleep(0.5)
    return ""


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


def parse_rakuten_html(ltype, html_text):
    if not html_text:
        return []

    cfg = RAKUTEN_CONFIG[ltype]
    # タグを空白に変換してテキスト構造を解析
    clean = re.sub(r"<script[\s\S]*?</script>", " ", html_text, flags=re.IGNORECASE)
    clean = re.sub(r"<style[\s\S]*?</style>", " ", clean, flags=re.IGNORECASE)
    clean = re.sub(r"<[^>]+>", " ", clean)
    clean = re.sub(r"\s+", " ", clean)

    results = []

    if ltype in ("numbers3", "numbers4"):
        # パターン: 開催回 第7114回 抽せん日 2026/11/13 当せん番号 605
        digits_len = cfg["main_count"]
        pattern = re.compile(
            r"第0*(\d+)回\s*抽せん日\s*(\d{4})/(\d{1,2})/(\d{1,2})\s*当せん番号\s*(\d{" + str(digits_len) + r"})"
        )
        for m in pattern.finditer(clean):
            r_num = int(m.group(1))
            d_str = format_jp_date(m.group(2), m.group(3), m.group(4))
            nums = [int(ch) for ch in m.group(5)]
            results.append({
                "round": r_num,
                "date": d_str,
                "numbers": nums,
                "bonus": [],
            })
        return results

    # ロト6・ロト7・ミニロト
    # ブロック単位で分割: 第XXXX回 抽せん日 YYYY/MM/DD ...
    blocks = re.split(r"(?=第0*\d+回\s*抽せん日)", clean)
    for blk in blocks:
        m_head = re.match(r"第0*(\d+)回\s*抽せん日\s*(\d{4})/(\d{1,2})/(\d{1,2})", blk)
        if not m_head:
            continue
        r_num = int(m_head.group(1))
        d_str = format_jp_date(m_head.group(2), m_head.group(3), m_head.group(4))

        m_nums = re.search(r"本数字\s*([\d\s\-]+?)\s*ボーナス数字\s*\(?([\d\s\(\)\-]+?)\)?(?:\s*1等|\s*抽せん|\s*$)", blk)
        if not m_nums:
            continue

        main_list = [int(x) for x in re.findall(r"\d+", m_nums.group(1))]
        bonus_list = [int(x) for x in re.findall(r"\d+", m_nums.group(2))]

        if len(main_list) < cfg["main_count"] or not bonus_list:
            continue

        rec = {
            "round": r_num,
            "date": d_str,
            "numbers": sorted(main_list[: cfg["main_count"]]),
            "bonus": sorted(bonus_list[: (2 if ltype == "loto7" else 1)]),
        }

        if ltype in ("loto6", "loto7"):
            m_co = re.search(r"キャリーオーバー\s*([\d,]+)\s*円", blk)
            if m_co:
                co_val = int(m_co.group(1).replace(",", ""))
                if co_val > 0:
                    rec["carryover"] = format_compact_yen(co_val)
                    rec["carryoverExact"] = format_exact_yen(co_val)

        results.append(rec)

    return results


def collect_rakuten_lottery(ltype, existing_rounds):
    cfg = RAKUTEN_CONFIG[ltype]
    collected = []

    # 1. 最新月・直近ページを取得
    latest_html = fetch_html(cfg["latest_url"])
    collected.extend(parse_rakuten_html(ltype, latest_html))

    # 2. 過去全回号一覧ページから月別・20回別リンクを取得
    past_index_html = fetch_html(cfg["past_index_url"])
    if not past_index_html:
        return collected

    # 月別URL (/backnumber/loto6/202610/ 等) と 20回別URL (/backnumber/loto6_detail/0001-0020/ 等) を抽出
    month_links = set(re.findall(rf"/backnumber/{ltype}/\d{{6}}/", past_index_html))
    detail_links = set(re.findall(cfg["detail_pattern"], past_index_html))

    target_urls = []
    # すでに過去データが十分ある場合は月別と最新detailのみ取得（高速差分更新）
    if len(existing_rounds) >= 300:
        for path in sorted(month_links, reverse=True)[:3]:
            target_urls.append("https://takarakuji.rakuten.co.jp" + path)
        for path in sorted(detail_links, reverse=True)[:3]:
            target_urls.append("https://takarakuji.rakuten.co.jp" + path)
    else:
        # 初回フルブートストラップ時は第1回〜最新回まですべて取得
        for path in sorted(month_links):
            target_urls.append("https://takarakuji.rakuten.co.jp" + path)
        for path in sorted(detail_links):
            target_urls.append("https://takarakuji.rakuten.co.jp" + path)

    print(f"  -> {ltype}: {len(target_urls)}ページのアーカイブを取得中...")

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(fetch_html, u): u for u in target_urls}
        for fut in as_completed(futures):
            html = fut.result()
            if html:
                collected.extend(parse_rakuten_html(ltype, html))

    return collected


def parse_bingo5_html(html_text):
    if not html_text:
        return []
    clean = re.sub(r"<script[\s\S]*?</script>", " ", html_text, flags=re.IGNORECASE)
    clean = re.sub(r"<style[\s\S]*?</style>", " ", clean, flags=re.IGNORECASE)
    clean = re.sub(r"<[^>]+>", " ", clean)
    # 全角数字を半角へ正規化
    clean = clean.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    clean = re.sub(r"\s+", " ", clean)

    results = []
    # パターン: 第1回 ビンゴ5 当選番号速報 抽選日 2017年4月5日 01 10 13 19 FREE 23 28 35 37
    pattern = re.compile(
        r"第0*(\d+)回\s*ビンゴ5\s*当選番号速報\s*抽選日\s*(\d{4})年(\d{1,2})月(\d{1,2})日\s*"
        r"(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+FREE\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})"
    )
    for m in pattern.finditer(clean):
        r_num = int(m.group(1))
        d_str = format_jp_date(m.group(2), m.group(3), m.group(4))
        nums = [int(m.group(i)) for i in range(5, 13)]
        results.append({
            "round": r_num,
            "date": d_str,
            "numbers": nums,
            "bonus": [],
        })
    return results


def collect_bingo5(existing_rounds):
    collected = []
    # 最新速報ページ
    latest_html = fetch_html("https://takarakuji-loto.jp/bingo5/")
    collected.extend(parse_bingo5_html(latest_html))

    # 過去一覧インデックスから resultXXXX.html を収集
    index_html = fetch_html("https://takarakuji-loto.jp/bingo5/index.html")
    if not index_html:
        index_html = latest_html

    pages = set(re.findall(r"result\d{4}\.html", index_html or ""))
    # 1〜500回まで確実にカバー
    for start in range(1, 550, 10):
        pages.add(f"result{start:04d}.html")

    target_urls = [f"https://takarakuji-loto.jp/bingo5/{p}" for p in sorted(pages)]
    if len(existing_rounds) >= 300:
        target_urls = target_urls[-8:]

    print(f"  -> bingo5: {len(target_urls)}ページのアーカイブを取得中...")
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(fetch_html, u): u for u in target_urls}
        for fut in as_completed(futures):
            html = fut.result()
            if html:
                collected.extend(parse_bingo5_html(html))

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

    for ltype in ["loto6", "loto7", "miniloto", "numbers3", "numbers4"]:
        existing_rounds = {x["round"] for x in db[ltype]}
        items = collect_rakuten_lottery(ltype, existing_rounds)
        merged, added = merge_cumulative(db[ltype], items)
        db[ltype] = merged
        if merged and ltype in ("loto6", "loto7"):
            latest_rec = merged[0]
            if latest_rec.get("carryoverExact"):
                db["carryovers"][ltype] = latest_rec["carryoverExact"]
            else:
                db["carryovers"].pop(ltype, None)
        print(f"[RESULT] {ltype}: 新規追加 {added}件 / 累積総数 {len(merged)}回分")

    # ビンゴ5
    existing_b5 = {x["round"] for x in db["bingo5"]}
    b5_items = collect_bingo5(existing_b5)
    merged_b5, added_b5 = merge_cumulative(db["bingo5"], b5_items)
    db["bingo5"] = merged_b5
    print(f"[RESULT] bingo5: 新規追加 {added_b5}件 / 累積総数 {len(merged_b5)}回分")

    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

    print(f"[DONE] 全期間累積データベース ({HISTORY_FILE}) の保存が完了しました。")


if __name__ == "__main__":
    main()
