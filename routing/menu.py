"""Item-level menu evidence (POST /api/menu/verify) from a place's own official website.

Which URL: the server looks the place up in the discovery index (data/places, OpenStreetMap website / website:menu tags) and only
reads that official site. A URL sent by the browser is never fetched unless it is on the same site as the indexed website.

Security (SSRF): http/https only; the host is resolved and every address must be public (no loopback, private, link-local,
multicast, reserved or cloud-metadata ranges); the connection is made to that validated address (no DNS re-binding window);
every redirect hop is validated again; at most 3 pages, 1.5 MB each, 6 s per request, 20 s per check; robots.txt honoured;
a per-client rate limit is applied by server.py.

Evidence grades (status):
  confirmed_menu_match         the item, or a known spelling of it, is on a page that is a menu (website:menu, or a URL/title with
                               "menu", or a PDF menu)
  probable_match_review        a close variant appears on a menu page (e.g. "iced cappuccino", a one-letter misspelling) — a person
                               should confirm
  unverified                   no readable menu page (dynamic site, image menu, unreachable, blocked), or only a mention outside a menu
  not_found_in_checked_sources the menu pages that could be read do not list it — not proof that the place never serves it
A menu listing never confirms today's availability, price or stock.
"""
import html, http.client, ipaddress, json, os, re, socket, ssl, time, zlib
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib import parse, robotparser

UA = 'STREETWISE-NYC-menu-check/2.0 (+https://elianmu.github.io/streetwise/; one request per user action)'
MAX_BYTES, TIMEOUT_S, DEADLINE_S, MAX_PAGES = 1_500_000, 6, 20, 3
CACHE, TTL = {}, 12 * 3600
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLACES_DIR = os.path.join(ROOT, 'data', 'places')
# Known names and spellings of an item (confirmed); anything else close is only "probable".
SYNONYMS = {'cappuccino': ['cappuccino', 'capuccino', 'cappucino', 'cappuccini'], 'latte': ['latte', 'caffe latte', 'caffè latte'],
            'espresso': ['espresso'], 'flat white': ['flat white'], 'cortado': ['cortado'], 'macchiato': ['macchiato'],
            'cheesecake': ['cheesecake', 'cheese cake'], 'bagel': ['bagel', 'bagels'], 'croissant': ['croissant', 'croissants'],
            'tiramisu': ['tiramisu', 'tiramisù'], 'matcha': ['matcha'], 'pizza': ['pizza'], 'cannoli': ['cannoli', 'cannolo']}
_INDEX = None


class UnsafeURL(ValueError):
    pass


def place_sites():
    """place id → (website, menu url) from the discovery index (the only sites this service will read)."""
    global _INDEX
    if _INDEX is None:
        _INDEX = {}
        for fn in os.listdir(PLACES_DIR) if os.path.isdir(PLACES_DIR) else []:
            if fn.endswith('.json') and fn != 'index.json':
                for r in json.load(open(os.path.join(PLACES_DIR, fn)))['records']:
                    if r.get('web') or r.get('menu'):
                        _INDEX[r['id']] = (r.get('web'), r.get('menu'))
    return _INDEX


def _check_host(host):
    """Resolve and return one public address for host; raise UnsafeURL otherwise."""
    if not host:
        raise UnsafeURL('no host')
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise UnsafeURL(f'cannot resolve {host}: {e}')
    addrs = {i[4][0] for i in infos}
    for a in addrs:
        ip = ipaddress.ip_address(a.split('%')[0])
        if not ip.is_global or ip.is_multicast or str(ip) in ('169.254.169.254', 'fd00:ec2::254'):
            raise UnsafeURL(f'{host} resolves to a non-public address')
    return sorted(addrs)[0]


def check_url(url):
    u = parse.urlsplit(url)
    if u.scheme not in ('http', 'https'):
        raise UnsafeURL('only http and https are allowed')
    if u.username or u.password:
        raise UnsafeURL('credentials in URL are not allowed')
    if u.port not in (None, 80, 443):
        raise UnsafeURL('only standard web ports are allowed')
    return u, _check_host(u.hostname)


class _Pinned(http.client.HTTPSConnection):
    """HTTPS to the already-validated IP, with the real host name for TLS (SNI + certificate check)."""
    def __init__(self, host, ip, **kw):
        super().__init__(host, **kw)
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, host, ip, **kw):
        super().__init__(host, **kw)
        self._ip = ip

    def connect(self):
        self.sock = socket.create_connection((self._ip, self.port), self.timeout)


def safe_get(url, max_bytes=MAX_BYTES, hops=3):
    """GET with SSRF checks on every hop; returns (final_url, content_type, body bytes, headers)."""
    for _ in range(hops + 1):
        u, ip = check_url(url)
        conn = (_Pinned(u.hostname, ip, timeout=TIMEOUT_S, context=ssl.create_default_context()) if u.scheme == 'https'
                else _PinnedHTTP(u.hostname, ip, timeout=TIMEOUT_S))
        path = (u.path or '/') + ('?' + u.query if u.query else '')
        try:
            conn.request('GET', path, headers={'User-Agent': UA, 'Accept': 'text/html,application/xhtml+xml,application/pdf;q=0.9,text/plain;q=0.8'})
            r = conn.getresponse()
            if r.status in (301, 302, 303, 307, 308) and r.getheader('Location'):
                url = parse.urljoin(url, r.getheader('Location'))
                continue
            if r.status >= 400:
                raise OSError(f'HTTP {r.status}')
            body = r.read(max_bytes + 1)[:max_bytes]
            return url, (r.getheader('Content-Type') or '').lower(), body, dict(r.getheaders())
        finally:
            conn.close()
    raise OSError('too many redirects')


def _allowed(url):
    try:
        final, ctype, body, _ = safe_get(parse.urljoin(url, '/robots.txt'), max_bytes=200_000)
    except UnsafeURL:
        raise
    except OSError as e:
        return not str(e).startswith(('HTTP 401', 'HTTP 403'))
    except Exception:
        return True  # unreachable robots.txt: no restriction under the standard
    rp = robotparser.RobotFileParser()
    rp.parse(body.decode('utf-8', 'replace').splitlines())
    return rp.can_fetch(UA, url)


def _html_text(page):
    page = re.sub(r'(?is)<(script|style|noscript)[^>]*>.*?</\1>', ' ', page)
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'(?s)<[^>]+>', ' ', page))).strip()


def _title(page):
    m = re.search(r'(?is)<title[^>]*>(.*?)</title>', page)
    return html.unescape(m.group(1)).strip() if m else ''


def pdf_text(data):
    """Text from simple PDFs: (Flate-)compressed content streams with Tj / TJ string operators. Fonts with custom
    encodings come out unreadable — then the menu stays unverified rather than guessed."""
    chunks = []
    for m in re.finditer(rb'stream\r?\n(.*?)\r?\nendstream', data, re.S):
        raw = m.group(1)
        try:
            s = zlib.decompress(raw)
        except zlib.error:
            s = raw
        for t in re.findall(rb'\((?:\\.|[^\\)])*\)\s*Tj|\[[^\]]*\]\s*TJ', s):
            for part in re.findall(rb'\(((?:\\.|[^\\)])*)\)', t):
                chunks.append(re.sub(rb'\\(.)', rb'\1', part).decode('latin-1', 'replace'))
            chunks.append(' ')
    return re.sub(r'\s+', ' ', ''.join(chunks)).strip()


def _menu_links(base, page):
    host = parse.urlsplit(base).netloc
    out = []
    for href, label in re.findall(r'(?is)<a[^>]+href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', page):
        u = parse.urljoin(base, href)
        if parse.urlsplit(u).netloc == host and re.search(r'menu', href + ' ' + _html_text(label), re.I) and u not in out:
            out.append(u)
    return out[:2]


def _lev1(a, b):
    """True when a and b differ by at most one edit (a misspelling, not a different word)."""
    if a == b or abs(len(a) - len(b)) > 1:
        return a == b
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    return a[i + 1:] == b[i + 1:] or a[i:] == b[i + 1:] or a[i + 1:] == b[i:]


def match_item(item, text):
    """(grade, matched text, snippet, price) where grade is 'confirmed', 'probable' or None."""
    words = SYNONYMS.get(item.lower(), [item.lower()])
    for w in words:
        m = re.search(r'(?i)(?<![\w-])' + re.escape(w) + r'(?![\w-])', text)
        if m:
            price = re.search(r'\$\s?(\d{1,3}(?:\.\d{2})?)', text[m.end(): m.end() + 40])
            return 'confirmed', m.group(0), text[max(0, m.start() - 70): m.end() + 70], float(price.group(1)) if price else None
    base = words[0]
    for m in re.finditer(r'(?i)[a-zà-ü]{4,}', text):
        tok = m.group(0).lower()
        if tok == base:
            continue
        if (len(base) >= 6 and _lev1(tok, base)) or (len(base) >= 5 and base in tok):
            return 'probable', m.group(0), text[max(0, m.start() - 70): m.end() + 70], None
    return None, None, None, None


def _menu_date(headers, text):
    lm = headers.get('Last-Modified') or headers.get('last-modified')
    if lm:
        try:
            return parsedate_to_datetime(lm).date().isoformat(), 'Last-Modified header'
        except (TypeError, ValueError):
            pass
    m = re.search(r'\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b', text) or re.search(r'(?i)\b(?:updated|effective)[^0-9]{0,12}(\w+ \d{1,2},? 20\d{2})', text)
    return (m.group(0), 'date printed on the page') if m else (None, None)


def verify(doc, now=None):
    item = str(doc.get('item') or '').strip()[:60]
    if not item:
        raise ValueError('item is required')
    pid, name = str(doc.get('place_id') or '')[:120], str(doc.get('name') or '')[:160]
    checked = (now or datetime.now(timezone.utc)).isoformat(timespec='seconds')
    base = {'place_id': pid, 'name': name, 'requested_item': item, 'item': item, 'matched_item': None, 'evidence_type': None,
            'menu_source_url': None, 'source_url': None, 'evidence': None, 'menu_date': None, 'menu_date_basis': None,
            'checked_at': checked, 'price': None, 'currency': None, 'pages_checked': [],
            'note': 'A menu listing does not confirm today’s availability, price or stock. Branches may differ.'}
    site, menu_url = place_sites().get(pid, (None, None))
    # A browser-sent menu URL is only used when it is on the indexed official site (never an arbitrary target).
    u = doc.get('menu_url')
    if not menu_url and isinstance(u, str) and site and parse.urlsplit(u).hostname == parse.urlsplit(site).hostname:
        menu_url = u
    if not site and not menu_url:
        return {**base, 'status': 'unverified', 'reason': 'No official website is recorded for this place in the checked sources (OpenStreetMap).'}
    key = (pid, item.lower())
    if key in CACHE and time.time() - CACHE[key][0] < TTL:
        return {**CACHE[key][1], 'cached': True}
    queue = ([(menu_url, True)] if menu_url else []) + ([(site, False)] if site else [])
    seen, start, reasons, pages = set(), time.time(), [], []
    while queue and len(seen) < MAX_PAGES:
        url, is_menu = queue.pop(0)
        if url in seen:
            continue
        if time.time() - start > DEADLINE_S:
            reasons.append('time limit reached')
            break
        seen.add(url)
        try:
            if not _allowed(url):
                reasons.append(f'{url}: robots.txt does not allow automated reading')
                continue
            final, ctype, body, headers = safe_get(url)
        except UnsafeURL as e:
            reasons.append(f'{url}: refused ({e})')
            continue
        except (OSError, ssl.SSLError, http.client.HTTPException) as e:
            reasons.append(f'{url}: {e}')
            continue
        if 'pdf' in ctype or body[:5] == b'%PDF-':
            text, kind, menu_page = pdf_text(body), 'pdf_menu', True
            if len(text) < 15:
                reasons.append(f'{final}: PDF text could not be extracted (scanned or custom-encoded menu)')
                continue
        elif ctype.startswith('image/'):
            reasons.append(f'{final}: image menu (not read; no OCR is used)')
            continue
        else:
            page = body.decode('utf-8', 'replace')
            text, kind = _html_text(page), 'html_menu_page'
            menu_page = is_menu or bool(re.search(r'menu', final + ' ' + _title(page), re.I))
            if not menu_page:
                queue += [(m, True) for m in _menu_links(final, page)]
                kind = 'website_page'
            if len(text) < 200 and menu_page:
                reasons.append(f'{final}: page text is nearly empty (menu probably drawn by scripts)')
        date, basis = _menu_date(headers, text)
        pages.append({'url': final, 'menu_page': menu_page, 'type': kind, 'text': text, 'date': date, 'date_basis': basis})
    base['pages_checked'] = [{'url': p['url'], 'menu_page': p['menu_page'], 'type': p['type']} for p in pages]
    best = None
    for p in pages:
        grade, matched, snippet, price = match_item(item, p['text'])
        if grade and (best is None or (p['menu_page'], grade == 'confirmed') > (best[0]['menu_page'], best[1] == 'confirmed')):
            best = (p, grade, matched, snippet, price)
    if best and best[0]['menu_page']:
        p, grade, matched, snippet, price = best
        out = {**base, 'status': 'confirmed_menu_match' if grade == 'confirmed' else 'probable_match_review', 'matched_item': matched,
               'evidence_type': p['type'], 'menu_source_url': p['url'], 'source_url': p['url'], 'evidence': snippet, 'menu_date': p['date'],
               'menu_date_basis': p['date_basis'], 'price': price if grade == 'confirmed' else None, 'currency': 'USD' if price and grade == 'confirmed' else None,
               'reason': (f'“{matched}” appears on the official menu.' if grade == 'confirmed'
                          else f'A close variant “{matched}” appears on the official menu; please confirm it is “{item}”.')}
    elif best:
        p, grade, matched, snippet, _ = best
        out = {**base, 'status': 'unverified', 'matched_item': matched, 'evidence_type': 'website_mention', 'source_url': p['url'], 'evidence': snippet,
               'reason': f'“{matched}” is mentioned on the official website, but not on a page identified as a menu.'}
    elif any(p['menu_page'] for p in pages):
        p = next(p for p in pages if p['menu_page'])
        out = {**base, 'status': 'not_found_in_checked_sources', 'menu_source_url': p['url'], 'source_url': p['url'], 'evidence_type': p['type'],
               'menu_date': p['date'], 'menu_date_basis': p['date_basis'],
               'reason': f'The readable menu text does not list “{item}”. Menus drawn by scripts, images or other branches may differ.'}
    else:
        out = {**base, 'status': 'unverified', 'source_url': pages[0]['url'] if pages else None,
               'reason': 'No readable menu page was found on the official website.' + (' ' + '; '.join(reasons) if reasons else '')}
    CACHE[key] = (time.time(), out)
    return out
