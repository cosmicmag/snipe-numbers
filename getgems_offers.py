#!/usr/bin/env python3
"""
Стакан collection-офферов (бидов) на коллекцию через авторизованный getgems.io/graphql.
Без авторизации режут (NO_SCRAPPERS) — нужна сессия (GG_AUTH_TOKEN + GG_JWT из env).

Возвращает офферы [{price, net, owner, qty, finish}] отсортированные по цене (топ-бид первый).
При протухшем токене бросает TokenExpired.
"""
from __future__ import annotations
import os, json, urllib.request, urllib.parse

NUMBERS_EQ = "EQAOQdwdw8kGftJCSFgOErM1mBjYPe4DBPq8-AhF6vr9si5N"
OFFERS_HASH = "46aca783e8949efebbcf4ad9b0c61f2d97d066a4a91504a3e843541ecd53ae3b"
GG_AUTH = os.environ.get("GG_AUTH_TOKEN", "")
GG_JWT = os.environ.get("GG_JWT", "")
MIN_REAL_PRICE = 100  # отсекаем тролль-биды 0/1 TON


class TokenExpired(Exception):
    pass


def _headers():
    return {
        "accept": "application/json",
        "content-type": "application/json",
        "cookie": f"AUTH_TOKEN={GG_AUTH}; JWT_TOKEN={GG_JWT}",
        "referer": "https://getgems.io/",
        "x-auth-token": GG_AUTH,
        "x-gg-client": "v:1 l:en s:snipebot1",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/148.0.0.0 Safari/537.36",
    }


def fetch_collection_offers(collection_eq: str = NUMBERS_EQ) -> list[dict]:
    if not (GG_AUTH and GG_JWT):
        raise TokenExpired("no token configured")
    ext = json.dumps({"persistedQuery": {"version": 1, "sha256Hash": OFFERS_HASH}})
    v = json.dumps({"collectionAddress": collection_eq})
    url = (f"https://getgems.io/graphql/?operationName=collectionOffers"
           f"&variables={urllib.parse.quote(v)}&extensions={urllib.parse.quote(ext)}")
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=_headers()), timeout=15)
        d = json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        if e.code in (401, 403) or "NO_SCRAPPERS" in body or "STRANGE_QUERY" in body:
            raise TokenExpired(f"{e.code}: {body[:120]}")
        raise
    errs = d.get("errors")
    if errs:
        raise TokenExpired(str(errs[0].get("message", ""))[:120])
    out = []
    for o in d.get("data", {}).get("collectionOffers") or []:
        price = int(o.get("fullPrice", 0)) / 1e9
        if price < MIN_REAL_PRICE or o.get("currency") != "TON":
            continue
        qty = o.get("maxQuantity", 1) - o.get("purchasedQuantity", 0)
        if qty <= 0:
            continue
        out.append({
            "price": price,
            "net": int(o.get("profitPrice", 0)) / 1e9,
            "owner": o.get("offerOwnerAddress", ""),
            "qty": qty,
            "finish": o.get("finishAt", 0),
            "offerAddress": o.get("offerAddress", ""),
        })
    out.sort(key=lambda x: -x["price"])
    return out


def top_bid(collection_eq: str = NUMBERS_EQ):
    offers = fetch_collection_offers(collection_eq)
    return (offers[0] if offers else None), offers


if __name__ == "__main__":
    try:
        top, offers = top_bid()
        print(f"collection-офферов: {len(offers)}")
        for o in offers[:10]:
            print(f"  {o['price']:>7.0f} TON  qty {o['qty']}  {o['owner'][:14]}..")
        print(f"\nТОП-БИД: {top['price']:.0f} TON" if top else "офферов нет")
    except TokenExpired as e:
        print(f"🔑 TOKEN EXPIRED: {e}")
