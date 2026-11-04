#!/usr/bin/env python3
"""Generate light-theme.css: the light UI that goes with the light map.

The dark interface in styles.css has many literal neutral colours beyond the design tokens
(panels, inputs, chips and borders written as #111, #262626, rgba(255,255,255,.08) and so on).
This script reads styles.css and writes, for each rule that paints colour, a copy of that rule
scoped to html[data-map-theme="light"], with each colour mapped to its light-theme counterpart:

  * neutral greys are inverted on a tuned curve (dark surfaces -> white, light text -> near-black,
    hairlines stay hairlines);
  * chromatic colours keep their hue: pale text/foreground colours are darkened so they read on
    white, very dark tinted surfaces become pale tints, mid colours (swatches, badges) are kept;
  * shadows stay dark but lighter, and light glows become faint dark shadows.

Every colour-related declaration of a rule is copied, including ones that use var() or none, so the
cascade between the copies is the same as between the originals. The copies add (0,1,1) specificity
and keep !important, so they win over the dark originals. AR rules (.ar-*), which sit on the camera
image, are left alone. Hand-written rules that are not mechanical are at the end (FOOTER).

Run:  python3 scripts/build_light_theme.py        (writes light-theme.css next to styles.css)
"""
import colorsys
import pathlib
import re
import sys

import tinycss2

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / 'styles.css'
OUT = ROOT / 'light-theme.css'
SCOPE = 'html[data-map-theme="light"]'

NAMED = {'white': (255, 255, 255, 1.0), 'black': (0, 0, 0, 1.0)}
SHADOW_PROPS = {'box-shadow', 'text-shadow', 'filter', '-webkit-filter'}
FG_PROPS = {'color', 'fill', 'stroke', 'caret-color', '-webkit-text-fill-color', 'text-decoration-color',
            'outline-color', 'accent-color', 'column-rule-color'}
BORDER_SHORTHANDS = {'border', 'border-top', 'border-right', 'border-bottom', 'border-left',
                     'border-block', 'border-inline', 'border-block-start', 'border-block-end',
                     'border-inline-start', 'border-inline-end', 'outline'}
SCRIM_HINT = re.compile(r'backdrop|scrim|overlay|veil|dim\b', re.I)
KEEP_TOKENS = {'--signal'}  # the AR lime stays as it is (camera image)


def is_colour_prop(name):
    return (name.startswith('--') or name.startswith('background') or name in SHADOW_PROPS or name in FG_PROPS
            or name in BORDER_SHORTHANDS or (name.startswith('border') and name.endswith('-color')))


# ---------- colour parsing / formatting ----------
def parse_hex(h):
    h = h.lower()
    if len(h) in (3, 4):
        h = ''.join(c * 2 for c in h)
    if len(h) not in (6, 8):
        return None
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        a = int(h[6:8], 16) / 255 if len(h) == 8 else 1.0
    except ValueError:
        return None
    return r, g, b, a


def parse_rgb_args(tokens):
    nums = []
    for t in tokens:
        if t.type == 'number':
            nums.append(float(t.value))
        elif t.type == 'percentage':
            nums.append(('%', float(t.value)))
    if len(nums) not in (3, 4):
        return None
    out = []
    for i, n in enumerate(nums):
        if isinstance(n, tuple):
            v = n[1] / 100 * (255 if i < 3 else 1)
        else:
            v = n
        out.append(v)
    if len(out) == 3:
        out.append(1.0)
    return out[0], out[1], out[2], out[3]


def fmt(r, g, b, a):
    r, g, b = (max(0, min(255, int(round(x)))) for x in (r, g, b))
    if a >= 0.999:
        return '#%02X%02X%02X' % (r, g, b)
    a = max(0.0, min(1.0, a))
    return 'rgba(%d,%d,%d,%s)' % (r, g, b, ('%.3f' % a).rstrip('0').rstrip('.') or '0')


# ---------- the mapping ----------
def grey_curve(v):
    """Dark-theme grey level -> light-theme grey level."""
    if v <= 24:          # page / panel surfaces -> white
        return 255
    if v < 128:          # raised surfaces and hairlines -> light greys that still separate on white
        return max(110, 255 - (v - 24) * 1.6)
    return max(20, 265 - v)  # text and icons -> near-black / mid greys


def map_colour(c, role, selector=''):
    r, g, b, a = c
    mx, mn = max(r, g, b), min(r, g, b)
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    neutral = (mx - mn) < 22 or s < 0.12
    if role == 'shadow':
        if neutral and l < 0.5:  # a dark shadow: keep it, lighter
            return (0, 0, 0, min(a, 1.0) * (0.35 if a > 0.5 else 0.5)) if a < 0.999 else (0, 0, 0, 0.16)
        if neutral:  # a light glow / highlight ring -> faint dark ring
            return (20, 20, 19, min(0.18, a * 0.6 + 0.02))
        return (r, g, b, a * 0.55)  # coloured glow
    if neutral:
        v = (r + g + b) / 3
        if role == 'surface' and v < 14 and a < 0.75 and SCRIM_HINT.search(selector):
            return (20, 20, 19, a * 0.45)  # a modal scrim stays a (lighter) dark scrim
        nv = grey_curve(v)
        # a hint of the warm editorial paper tone for mid/light greys
        return (nv, nv, nv - (2 if 120 < nv < 250 else 0), a)
    if role == 'fg':
        if l > 0.6:
            l = 0.36 if s > 0.25 else 0.32
        rr, gg, bb = colorsys.hls_to_rgb(h, l, s)
        return (rr * 255, gg * 255, bb * 255, a)
    if role == 'token':
        if l > 0.62:
            l = 0.42
        rr, gg, bb = colorsys.hls_to_rgb(h, l, s)
        return (rr * 255, gg * 255, bb * 255, a)
    # surface
    if l < 0.22:
        rr, gg, bb = colorsys.hls_to_rgb(h, 0.95 - l * 0.4, s * 0.6)
        return (rr * 255, gg * 255, bb * 255, a)
    return (r, g, b, a)


def role_for(prop):
    if prop in SHADOW_PROPS:
        return 'shadow'
    if prop in FG_PROPS:
        return 'fg'
    if prop.startswith('--'):
        return 'token'
    return 'surface'


def map_tokens(tokens, role, selector, prop):
    """Serialize a component-value list, mapping every colour in it."""
    out = []
    for t in tokens:
        if t.type == 'hash':
            c = parse_hex(t.value)
            out.append(fmt(*map_colour(c, role, selector)) if c else t.serialize())
        elif t.type == 'ident' and t.lower_value in NAMED:
            out.append(fmt(*map_colour(NAMED[t.lower_value], role, selector)))
        elif t.type == 'function' and t.lower_name in ('rgb', 'rgba'):
            c = parse_rgb_args(t.arguments)
            out.append(fmt(*map_colour(c, role, selector)) if c else t.serialize())
        elif t.type == 'function':
            # drop-shadow() inside filter, gradients in backgrounds, var() fallbacks…
            inner_role = 'shadow' if t.lower_name == 'drop-shadow' else role
            out.append('%s(%s)' % (t.name, map_tokens(t.arguments, inner_role, selector, prop)))
        else:
            out.append(t.serialize())
    return ''.join(out)


def colour_in(tokens):
    for t in tokens:
        if t.type == 'hash' and parse_hex(t.value):
            return True
        if t.type == 'ident' and t.lower_value in set(NAMED) | {'transparent', 'currentcolor'}:
            return True
        if t.type == 'function' and t.lower_name in ('rgb', 'rgba', 'var'):
            return True
    return False


def border_colour_part(tokens):
    """The colour component of a border/outline shorthand, as tokens (or None)."""
    for t in tokens:
        if t.type == 'hash' and parse_hex(t.value):
            return [t]
        if t.type == 'ident' and t.lower_value in set(NAMED) | {'transparent', 'currentcolor'}:
            return [t]
        if t.type == 'function' and t.lower_name in ('rgb', 'rgba', 'var'):
            return [t]
    return None


# ---------- selectors ----------
def split_selectors(text):
    parts, depth, cur = [], 0, ''
    for ch in text:
        if ch in '([':
            depth += 1
        elif ch in ')]':
            depth -= 1
        if ch == ',' and depth == 0:
            parts.append(cur)
            cur = ''
        else:
            cur += ch
    parts.append(cur)
    return [p.strip() for p in parts if p.strip()]


def scope_selector(sel):
    if re.search(r'\.ar-|#ar[A-Z]', sel):
        return None  # AR: on the camera image, stays dark
    if sel.startswith(':root'):
        return SCOPE + sel[len(':root'):]
    m = re.match(r'html(?![\w-])', sel)
    if m:
        return SCOPE + sel[4:]
    return SCOPE + ' ' + sel


# ---------- walking the stylesheet ----------
def process_rule(rule):
    prelude = tinycss2.serialize(rule.prelude).strip()
    sels = [s for s in (scope_selector(x) for x in split_selectors(prelude)) if s]
    if not sels:
        return ''
    decls = tinycss2.parse_declaration_list(rule.content, skip_comments=True, skip_whitespace=True)
    out = []
    painted = False
    for d in decls:
        if d.type != 'declaration':
            continue
        name = d.lower_name
        if name in KEEP_TOKENS or not is_colour_prop(name):
            continue
        imp = '!important' if d.important else ''
        value_tokens = [t for t in d.value]
        if name in BORDER_SHORTHANDS:
            part = border_colour_part(value_tokens)
            if not part:
                continue
            longhand = 'outline-color' if name == 'outline' else name + '-color'
            val = map_tokens(part, 'surface', prelude, longhand)
            out.append('%s:%s%s' % (longhand, val, imp))
            painted = painted or val != tinycss2.serialize(part)
            continue
        if name.startswith('--') and not colour_in(value_tokens):
            continue
        role = role_for(name)
        original = tinycss2.serialize(value_tokens).strip()
        val = map_tokens(value_tokens, role, prelude, name).strip()
        painted = painted or val != original
        out.append('%s:%s%s' % (name, val, imp))
    if not out or not painted:
        # nothing literal to change in this rule: the token overrides already restyle it, and copying it
        # unchanged only matters for ordering against rules that do change — keep those copies too, but
        # skip rules that set no colour at all
        if not out:
            return ''
    return '%s{%s}' % (','.join(sels), ';'.join(out))


def walk(rules):
    chunks = []
    for rule in rules:
        if rule.type == 'qualified-rule':
            css = process_rule(rule)
            if css:
                chunks.append(css)
        elif rule.type == 'at-rule' and rule.lower_at_keyword in ('media', 'supports') and rule.content:
            inner = walk(tinycss2.parse_rule_list(rule.content, skip_comments=True, skip_whitespace=True))
            if inner:
                chunks.append('@%s %s{%s}' % (rule.at_keyword, tinycss2.serialize(rule.prelude).strip(), ''.join(inner)))
    return chunks


FOOTER = r'''
/* ---- hand-tuned (not mechanical) ---- */
/* the turn-by-turn arrow box: white with a black arrow on the dark theme (styles.css), black with a white arrow here */
html[data-map-theme="light"] .nav-arrow{background:#141413;color:#FFFFFF}
/* MapLibre's own control icons are dark glyphs; the dark theme inverts them, the light theme shows them as drawn */
html[data-map-theme="light"] .maplibregl-ctrl-group button .maplibregl-ctrl-icon{filter:none}
html[data-map-theme="light"] .maplibregl-ctrl-group{background:#FFFFFF;box-shadow:0 1px 3px rgba(0,0,0,.12),0 0 0 1px #E2E2DE}
html[data-map-theme="light"] .maplibregl-ctrl-group button+button{border-top-color:#E2E2DE}
html[data-map-theme="light"] .maplibregl-ctrl-attrib,html[data-map-theme="light"] .maplibregl-ctrl-attrib a{background:rgba(255,255,255,.8);color:#5E5E5A}
/* AR sits on the camera image: its own scope keeps the dark palette whatever the map theme */
html[data-map-theme="light"] .ar-view{--bg:#0B0B0B;--bg2:#111111;--pane:#171717;--pane2:#242424;--line:#2E2E2E;--line-strong:#3D3D3B;--text:#F5F5F2;--muted:#A8A8A5;--subtle:#76766F;--white:#F5F5F2;--accent:#F5F5F2;--accent-ink:#0B0B0B;--lime:#F5F5F2;--glass:rgba(17,17,17,.86);--hair:rgba(255,255,255,.09);color:#F5F5F2}
/* iOS Home Screen app: the status bar style is fixed at launch (black-translucent = white clock and battery),
   so under a white header keep a dark band behind the status bar or the clock would vanish */
html.ios-standalone[data-map-theme="light"] body::before{content:'';position:fixed;left:0;right:0;top:0;height:env(safe-area-inset-top,0px);background:#141413;z-index:2147483000;pointer-events:none}
'''


def main():
    sheet = tinycss2.parse_stylesheet(SRC.read_text(encoding='utf-8'), skip_comments=True, skip_whitespace=True)
    chunks = walk(sheet)
    header = ('/* STROLLANE · light UI theme — GENERATED by scripts/build_light_theme.py from styles.css; edit the\n'
              '   script (or styles.css) and re-run it, not this file. Applies only while html[data-map-theme="light"]. */\n')
    OUT.write_text(header + '\n'.join(chunks) + '\n' + FOOTER.lstrip('\n'), encoding='utf-8')
    print('wrote %s: %d rules, %d bytes' % (OUT.name, len(chunks), OUT.stat().st_size))


if __name__ == '__main__':
    sys.exit(main())
