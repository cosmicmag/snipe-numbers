#!/usr/bin/env python3
"""
Оценка справедливой стоимости +888 анонимного номера по ПАТТЕРНУ цифр.

Логика: базовая стоимость номера = floor "обычного" номера (калибруется снаружи,
из реального стакана Fragment/on-chain). Сверху накручиваем мультипликатор за
редкость паттерна. Чем реже/красивее паттерн — тем выше fair value.

Это НЕ оракул, а эвристика. Калибруется константами PREMIUM_* по реальным продажам.
Цель: ловить листинги, выставленные сильно НИЖЕ pattern-implied fair value.

Формат номера: +888 XXXX XXXX → 8 значащих цифр после кода 888.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field


def digits_of(number: str) -> str:
    """'+888 0391 5274' / '88803915274' / '0391 5274' -> '03915274' (8 цифр после 888)."""
    d = re.sub(r"\D", "", number)
    if d.startswith("888") and len(d) > 8:
        d = d[3:]
    return d[-8:]  # последние 8 — тело номера


# ── детекторы паттернов: каждый возвращает множитель к базовой цене ──

def _max_repeat_run(d: str) -> int:
    best = run = 1
    for i in range(1, len(d)):
        run = run + 1 if d[i] == d[i - 1] else 1
        best = max(best, run)
    return best


def _is_palindrome(d: str) -> bool:
    return d == d[::-1]


def _max_sequential_run(d: str) -> int:
    """Длина самого длинного арифм. ряда ±1 (1234 / 9876)."""
    best = run = 1
    for i in range(1, len(d)):
        if abs(int(d[i]) - int(d[i - 1])) == 1 and (i < 2 or (int(d[i]) - int(d[i - 1])) == (int(d[i - 1]) - int(d[i - 2]))):
            run += 1
        else:
            run = 2 if abs(int(d[i]) - int(d[i - 1])) == 1 else 1
        best = max(best, run)
    return best


def _trailing_zeros(d: str) -> int:
    return len(d) - len(d.rstrip("0"))


def _distinct(d: str) -> int:
    return len(set(d))


@dataclass
class Valuation:
    digits: str
    tags: list[str] = field(default_factory=list)
    mult: float = 1.0

    def fair(self, base_floor: float) -> float:
        return round(base_floor * self.mult, 1)


# Премии (мультипликаторы). Консервативно; калибровать по продажам.
PREMIUM = {
    "quad_repeat": 8.0,     # AAAA где-то подряд (4+)
    "triple_repeat": 2.6,   # AAA подряд
    "pair_repeat": 1.25,    # AA подряд (слабо)
    "palindrome": 3.0,
    "seq4": 3.5,            # 4+ подряд по порядку
    "seq3": 1.4,
    "trail_zeros3": 3.0,    # ...000
    "trail_zeros2": 1.5,    # ...00
    "low_distinct2": 2.2,   # всего 2 разные цифры во всём номере
    "low_distinct3": 1.4,
    "ABABAB": 2.5,          # чередование пары
}


def evaluate(number: str) -> Valuation:
    d = digits_of(number)
    v = Valuation(digits=d)
    mult = 1.0

    rr = _max_repeat_run(d)
    if rr >= 4:
        mult = max(mult, PREMIUM["quad_repeat"]); v.tags.append(f"repeat×{rr}")
    elif rr == 3:
        mult = max(mult, PREMIUM["triple_repeat"]); v.tags.append("triple")
    elif rr == 2:
        mult *= PREMIUM["pair_repeat"]; v.tags.append("pair")

    if _is_palindrome(d):
        mult = max(mult, PREMIUM["palindrome"]); v.tags.append("palindrome")

    sq = _max_sequential_run(d)
    if sq >= 4:
        mult = max(mult, PREMIUM["seq4"]); v.tags.append(f"seq{sq}")
    elif sq == 3:
        mult = max(mult, PREMIUM["seq3"]); v.tags.append("seq3")

    tz = _trailing_zeros(d)
    if tz >= 3:
        mult = max(mult, PREMIUM["trail_zeros3"]); v.tags.append(f"…{'0'*tz}")
    elif tz == 2:
        mult = max(mult, PREMIUM["trail_zeros2"]); v.tags.append("…00")

    nd = _distinct(d)
    if nd <= 2:
        mult = max(mult, PREMIUM["low_distinct2"]); v.tags.append(f"{nd}digits")
    elif nd == 3:
        mult = max(mult, PREMIUM["low_distinct3"]); v.tags.append("3digits")

    # ABABABAB чередование
    if len(d) == 8 and d[0::2] == d[0] * 4 and d[1::2] == d[1] * 4 and d[0] != d[1]:
        mult = max(mult, PREMIUM["ABABAB"]); v.tags.append("ABAB")

    v.mult = round(mult, 3)
    if not v.tags:
        v.tags.append("plain")
    return v


# ── класс для ОЦЕНКИ по реальному стакану ──
# Только паттерны, за которые рынок реально платит премию, получают свой класс.
# Слабьё (pair / seq3 / …00 / 3 разные цифры) намеренно = plain: на него спроса по
# премии нет, выход = обычный floor. Так оценка идёт от РЕАЛЬНОГО флора класса,
# а не от выдуманного множителя.

def value_class(number: str) -> tuple[str, str]:
    """('triple','triple') и т.п.; для непремиальных номеров → ('plain','plain')."""
    d = digits_of(number)
    rr = _max_repeat_run(d)
    sq = _max_sequential_run(d)
    tz = _trailing_zeros(d)
    nd = _distinct(d)
    if rr >= 4:
        return "quad", f"repeat×{rr}"
    if _is_palindrome(d):
        return "palindrome", "palindrome"
    if sq >= 4:
        return "seq4", f"seq{sq}"
    if tz >= 3:
        return "zeros3", f"…{'0'*tz}"
    if rr == 3:
        return "triple", "triple"
    if nd <= 2:
        return "two_distinct", f"{nd}digits"
    return "plain", "plain"


if __name__ == "__main__":
    tests = ["+888 0391 5274", "+888 8888 0000", "+888 1234 5678",
             "+888 0007 0000", "+888 1212 1212", "+888 0660 0660",
             "+888 0597 1634", "+888 0000 0001"]
    print(f"{'NUMBER':18s} {'DIGITS':10s} {'MULT':>6} TAGS")
    for t in tests:
        v = evaluate(t)
        print(f"{t:18s} {v.digits:10s} {v.mult:>6.2f} {','.join(v.tags)}")
