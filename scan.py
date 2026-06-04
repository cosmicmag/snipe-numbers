#!/usr/bin/env python3
"""
Phase-1 сигнальный сканер (keyless).

  1) тянет листинги Fragment (cheapest-first)
  2) калибрует base_floor = низ "plain"-номеров (perc-5 среди mult==1.0)
  3) для каждого листинга fair = base_floor * pattern_mult
  4) флагает где price < fair * (1 - MARGIN)  → потенциальный snipe
  5) печатает топ-кандидатов + честную сводку

NB: Fragment = дорогая витрина (продают тут). Дешёвый закуп (~1400) на Getgems —
для него нужен Getgems public API key (см. README). Этот скан проверяет Fragment-side
и работает как калибратор fair-value, пока не подключён Getgems-фид.
"""
from __future__ import annotations
import statistics as st
from fragment_feed import fetch_listings
from pattern_value import evaluate

MARGIN = 0.15          # листинг должен быть на 15%+ ниже fair, чтобы считаться snipe
INCLUDE_AUCTIONS = True # аукционы инстант не купить, но показываем как сигнал


def calibrate_floor(listings) -> float:
    plain = [l["price"] for l in listings if evaluate(l["number"]).mult == 1.0]
    if not plain:
        return min(l["price"] for l in listings)
    plain.sort()
    # 5-й перцентиль "обычных" = текущий честный floor
    k = max(0, int(len(plain) * 0.05))
    return plain[k]


def main():
    listings = fetch_listings(200)
    if not listings:
        print("Fragment вернул 0 листингов — проверь доступ/верстку.")
        return
    floor = calibrate_floor(listings)
    plain_prices = [l["price"] for l in listings if evaluate(l["number"]).mult == 1.0]

    print(f"листингов: {len(listings)}  |  fixed-price: {sum(l['sale_type']=='fixed' for l in listings)}")
    print(f"калиброванный floor (plain p5): {floor:.0f} TON")
    if plain_prices:
        print(f"plain-диапазон: {min(plain_prices):.0f}–{max(plain_prices):.0f} TON (med {st.median(plain_prices):.0f})")

    cands = []
    for l in listings:
        if not INCLUDE_AUCTIONS and l["sale_type"] != "fixed":
            continue
        v = evaluate(l["number"])
        fair = v.fair(floor)
        disc = (fair - l["price"]) / fair if fair else 0
        if l["price"] < fair * (1 - MARGIN) and v.mult > 1.0:
            cands.append((disc, l, v, fair))

    cands.sort(key=lambda x: -x[0])
    print(f"\n══════ SNIPE-КАНДИДАТЫ (price < fair−{int(MARGIN*100)}%, есть паттерн): {len(cands)} ══════")
    if not cands:
        print("  Пусто. На Fragment сейчас нет недооценённых паттерн-номеров —")
        print("  дешёвый закуп идёт на Getgems (нужен API key). Fragment держит флор.")
    for disc, l, v, fair in cands[:25]:
        instant = "🟢BUY" if l["sale_type"] == "fixed" else "⏳auc"
        print(f"  {instant} {l['price']:>6.0f} TON  fair≈{fair:>6.0f} (−{disc*100:>4.0f}%)  "
              f"{l['number']:18s} [{','.join(v.tags)}]  {l['url']}")
    print("\n⚠️  fair-value = эвристика по паттерну (pattern_value.PREMIUM). До подключения")
    print("    реальных продаж-компов воспринимай как 'обрати внимание', а не истину.")


if __name__ == "__main__":
    main()
