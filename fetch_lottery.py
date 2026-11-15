#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全期間累積型・宝くじ当選番号自動収集スクリプト (fetch_lottery.py)
【真・第1回〜最新回 全歴史完全網羅 ＆ 毎日差分累積版】

データソース:
- ロト6 / ロト7 / ミニロト / ナンバーズ3 / ナンバーズ4: 楽天×宝くじ 公開アーカイブ（目次リンク直接抽出）
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
        "detail_prefix": "loto6_detail",
        "main_count": 6,
        "has_bonus": True,
    },
    "loto7": {
        "latest_url": "https://takarakuji.rakuten.co.jp/backnumber/loto7/",
        "past_index_url": "https://takarakuji.rakuten.co.jp/backnumber/loto7_past/",
        "detail_prefix": "loto7_detail",
        "main_count": 7,
        "has_bonus": True,
    },
    "miniloto": {
        "latest_url": "https://takarakuji.rakuten.co.jp/backnumber/miniloto/",
        "past_index_url": "https://takarakuji.rakuten.co.jp/backnumber/miniloto_past/",
        "detail_prefix": "miniloto_detail",
        "main_count": 5,
        "has_bonus": True,
    },
    "numbers3": {
        "latest_url": "https://takarakuji.rakuten.co.jp/backnumber/numbers3/",
        "past_index_url": "https://takarakuji.rakuten.co.jp/backnumber/numbers3_past/",
        "detail_prefix": "numbers3_detail",
        "main_count": 3,
        "has_bonus": False,
    },
    "numbers4": {
        "latest_url": "https://takarakuji.rakuten.co.jp/backnumber/numbers4/",
        "past_index_url": "https://takarakuji.rakuten.co.jp/backnumber/numbers4_past/",
        "detail_prefix": "numbers4_detail",
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
                time.sleep(0.4)
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
    clean = re.sub(r"<script[\s\S]*?</script>", " ", html_text, flags=re.IGNORECASE)
    clean = re.sub(r"<style[\s\S]*?</style>", " ", clean, flags=re.IGNORECASE)
    clean = re.sub(r"<[^>]+>", " ", clean)
    clean = re.sub(r"\s+", " ", clean)

    results = []

    if ltype in ("numbers3", "numbers4"):
        digits_len = cfg["main_count"]
        pattern = re.compile(
            r"第0*(\d+)回\s*抽せん日\s*(\d{4})/(\d{1,2})/(\d{1,2})\s*(?:ナンバーズ[34３４]|当せん番号)\s*(\d{" + str(digits_len) + r"})"
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

    blocks = re.split(r"(?=第0*\d+回\s*抽せん日)", clean)
    bonus_expected = 2 if ltype == "loto7" else 1

    for blk in blocks:
        m_head = re.match(r"第0*(\d+)回\s*抽せん日\s*(\d{4})/(\d{1,2})/(\d{1,2})", blk)
        if not m_head:
            continue
        r_num = int(m_head.group(1))
        d_str = format_jp_date(m_head.group(2), m_head.group(3), m_head.group(4))

        m_nums = re.search(
            r"本数字\s*([\d\s\-]+?)\s*ボーナス数字\s*([\(\)\d\s\-]+)",
            blk,
        )
        if not m_nums:
            continue

        main_list = [int(x) for x in re.findall(r"\d+", m_nums.group(1))]
        bonus_list = [int(x) for x in re.findall(r"\d+", m_nums.group(2))]

        if len(main_list) < cfg["main_count"] or len(bonus_list) < bonus_expected:
            continue

        rec = {
            "round": r_num,
            "date": d_str,
            "numbers": sorted(main_list[: cfg["main_count"]]),
            "bonus": sorted(bonus_list[:bonus_expected]),
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

    latest_html = fetch_html(cfg["latest_url"])
    latest_items = parse_rakuten_html(ltype, latest_html)
    collected.extend(latest_items)

    past_index_html = fetch_html(cfg["past_index_url"])
    month_links = set()
    detail_links = set()

    if past_index_html:
        month_links = set(re.findall(rf"/backnumber/{ltype}/\d{{6}}/?", past_index_html))
        detail_links = set(re.findall(rf"/backnumber/{cfg['detail_prefix']}/\d+-\d+/?", past_index_html))

    target_urls = set()

    if len(existing_rounds) >= 350:
        for path in sorted(month_links, reverse=True)[:3]:
            u = "https://takarakuji.rakuten.co.jp" + path
            if not u.endswith("/"):
                u += "/"
            target_urls.add(u)
    else:
        for path in sorted(month_links):
            u = "https://takarakuji.rakuten.co.jp" + path
            if not u.endswith("/"):
                u += "/"
            target_urls.add(u)

        for path in sorted(detail_links):
            u = "https://takarakuji.rakuten.co.jp" + path
            if not u.endswith("/"):
                u += "/"
            target_urls.add(u)

        if not detail_links:
            fallback_max = {
                "numbers3": 7200,
                "numbers4": 7200,
                "loto6": 2200,
                "miniloto": 1450,
                "loto7": 750,
            }.get(ltype, 2500)
            for start in range(1, fallback_max, 20):
                end = start + 19
                target_urls.add(
                    f"https://takarakuji.rakuten.co.jp/backnumber/{cfg['detail_prefix']}/{start:04d}-{end:04d}/"
                )

    url_list = sorted(target_urls)
    print(f"  -> {ltype}: {len(url_list)}ページのアーカイブを取得中（目次抽出: 月別{len(month_links)}件 / 詳細{len(detail_links)}件）...")

    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = {executor.submit(fetch_html, u): u for u in url_list}
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
    clean = clean.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    clean = re.sub(r"\s+", " ", clean)

    results = []
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
    latest_html = fetch_html("https://takarakuji-loto.jp/bingo5/")
    collected.extend(parse_bingo5_html(latest_html))

    pages = set()
    for start in range(1, 550, 10):
        pages.add(f"result{start:04d}.html")

    target_urls = [f"https://takarakuji-loto.jp/bingo5/{p}" for p in sorted(pages)]
    if len(existing_rounds) >= 400:
        target_urls = target_urls[-8:]

    print(f"  -> bingo5: {len(target_urls)}ページのアーカイブを取得中...")
    with ThreadPoolExecutor(max_workers=10) as executor:
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
