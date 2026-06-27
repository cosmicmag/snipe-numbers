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
import re, json, sys, urllib.request, urllib.parse, http.cookiejar

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


_API_QUERIES = [""] + [str(d) for d in range(10)]


def _api_session(filt: str = "auction"):
    """GET страницы numbers -> cookie-сессия + api-hash (нужен для /api пагинации)."""
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.addheaders = [("User-Agent", UA)]
    page = op.open(f"{BASE}/numbers?filter={filt}", timeout=20).read().decode("utf-8", "replace")
    m = re.search(r'apiUrl":"\\/api\?hash=([a-f0-9]+)', page)
    if not m:
        raise RuntimeError("Fragment: api-hash не найден (поменялась вёрстка?)")
    return op, m.group(1)


def _parse_cards(html: str) -> list[dict]:
    """Распарсить строки таблицы /api в унифицированные dict'ы (одна <tr> = один лот)."""
    out = []
    for row in re.findall(r'<tr class="tm-row-selectable">(.*?)</tr>', html, re.S):
        m_id = re.search(r'/number/(\d+)', row)
        m_price = re.search(r'icon-ton">([\d,]+)', row)
        if not (m_id and m_price):
            continue
        nid = m_id.group(1)
        m_val = re.search(r'tm-value">(\+888[^<]*)<', row)
        number = m_val.group(1).strip() if m_val else "+888 " + nid[3:]
        m_exp = re.search(r'datetime="([^"]+)"|data-expires="(\d+)"', row)
        # "For sale" = fix-price (купить сразу); иначе — аукцион (ставка/min-bid).
        # NB: tm-timer есть и у fix-price (relative "listed ago") — на него не опираемся.
        is_fixed = "For sale" in row
        out.append({
            "id": nid,
            "number": number,
            "digits": re.sub(r"\D", "", number)[-8:],
            "price": float(m_price.group(1).replace(",", "")),
            "sale_type": "fixed" if is_fixed else "auction",
            "time_left": "",
            "expires": (m_exp.group(1) or m_exp.group(2)) if m_exp else "",
            "url": f"{BASE}/number/{nid}",
        })
    return out


def _api_fetch(filt: str, sorts: tuple[str, ...], max_rows: int) -> list[dict]:
    """Полный фид filter через внутренний /api с пагинацией по query (keyless)."""
    op, hash_ = _api_session(filt)
    seen: dict[str, dict] = {}
    for q in _API_QUERIES:
        for srt in sorts:
            data = urllib.parse.urlencode({
                "type": "numbers", "query": q, "filter": filt,
                "sort": srt, "method": "searchAuctions",
            }).encode()
            req = urllib.request.Request(f"{BASE}/api?hash={hash_}", data=data, headers={
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": f"{BASE}/numbers",
            })
            try:
                html = json.loads(op.open(req, timeout=20).read().decode()).get("html", "")
            except Exception:
                continue
            for c in _parse_cards(html):
                seen.setdefault(c["id"], c)
            if len(seen) >= max_rows:
                break
        if len(seen) >= max_rows:
            break
    return list(seen.values())


def fetch_auctions(max_rows: int = 400) -> list[dict]:
    """Фид аукционов (filter=auction), включая премиум-лоты. price = текущая ставка/мин-бид."""
    return _api_fetch("auction", ("ending", "price_asc"), max_rows)


def fetch_sale_book(max_rows: int = 800) -> list[dict]:
    """
    Полный аск-стакан (filter=sale): и fixed-price, и аукционы.
    Нужен, чтобы посчитать РЕАЛЬНЫЙ floor по каждому классу паттерна (по fixed-price),
    т.е. за сколько ты реально перевыставишь номер — а не по выдуманной формуле.
    """
    return _api_fetch("sale", ("price_asc", "price_desc"), max_rows)


if __name__ == "__main__":
    ls = fetch_listings(int(sys.argv[1]) if len(sys.argv) > 1 else 30)
    print(f"fetched {len(ls)} listings (cheapest first)\n")
    for l in ls[:30]:
        print(f"  {l['price']:>7.0f} TON  {l['number']:18s} {l['sale_type']:7s} {l['time_left']}")
    fixed = [l for l in ls if l["sale_type"] == "fixed"]
    print(f"\nfixed-price (instant-buy): {len(fixed)}/{len(ls)}")
    json.dump(ls, open("/tmp/frag_listings.json", "w"), indent=1)

    aucs = fetch_auctions()
    print(f"\nauctions feed: {len(aucs)} лотов (premium включая)")
    for a in sorted(aucs, key=lambda x: x["price"])[:15]:
        print(f"  bid {a['price']:>8.0f} TON  {a['number']:18s} ends {a['expires']}")
