"""Item-level menu verification (POST /api/menu/verify) against a place's own official website.

No menu API with usage rights is connected, so the only source checked is the business's official site, as linked in
OpenStreetMap (website:menu first, then website). One request per user action, robots.txt respected, small pages only,
results cached for 12 hours. Statuses are kept apart:
  verified_on_menu   the item name appears on a page that is a menu (website:menu, or a URL/title containing "menu")
  unverified         the site could not be read, has no menu page, or only mentions the item outside a menu
  not_found          a menu page was read and the item does not appear on it
A listing on a menu says nothing about live availability, today's price or stock.
"""
import html, re, time
from datetime import datetime, timezone
from urllib import parse, request, robotparser, error

UA = 'STREETWISE-NYC-menu-check/1.0 (+https://elianmu.github.io/streetwise/; one request per user action)'
MAX_BYTES = 1_500_000
CACHE, TTL = {}, 12 * 3600
DEADLINE_S = 20  # whole check, across robots.txt and up to three pages
SYNONYMS = {'cappuccino': ['cappuccino', 'capuccino', 'cappucino'], 'latte': ['latte'], 'espresso': ['espresso'], 'flat white': ['flat white'],
            'cheesecake': ['cheesecake', 'cheese cake'], 'bagel': ['bagel'], 'croissant': ['croissant'], 'matcha': ['matcha'], 'pizza': ['pizza']}


def _allowed(url):
    robots = parse.urljoin(url, '/robots.txt')
    try:
        with request.urlopen(request.Request(robots, headers={'User-Agent': UA}), timeout=4) as r:
            lines = r.read(200_000).decode('utf-8', 'replace').splitlines()
    except error.HTTPError as e:
        return e.code not in (401, 403)  # 404 etc.: no robots.txt, no restriction; 401/403: treat as disallowed
    except Exception:
        return True  # unreachable robots.txt: the standard treats it as no restriction
    rp = robotparser.RobotFileParser()
    rp.parse(lines)
    return rp.can_fetch(UA, url)


def _get(url):
    req = request.Request(url, headers={'User-Agent': UA, 'Accept': 'text/html,application/xhtml+xml'})
    with request.urlopen(req, timeout=6) as r:
        ctype = r.headers.get('Content-Type', '')
        if 'html' not in ctype and 'text' not in ctype:
            raise ValueError(f'not a web page ({ctype or "unknown type"})')
        body = r.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            body = body[:MAX_BYTES]
        return r.geturl(), body.decode(r.headers.get_content_charset() or 'utf-8', 'replace')


def _text(page):
    page = re.sub(r'(?is)<(script|style|noscript)[^>]*>.*?</\1>', ' ', page)
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'(?s)<[^>]+>', ' ', page))).strip()


def _title(page):
    m = re.search(r'(?is)<title[^>]*>(.*?)</title>', page)
    return html.unescape(m.group(1)).strip() if m else ''


def _menu_links(base, page):
    host = parse.urlsplit(base).netloc
    out = []
    for href, label in re.findall(r'(?is)<a[^>]+href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', page):
        u = parse.urljoin(base, href)
        if parse.urlsplit(u).netloc == host and re.search(r'menu', href + ' ' + _text(label), re.I) and u not in out:
            out.append(u)
    return out[:2]


def _find(item, text):
    for w in SYNONYMS.get(item.lower(), [item.lower()]):
        m = re.search(r'(?i)\b' + re.escape(w) + r'\b', text)
        if m:
            snippet = text[max(0, m.start() - 70): m.end() + 70]
            price = re.search(r'\$\s?(\d{1,3}(?:\.\d{2})?)', text[m.end(): m.end() + 40])
            return snippet, (float(price.group(1)) if price else None)
    return None, None


def verify(doc):
    item = str(doc.get('item') or '').strip()[:60]
    if not item:
        raise ValueError('item is required')
    pid, name = str(doc.get('place_id') or '')[:120], str(doc.get('name') or '')[:160]
    urls = [u for u in (doc.get('menu_url'), doc.get('website')) if isinstance(u, str) and u.startswith(('http://', 'https://'))]
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    base = {'place_id': pid, 'name': name, 'item': item, 'checked_at': now, 'price': None, 'currency': None, 'source_url': None,
            'evidence': None, 'note': 'A menu listing does not confirm live availability, today’s price or stock.'}
    if not urls:
        return {**base, 'status': 'unverified', 'reason': 'No official website or menu link is recorded for this place in the available sources.'}
    key = (pid, item.lower(), tuple(urls))
    if key in CACHE and time.time() - CACHE[key][0] < TTL:
        return {**CACHE[key][1], 'cached': True}
    pages, reasons = [], []
    queue = [(urls[0], bool(doc.get('menu_url')) and urls[0] == doc.get('menu_url'))] + [(u, False) for u in urls[1:]]
    seen, start = set(), time.time()
    while queue and len(seen) < 3:
        if time.time() - start > DEADLINE_S:
            reasons.append('time limit reached')
            break
        url, is_menu = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        if not _allowed(url):
            reasons.append(f'{url}: robots.txt does not allow automated reading')
            continue
        try:
            final, page = _get(url)
        except (error.URLError, ValueError, TimeoutError, OSError) as e:
            reasons.append(f'{url}: {getattr(e, "reason", e)}')
            continue
        menu_page = is_menu or bool(re.search(r'menu', final + ' ' + _title(page), re.I))
        pages.append((final, menu_page, _text(page)))
        if not menu_page:
            queue += [(u, True) for u in _menu_links(final, page)]
    found_any = None
    for final, menu_page, text in pages:
        snippet, price = _find(item, text)
        if snippet and menu_page:
            out = {**base, 'status': 'verified_on_menu', 'source_url': final, 'evidence': snippet, 'price': price, 'currency': 'USD' if price else None,
                   'reason': f'“{item}” appears on the official menu page.'}
            CACHE[key] = (time.time(), out)
            return out
        if snippet and not found_any:
            found_any = (final, snippet)
    if found_any:
        out = {**base, 'status': 'unverified', 'source_url': found_any[0], 'evidence': found_any[1],
               'reason': f'“{item}” is mentioned on the official website, but not on a page identified as a menu.'}
    elif any(m for _, m, _ in pages):
        out = {**base, 'status': 'not_found', 'source_url': next(f for f, m, _ in pages if m),
               'reason': f'The official menu page was read and its text does not list “{item}” (menus drawn by scripts, images or PDFs cannot be read).'}
    else:
        out = {**base, 'status': 'unverified', 'source_url': pages[0][0] if pages else None,
               'reason': 'No readable menu page was found on the official website.' + (' ' + '; '.join(reasons) if reasons else '')}
    CACHE[key] = (time.time(), out)
    return out
