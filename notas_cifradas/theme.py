"""Aspecto de Plasma para el Qt empaquetado.

Con el Qt del sistema, Plasma aplica Breeze, sus colores e iconos por sí solo. El Qt que va dentro del
bundle no trae el estilo Breeze, así que se toman los colores, el tema de iconos y la fuente de
~/.config/kdeglobals y se aplican sobre el estilo Fusion. Si el estilo Breeze está disponible
(Qt del sistema), no se toca nada.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QFont, QIcon, QPalette

R = QPalette.ColorRole
G = QPalette.ColorGroup

# (rol de Qt, sección de kdeglobals, clave)
_ROLES = (
    (R.Window, "Colors:Window", "BackgroundNormal"),
    (R.WindowText, "Colors:Window", "ForegroundNormal"),
    (R.Base, "Colors:View", "BackgroundNormal"),
    (R.AlternateBase, "Colors:View", "BackgroundAlternate"),
    (R.Text, "Colors:View", "ForegroundNormal"),
    (R.Button, "Colors:Button", "BackgroundNormal"),
    (R.ButtonText, "Colors:Button", "ForegroundNormal"),
    (R.Highlight, "Colors:Selection", "BackgroundNormal"),
    (R.HighlightedText, "Colors:Selection", "ForegroundNormal"),
    (R.ToolTipBase, "Colors:Tooltip", "BackgroundNormal"),
    (R.ToolTipText, "Colors:Tooltip", "ForegroundNormal"),
    (R.Link, "Colors:View", "ForegroundLink"),
    (R.LinkVisited, "Colors:View", "ForegroundVisited"),
)
# Los roles de texto deshabilitado usan ForegroundInactive de su sección.
_DISABLED = (
    (R.WindowText, "Colors:Window"),
    (R.Text, "Colors:View"),
    (R.ButtonText, "Colors:Button"),
)


@dataclass
class PlasmaLook:
    palette: QPalette | None = None
    icon_theme: str | None = None
    font: QFont | None = None


def kdeglobals_path() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "kdeglobals"


def _color(cfg: QSettings, section: str, key: str) -> QColor | None:
    raw = cfg.value(f"{section}/{key}")
    if isinstance(raw, str):  # QSettings convierte "1,2,3" en lista; con un solo valor llega str
        raw = raw.split(",")
    try:
        r, g, b = (int(x) for x in list(raw)[:3])
    except (TypeError, ValueError):
        return None
    color = QColor(r, g, b)
    return color if color.isValid() else None


def load_kdeglobals(path: Path | None = None) -> PlasmaLook:
    path = path or kdeglobals_path()
    if not path.is_file():
        return PlasmaLook()
    cfg = QSettings(str(path), QSettings.IniFormat)

    palette = QPalette()
    found = 0
    for role, section, key in _ROLES:
        color = _color(cfg, section, key)
        if color is not None:
            palette.setColor(role, color)
            found += 1
    for role, section in _DISABLED:
        color = _color(cfg, section, "ForegroundInactive")
        if color is not None:
            palette.setColor(G.Disabled, role, color)
    text = palette.color(R.Text)
    placeholder = QColor(text)
    placeholder.setAlpha(128)
    palette.setColor(R.PlaceholderText, placeholder)

    font = None
    font_spec = cfg.value("font")  # QSettings expone [General] sin prefijo
    if font_spec:
        candidate = QFont()
        spec = ",".join(font_spec) if isinstance(font_spec, list) else str(font_spec)
        if candidate.fromString(spec):
            font = candidate

    icon_theme = cfg.value("Icons/Theme") or None
    return PlasmaLook(palette if found else None, str(icon_theme) if icon_theme else None, font)


def breeze_available() -> bool:
    from PySide6.QtWidgets import QStyleFactory

    return any(name.lower() == "breeze" for name in QStyleFactory.keys())


def apply_plasma_look(app, path: Path | None = None) -> list[str]:
    """Aplica colores/iconos/fuente de Plasma sobre Fusion. Devuelve lo aplicado."""
    if breeze_available():
        return []
    look = load_kdeglobals(path)
    applied: list[str] = []
    app.setStyle("Fusion")
    if look.palette is not None:
        app.setPalette(look.palette)
        applied.append("colores")
    if look.icon_theme:
        QIcon.setThemeName(look.icon_theme)
        applied.append(f"iconos:{look.icon_theme}")
    if look.font is not None:
        app.setFont(look.font)
        applied.append("fuente")
    return applied
