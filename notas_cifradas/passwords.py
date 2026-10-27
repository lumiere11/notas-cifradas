"""Estimación orientativa de la fortaleza de una contraseña."""
from __future__ import annotations

import math
import string

MIN_LENGTH = 12

# (límite superior en bits, etiqueta, color)
LEVELS = (
    (40, "Muy débil", "#da4453"),
    (60, "Débil", "#f67400"),
    (80, "Aceptable", "#c9a000"),
    (100, "Fuerte", "#27ae60"),
    (float("inf"), "Excelente", "#11d116"),
)


def estimate_bits(password: str) -> float:
    if not password:
        return 0.0
    pool = 0
    if any(c.islower() for c in password):
        pool += 26
    if any(c.isupper() for c in password):
        pool += 26
    if any(c.isdigit() for c in password):
        pool += 10
    if any(c in string.punctuation or c.isspace() for c in password):
        pool += 33
    if any(ord(c) > 127 for c in password):
        pool += 64
    unique = len(set(password))
    effective = unique + 0.25 * (len(password) - unique)  # repetir no suma casi nada
    return effective * math.log2(max(pool, 2))


def describe(password: str) -> tuple[float, str, str]:
    bits = estimate_bits(password)
    for limit, label, color in LEVELS:
        if bits < limit:
            return bits, label, color
    return bits, LEVELS[-1][1], LEVELS[-1][2]
