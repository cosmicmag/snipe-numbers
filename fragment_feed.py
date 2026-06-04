#!/usr/bin/env python3
"""
Keyless-скрапер листингов +888 номеров с Fragment.
Возвращает cheapest-first список: number, digits, price(TON), sale_type, time_left, url.

Fragment отдаёт HTML-таблицу (sort=price_asc&filter=sale), auth не нужен.
Типы лотов:
  - "For sale"  → fix-price (можно купить сразу)
  - таймер + "Will close soon" → аукцион (мгновенно не купить)
"""
from __future__ import annotations
import re, json, sys, urllib.request

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/148.0.0.0 Safari/537.36"
BASE = "https://fragment.com"


def _get(url: str, timeout=20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


_ROW = re.compile(r'<tr class="tm-row-selectable">(.*?)</tr>', re.S)


def fetch_listings(max_rows: int = 200) -> list[dict]:
    html = _get(f"{BASE}/numbers?sort=price_asc&filter=sale")
    out = []
    for body in _ROW.finditer(html):
        row = body.group(1)
        m_id = re.search(r'/number/(\d+)', row)
        m_val = re.search(r'tm-value">(\+888[^<]*)</div>', row)
        m_price = re.search(r'icon-ton">([\d,]+)</div>', row)
        if not (m_id and m_val and m_price):
            continue
        timer = re.search(r'data-relative="short-text">([^<]+)</time>', row)
        is_auction = "tm-timer" in row
        out.append({
            "id": m_id.group(1),
            "number": m_val.group(1).strip(),
            "digits": re.sub(r"\D", "", m_val.group(1))[-8:],
            "price": float(m_price.group(1).replace(",", "")),
            "sale_type": "auction" if is_auction else "fixed",
            "time_left": timer.group(1) if timer else "",
            "url": f"{BASE}/number/{m_id.group(1)}",
        })
        if len(out) >= max_rows:
            break
    return out


if __name__ == "__main__":
    ls = fetch_listings(int(sys.argv[1]) if len(sys.argv) > 1 else 30)
    print(f"fetched {len(ls)} listings (cheapest first)\n")
    for l in ls[:30]:
        print(f"  {l['price']:>7.0f} TON  {l['number']:18s} {l['sale_type']:7s} {l['time_left']}")
    fixed = [l for l in ls if l["sale_type"] == "fixed"]
    print(f"\nfixed-price (instant-buy): {len(fixed)}/{len(ls)}")
    json.dump(ls, open("/tmp/frag_listings.json", "w"), indent=1)
