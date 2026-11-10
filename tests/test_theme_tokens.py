"""Theme guard: every interface colour in styles.css comes from the theme variables.

The dark and light themes are one set of variables (:root and html[data-map-theme="light"] at the top of
styles.css). A literal neutral colour written into a component rule would stay the same in both themes, which is
how the light map ended up with black panels. This test fails on any such literal, and on a variable that is defined
for one theme but not the other.

Allowed literals: AR rules (drawn over the camera image, dark in both themes), fully transparent colours, and the
data-encoding colours listed in DATA_COLOURS (they must match the map paint, whatever the theme).
"""
import pathlib
import re
import unittest

CSS = pathlib.Path(__file__).resolve().parent.parent / 'styles.css'
DATA_COLOURS = {'#56585a'}  # Explore "N/A" swatch = EXPLORE_NA in explore-map.js
COLOUR_PROP = re.compile(r'^(--[\w-]+|background[\w-]*|color|fill|stroke|caret-color|outline(-color)?|accent-color|'
                         r'border([\w-]*-color|-top|-right|-bottom|-left|-block[\w-]*|-inline[\w-]*)?|'
                         r'box-shadow|text-shadow|-?webkit-[\w-]*|filter|text-decoration-color)$')
LITERAL = re.compile(r'#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|\b(?:white|black)\b')
AR = re.compile(r'\.ar-|#ar[A-Z]|body\.ar-mode')


def rules(text):
    """(selector, body) for every style rule, descending into @media / @supports blocks."""
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    out, i = [], 0
    while True:
        j = text.find('{', i)
        if j < 0:
            return out
        prelude = text[i:j].strip()
        depth, k = 1, j + 1
        while depth:
            depth += {'{': 1, '}': -1}.get(text[k], 0)
            k += 1
        body = text[j + 1:k - 1]
        if prelude.startswith('@media') or prelude.startswith('@supports'):
            out += rules(body)
        elif not prelude.startswith('@'):
            out.append((prelude, body))
        i = k


def parse_colour(lit):
    lit = lit.lower()
    if lit in ('white', 'black'):
        return (255, 255, 255, 1) if lit == 'white' else (0, 0, 0, 1)
    if lit.startswith('#'):
        h = lit[1:]
        if len(h) in (3, 4):
            h = ''.join(c * 2 for c in h)
        a = int(h[6:8], 16) / 255 if len(h) == 8 else 1
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a
    n = [float(x) for x in re.findall(r'[\d.]+', lit)]
    return n[0], n[1], n[2], (n[3] if len(n) > 3 else 1)


def declarations(body):
    for decl in body.split(';'):
        if ':' in decl:
            prop, value = decl.split(':', 1)
            yield prop.strip().lower(), value


class ThemeTokens(unittest.TestCase):
    def setUp(self):
        self.rules = rules(CSS.read_text(encoding='utf-8'))
        self.dark = next(b for s, b in self.rules if s.startswith(':root,.ar-view'))
        self.light = next(b for s, b in self.rules if s == 'html[data-map-theme="light"]')

    def test_both_themes_define_the_same_colour_variables(self):
        def colour_vars(body):
            # variables that hold a colour (or a colour-dependent filter) of their own, not ones derived with var()
            return {p for p, v in declarations(body) if p.startswith('--') and 'var(' not in v and re.search(r'#|rgba?\(|transparent|invert|^\s*none\s*$', v)}
        dark, light = colour_vars(self.dark), colour_vars(self.light)
        light.discard('--signal')
        self.assertEqual(sorted(dark - light - {'--signal'}), [], 'variables without a light-theme value')
        self.assertEqual(sorted(light - dark), [], 'light-theme variables the dark theme does not define')
        self.assertGreaterEqual(len([v for v in dark if re.match(r'--g[0-9a-f]{2}$', v)]), 20)

    def test_no_literal_neutral_colours_outside_the_theme(self):
        bad = []
        for sel, body in self.rules:
            if sel in (':root,.ar-view,body.ar-mode .nav-top,body.ar-mode .nav-bottom', 'html[data-map-theme="light"]') or AR.search(sel):
                continue
            for prop, value in declarations(body):
                if not COLOUR_PROP.match(prop):
                    continue
                for lit in LITERAL.findall(value):
                    r, g, b, a = parse_colour(lit)
                    if a == 0 or lit.lower() in DATA_COLOURS:
                        continue
                    if max(r, g, b) - min(r, g, b) < 22:  # a grey: must be a theme variable
                        bad.append(f'{sel[:60]} {{ {prop}: {lit} }}')
        self.assertEqual(bad, [], 'use a theme variable (--gXX, --bg-*, --text-*, --border-*) instead')

    def test_theme_switch_is_the_map_theme_attribute(self):
        app = (CSS.parent / 'app.js').read_text(encoding='utf-8')
        head = (CSS.parent / 'index.html').read_text(encoding='utf-8')
        self.assertIn('root.dataset.mapTheme=', app)
        # applied before first paint: light by default, dark only when the visitor chose it (PR #63)
        self.assertIn("var t='light'", head)
        self.assertIn('document.documentElement.dataset.mapTheme=t', head)
        self.assertNotIn('light-theme.css', head)  # one theme system, no second stylesheet


if __name__ == '__main__':
    unittest.main()
