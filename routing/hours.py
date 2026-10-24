"""OpenStreetMap opening_hours evaluation in New York time (same rules as opening-hours.js): 24/7; ';'-separated rules;
day lists / ranges; time lists / ranges incl. past midnight; off / closed. Anything else is unknown (None), never a guess.
Hours in OSM are as mapped by volunteers — not verified live opening status."""
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

NY = ZoneInfo('America/New_York')
DAYS = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']
DAYSPEC = r'(?:Mo|Tu|We|Th|Fr|Sa|Su)(?:-(?:Mo|Tu|We|Th|Fr|Sa|Su))?'
MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']


def _days(spec):
    out = set()
    for part in spec.split(','):
        m = re.fullmatch(r'(Mo|Tu|We|Th|Fr|Sa|Su)(?:-(Mo|Tu|We|Th|Fr|Sa|Su))?', part.strip())
        if not m:
            return None
        a = DAYS.index(m.group(1)); b = DAYS.index(m.group(2)) if m.group(2) else a
        for i in range(7):
            d = (a + i) % 7
            out.add(d)
            if d == b:
                break
    return out


def _times(spec):
    out = []
    for part in spec.split(','):
        m = re.fullmatch(r'(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})\+?', part.strip())
        if not m:
            return None
        a, am, b, bm = map(int, m.groups())
        if a > 23 or b > 24 or am > 59 or bm > 59 or (b == 24 and bm != 0):
            return None
        out.append((a * 60 + am, b * 60 + bm))
    return out


def is_open_at(hours, when):
    """True / False / None (unknown or unsupported syntax). `when` is an aware datetime."""
    if not hours or not isinstance(hours, str):
        return None
    h = hours.strip()
    if h == '24/7':
        return True
    # No authoritative/local holiday calendar is connected. A PH exception may
    # override an ordinary-day rule; silently skipping it could claim open.
    if re.search(r'\bPH\b', h):
        return None
    t = when.astimezone(NY)
    day, minute = t.weekday(), t.hour * 60 + t.minute
    prev = (day + 6) % 7
    verdict, any_rule = None, False
    for raw in h.split(';'):
        r = raw.strip()
        if not r:
            continue
        mm = re.match(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b\s*(.*)', r)
        if mm:
            # date exceptions: 'Dec 25 off', 'Nov Th[4] off' apply on their date only; other dated rules this month are unknown
            mon, rest = MONTHS.index(mm.group(1)) + 1, mm.group(2).strip()
            if t.month != mon:
                continue
            d1 = re.fullmatch(r'0?(\d{1,2})\s+(off|closed)', rest)
            nth = re.fullmatch(r'(Mo|Tu|We|Th|Fr|Sa|Su)\[(\d)\]\s+(off|closed)', rest)
            if d1:
                if t.day == int(d1.group(1)):
                    return False
                continue
            if nth:
                if t.weekday() == DAYS.index(nth.group(1)) and (t.day - 1) // 7 + 1 == int(nth.group(2)):
                    return False
                continue
            return None
        m = re.fullmatch(rf'((?:{DAYSPEC})(?:,{DAYSPEC})*)?\s*(.*)', r)
        if not m:
            return None
        days = _days(m.group(1)) if m.group(1) else set(range(7))
        rest = m.group(2).strip()
        if days is None:
            return None
        any_rule = True
        if re.fullmatch(r'(?i)off|closed', rest):
            if day in days:
                verdict = False
            continue
        times = [(0, 1440)] if rest == '' else _times(rest)
        if times is None:
            return None
        for a, b in times:
            if b > a:
                if day in days:
                    verdict = verdict or False
                    if a <= minute < b:
                        verdict = True
            else:
                if day in days:
                    verdict = verdict or False
                    if minute >= a:
                        verdict = True
                if prev in days and minute < b:
                    verdict = True
    if not any_rule:
        return None
    return False if verdict is None else verdict


def closes_within(hours, when, minutes):
    """True when the place is open at `when` but not `minutes` later (it closes during the visit); None if unknown."""
    a = is_open_at(hours, when)
    if a is not True:
        return None if a is None else False
    b = is_open_at(hours, when + timedelta(minutes=minutes))
    return None if b is None else not b
