import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QApplication
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False

KDEGLOBALS = """\
[$Version]
update_info=kde5.upd

[General]
ColorScheme=BreezeDark
font=Noto Sans,11,-1,5,400,0,0,0,0,0,0,0,0,0,0,1

[Icons]
Theme=breeze-dark

[Colors:Window]
BackgroundNormal=35,38,41
ForegroundNormal=252,252,252
ForegroundInactive=161,169,177

[Colors:View]
BackgroundNormal=27,30,32
BackgroundAlternate=35,38,41
ForegroundNormal=252,252,252
ForegroundInactive=161,169,177
ForegroundLink=29,153,243

[Colors:Selection]
BackgroundNormal=61,174,233
ForegroundNormal=252,252,252
"""


@unittest.skipUnless(HAVE_QT, "PySide6 no instalado")
class ThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def write(self, text):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        p = Path(d.name) / "kdeglobals"
        p.write_text(text)
        return p

    def test_reads_colors_icons_font(self):
        from notas_cifradas import theme

        look = theme.load_kdeglobals(self.write(KDEGLOBALS))
        pal = look.palette
        self.assertEqual(pal.color(QPalette.Window).getRgb()[:3], (35, 38, 41))
        self.assertEqual(pal.color(QPalette.Base).getRgb()[:3], (27, 30, 32))
        self.assertEqual(pal.color(QPalette.Text).getRgb()[:3], (252, 252, 252))
        self.assertEqual(pal.color(QPalette.Highlight).getRgb()[:3], (61, 174, 233))
        self.assertEqual(pal.color(QPalette.Disabled, QPalette.WindowText).getRgb()[:3], (161, 169, 177))
        self.assertEqual(look.icon_theme, "breeze-dark")
        self.assertEqual(look.font.family(), "Noto Sans")
        self.assertEqual(look.font.pointSize(), 11)

    def test_missing_file_changes_nothing(self):
        from notas_cifradas import theme

        look = theme.load_kdeglobals(Path("/nonexistent/kdeglobals"))
        self.assertIsNone(look.palette)
        self.assertIsNone(look.icon_theme)
        self.assertIsNone(look.font)

    def test_garbage_is_tolerated(self):
        from notas_cifradas import theme

        look = theme.load_kdeglobals(self.write("[Colors:Window]\nBackgroundNormal=abc\n[Icons]\n"))
        self.assertIsNone(look.palette)
        self.assertIsNone(look.icon_theme)

    def test_skipped_when_breeze_is_available(self):
        from notas_cifradas import theme

        orig = theme.breeze_available
        theme.breeze_available = lambda: True
        self.addCleanup(setattr, theme, "breeze_available", orig)
        self.assertEqual(theme.apply_plasma_look(self.app, self.write(KDEGLOBALS)), [])


if __name__ == "__main__":
    unittest.main()
