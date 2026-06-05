#!/usr/bin/env python3
"""
Алерт-бот по +888 номерам. Два источника, keyless, без кошелька:
  • Getgems (wallet-API, origin=walletbot.me) — дешёвая BUY-витрина (снайпы тут)
  • Fragment (HTML scrape)                    — официальный маркет / sell-флор

Один запуск = один тик (гоняй через cron/loop). Дедуп по state.json.

Сигналы (только НОВОЕ):
  🎯 RARE-SNIPE   — номер с паттерном дешевле pattern-fair на MARGIN+
  💰 CROSS-VENUE  — Getgems fix-price дешевле Fragment-флора на SPREAD+ (готовый арб)
  📉 FLOOR-DROP   — fix-price ниже прежнего флора
  🆕 NEW-CHEAP    — новый fix-price в топ-N дешёвых

Env: TG_BOT_TOKEN, TG_CHAT_ID, MARGIN(0.15), SPREAD(0.04). Без TG_* — dry-run в stdout.
"""
from __future__ import annotations
import os, json, time, statistics as st, urllib.request, urllib.parse
from pathlib import Path
from datetime import datetime, timezone
from getgems_feed import fetch_on_sale
from getgems_offers import top_bid as gg_top_bid, TokenExpired
from fragment_feed import fetch_listings
from pattern_value import evaluate

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state.json"
LOG = ROOT / "alert_bot.log"
MARGIN = float(os.environ.get("MARGIN", "0.15"))
FEE_SELL = float(os.environ.get("FEE_SELL", "0.06"))   # Getgems: 1% маркет + до 5% роялти (опц). 0.06 консерв / 0.02 без роялти
MIN_OFFER_PROFIT = float(os.environ.get("MIN_OFFER_PROFIT", "40"))  # окно оффера: алерт если NET ≥ этого
OFFER_GAS = float(os.environ.get("OFFER_GAS", "1.0"))
GAS_TON = float(os.environ.get("GAS_TON", "1.0"))
MIN_NET_TON = float(os.environ.get("MIN_NET_TON", "30"))  # минимум чистыми чтоб алертить арб
CHEAP_TOP_N = 5
FLOOR_PCT = float(os.environ.get("FLOOR_PCT", "1.5"))     # порог = флор * (1 + FLOOR_PCT/100); ловим всё у флора
FLOOR_MAX = float(os.environ.get("FLOOR_MAX", "0"))       # абсолютный потолок: слать любой fix-price <= этого (0=выкл)
TICK_SECONDS = int(os.environ.get("TICK_SECONDS", "0"))   # >0 = бесконечный loop с этим интервалом; 0 = один тик
GG_FETCH = int(os.environ.get("GG_FETCH", "400"))         # сколько листингов Getgems тянуть за тик (на быстрых тиках меньше)
FRAG_FETCH = int(os.environ.get("FRAG_FETCH", "200"))
TG_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT = os.environ.get("TG_CHAT_ID", "")


def log(msg: str):
    line = f"[{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%SZ}] {msg}"
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def tg_send(text: str):
    if not (TG_TOKEN and TG_CHAT):
        print("  [dry-run]\n" + text + "\n"); return
    data = urllib.parse.urlencode({
        "chat_id": TG_CHAT, "text": text, "parse_mode": "HTML",
        "disable_web_page_preview": "false",
    }).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", data=data), timeout=15).read()
    except Exception as e:
        log(f"⚠️ tg err: {e}")


def load_state() -> dict:
    return json.load(open(STATE)) if STATE.exists() else {}


def gather():
    """Собрать листинги обеих витрин (только fix-price TON для снайпа)."""
    out = []
    try:
        for l in fetch_on_sale(max_items=GG_FETCH):
            if l["currency"] != "TON":
                continue
            l["venue"] = "Getgems"
            out.append(l)
    except Exception as e:
        log(f"⚠️ getgems err: {e}")
    try:
        for l in fetch_listings(FRAG_FETCH):
            l["venue"] = "Fragment"
            out.append(l)
    except Exception as e:
        log(f"⚠️ fragment err: {e}")
    return out


def calibrate_floor(listings, venue=None, kind="fixed") -> float | None:
    pool = [l["price"] for l in listings
            if l["price"] > 0 and l["sale_type"] == kind
            and (venue is None or l["venue"] == venue)
            and evaluate(l["number"]).mult == 1.0]
    if not pool:
        return None
    pool.sort()
    return pool[max(0, int(len(pool) * 0.05))]


def fmt(l, v, kind, extra=""):
    inst = "🟢 fix-price (BUY СРАЗУ)" if l["sale_type"] == "fixed" else f"⏳ аукцион {l.get('time_left','')}"
    return (f"{kind}  ·  <b>{l['venue']}</b>\n<b>{l['number']}</b>  —  <b>{l['price']:.0f} TON</b>{extra}\n"
            f"паттерн: {','.join(v.tags)}\n{inst}\n{l['url']}")


def tick():
    s = load_state()
    seen = set(s.get("seen_ids", []))
    alerted = set(s.get("alerted", []))
    prev_true = s.get("gg_true_floor")   # текущий флор Getgems с прошлого тика
    cold = not seen

    listings = gather()
    if not listings:
        log("0 листингов — скип"); return

    gg_floor = calibrate_floor(listings, venue="Getgems", kind="fixed")   # робастный p5 для fair-value
    frag_floor = calibrate_floor(listings, venue="Fragment", kind="auction") or \
                 calibrate_floor(listings, venue="Fragment", kind="fixed")
    base = gg_floor or frag_floor or min(l["price"] for l in listings if l["price"] > 0)
    # ИСТИННЫЙ текущий флор = реальная самая дешёвая fix-price TON на Getgems прямо сейчас
    gg_fix_ton = [l["price"] for l in listings
                  if l["venue"] == "Getgems" and l["sale_type"] == "fixed" and l["price"] > 0]
    gg_true_floor = min(gg_fix_ton) if gg_fix_ton else None
    # топ-N дешёвых fix-price для NEW-CHEAP
    fixed = sorted([l for l in listings if l["sale_type"] == "fixed" and l["price"] > 0],
                   key=lambda x: x["price"])
    cheap_ids = {l["address"] if "address" in l else l["id"] for l in fixed[:CHEAP_TOP_N]}

    log(f"листингов {len(listings)} | GG-флор(true) {gg_true_floor} (p5 {gg_floor}) | "
        f"Frag {frag_floor} | FLOOR_MAX {FLOOR_MAX or '—'}")

    def lid(l):
        return l.get("address") or l.get("id")

    alerts = []

    # ── 💰 ОФФЕР-ОКНО: топ-бид настолько ниже флора, что выгодно оффертить ──
    try:
        top, _all = gg_top_bid()
        if top and gg_true_floor:
            window = gg_true_floor * (1 - FEE_SELL) - top["price"] - OFFER_GAS
            log(f"offers: топ-бид {top['price']:.0f} · окно {window:+.0f} TON (порог {MIN_OFFER_PROFIT:.0f})")
            if window >= MIN_OFFER_PROFIT:
                k = f"offerwin:{int(window // 25)}"
                if k not in alerted:
                    alerts.append((k, f"💰 <b>ОФФЕР-ОКНО</b>\nтоп-бид <b>{top['price']:.0f}</b> · флор <b>{gg_true_floor:.0f}</b> TON\n"
                                      f"поставь оффер ~{top['price']+1:.0f} → перепродай по флору\n"
                                      f"NET ~<b>+{window:.0f} TON</b> (комса {int(FEE_SELL*100)}%)"))
    except TokenExpired as e:
        k = f"ggtoken:{datetime.now(timezone.utc):%Y-%m-%d}"
        if k not in alerted:
            alerts.append((k, "🔑 <b>Getgems токен истёк</b> — мониторинг офферов на паузе.\n"
                              "Пришли свежий cURL запроса collectionOffers (из DevTools), обновлю секрет."))
        log(f"offers token expired: {e}")
    except Exception as e:
        log(f"offers err: {e}")
    for l in listings:
        nid = lid(l)
        v = evaluate(l["number"])
        fair = v.fair(base)

        # 🎯 RARE-SNIPE (отсекаем слабый pair-шум: только mult>=1.4)
        if v.mult >= 1.4 and l["price"] > 0 and l["price"] < fair * (1 - MARGIN):
            k = f"snipe:{nid}:{int(l['price'])}"
            if k not in alerted:
                alerts.append((k, fmt(l, v, "🎯 <b>RARE-SNIPE</b>",
                                      f"\nfair≈<b>{fair:.0f}</b> (−{(fair-l['price'])/fair*100:.0f}%)")))
            continue
        # 💰 CROSS-VENUE: Getgems fix-price → продать на Fragment, NET после комиссий
        if l["venue"] == "Getgems" and l["sale_type"] == "fixed" and frag_floor and l["price"] > 0:
            net = frag_floor * (1 - FEE_SELL) - l["price"] - GAS_TON
            if net >= MIN_NET_TON:
                k = f"xv:{nid}:{int(l['price'])}"
                if k not in alerted:
                    alerts.append((k, fmt(l, v, "💰 <b>CROSS-VENUE ARB</b>",
                        f"\nкупить GG {l['price']:.0f} → продать Frag ~{frag_floor:.0f}"
                        f"\nNET после комсы (~{int(FEE_SELL*100)}%): <b>+{net:.0f} TON</b>")))
                continue
        # 💎 У ФЛОРА: новый Getgems fix-price в пределах флор*(1+FLOOR_PCT%) ИЛИ ниже ручного потолка
        if l["venue"] == "Getgems" and l["sale_type"] == "fixed" and l["price"] > 0 and nid not in seen:
            base_floor = prev_true or gg_true_floor
            thresh = base_floor * (1 + FLOOR_PCT / 100) if base_floor else None
            ref = None
            if FLOOR_MAX and l["price"] <= FLOOR_MAX:
                ref = ("потолок", FLOOR_MAX)
            elif thresh and l["price"] <= thresh:
                ref = (("флор" if FLOOR_PCT == 0 else f"флор+{FLOOR_PCT:g}%"), thresh)
            if ref:
                k = f"below:{nid}:{int(l['price'])}"
                if k not in alerted:
                    extra = (f"\n<b>{l['price']:.0f} TON</b> ≤ {ref[0]} ({ref[1]:.0f} TON"
                             + (f", флор {base_floor:.0f}" if base_floor else "") + ")")
                    alerts.append((k, fmt(l, v, "💎 <b>У ФЛОРА</b>", extra)))
                continue
        if cold:
            continue
        # 🆕 NEW-CHEAP
        if nid in cheap_ids and nid not in seen:
            k = f"cheap:{nid}"
            if k not in alerted:
                alerts.append((k, fmt(l, v, "🆕 <b>NEW в топ-5 дешёвых</b>")))

    for k, text in alerts:
        tg_send(text); alerted.add(k); time.sleep(0.4)
    log(f"отправлено: {len(alerts)}")

    json.dump({
        "ts": datetime.now(timezone.utc).isoformat(),
        "seen_ids": [lid(l) for l in listings],
        "gg_true_floor": gg_true_floor,
        "alerted": list(alerted)[-3000:],
    }, open(STATE, "w"), indent=1)


def main():
    if TICK_SECONDS > 0:
        log(f"loop mode: тик каждые {TICK_SECONDS}s (GG_FETCH={GG_FETCH} FRAG_FETCH={FRAG_FETCH})")
        first = True
        while True:
            try:
                tick()
                if first:  # стартовый пинг = подтверждение что бот жив
                    fl = load_state().get("gg_true_floor")
                    tg_send(f"🟢 <b>snipe-bot запущен</b>\nтик каждые {TICK_SECONDS}s · "
                            f"флор {fl:.0f} TON · ловлю флор+{FLOOR_PCT:g}%" if fl else
                            "🟢 <b>snipe-bot запущен</b>")
                    first = False
            except Exception as e:
                log(f"⚠️ tick err: {e}")
            time.sleep(TICK_SECONDS)
    else:
        tick()


if __name__ == "__main__":
    main()
