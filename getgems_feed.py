#!/usr/bin/env python3
"""
KEYLESS Getgems-фид листингов через wallet-API (api.getgems.io/wallet/*),
который пускает по origin=walletbot.me без ключа/авторизации.

Эндпоинт: wallet/collectiblesOnSale/{collection_EQ}?count=N&cursor=...
Серверной сортировки по цене нет — пагинируем курсором и собираем стакан сами.

Это ДЕШЁВАЯ buy-витрина (то, что снайпит btcmacho), в отличие от Fragment (sell).
"""
from __future__ import annotations
import json, sys, urllib.request, urllib.parse, re

API = "https://api.getgems.io"
# EQ-адрес коллекции "Anonymous Telegram Numbers"
NUMBERS_EQ = "EQAOQdwdw8kGftJCSFgOErM1mBjYPe4DBPq8-AhF6vr9si5N"
HEADERS = {
    "accept": "application/json",
    "origin": "https://walletbot.me",
    "referer": "https://walletbot.me/",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/148.0.0.0 Safari/537.36",
}
# decimals по валютам (на номерах встречаются TON и USDT)
_DECIMALS = {"TON": 9, "USDT": 6}


def _get(path: str, timeout=15) -> dict:
    req = urllib.request.Request(API + path, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def fetch_on_sale(collection_eq: str = NUMBERS_EQ, max_items: int = 400) -> list[dict]:
    """Пройти стакан on-sale курсором, вернуть нормализованные листинги."""
    out, cursor, seen = [], "", set()
    while len(out) < max_items:
        q = f"?count=50" + (f"&cursor={urllib.parse.quote(cursor)}" if cursor else "")
        try:
            d = _get(f"/wallet/collectiblesOnSale/{collection_eq}{q}")
        except Exception as e:
            print(f"getgems feed err: {e}", file=sys.stderr)
            break
        items = d.get("collectibles", [])
        if not items:
            break
        for c in items:
            addr = c.get("address")
            if addr in seen:
                continue
            seen.add(addr)
            sp = c.get("salePreview") or {}
            cur = sp.get("currency", "TON")
            dec = _DECIMALS.get(cur, sp.get("currencyDecimals", 9))
            raw = sp.get("displayPrice", "0")
            try:
                price = int(raw) / (10 ** dec)
            except Exception:
                price = 0.0
            stype = sp.get("type", "")
            out.append({
                "address": addr,
                "number": c.get("name", ""),
                "digits": re.sub(r"\D", "", c.get("name", ""))[-8:],
                "price": price,
                "currency": cur,
                "sale_type": "fixed" if stype == "FixPriceSale" else ("auction" if stype == "Auction" else stype),
                "url": f"https://getgems.io/nft/{addr}",
            })
        cursor = d.get("cursor", "")
        if not cursor:
            break
    return out


if __name__ == "__main__":
    ls = fetch_on_sale(max_items=int(sys.argv[1]) if len(sys.argv) > 1 else 200)
    fixed_ton = sorted([l for l in ls if l["sale_type"] == "fixed" and l["currency"] == "TON"],
                       key=lambda x: x["price"])
    print(f"on-sale всего: {len(ls)}  |  fix-price TON: {len(fixed_ton)}")
    print("\n— CHEAPEST FIX-PRICE (TON), instant-buy —")
    for l in fixed_ton[:20]:
        print(f"  {l['price']:>7.0f} TON  {l['number']:18s} {l['url']}")
    autc = [l for l in ls if l["sale_type"] == "auction"]
    print(f"\nаукционов: {len(autc)} (цена/ставки тут не отображаются, displayPrice=0)")
