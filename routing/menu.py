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
import shutil, subprocess
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib import parse, robotparser

UA = 'STREETWISE-NYC-menu-check/2.0 (+https://elianmu.github.io/streetwise/; one request per user action)'
MAX_BYTES, TIMEOUT_S, DEADLINE_S, MAX_PAGES = 1_500_000, 6, 20, 3
CACHE, TTL = {}, 12 * 3600
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Known names and spellings of an item (confirmed); anything else close is only "probable".
SYNONYMS = {'cappuccino': ['cappuccino', 'capuccino', 'cappucino', 'cappuccini'], 'latte': ['latte', 'caffe latte', 'caffè latte'],
            'espresso': ['espresso'], 'flat white': ['flat white'], 'cortado': ['cortado'], 'macchiato': ['macchiato'],
            'cheesecake': ['cheesecake', 'cheese cake'], 'bagel': ['bagel', 'bagels'], 'croissant': ['croissant', 'croissants'],
            'tiramisu': ['tiramisu', 'tiramisù'], 'matcha': ['matcha'], 'pizza': ['pizza'], 'cannoli': ['cannoli', 'cannolo']}


class UnsafeURL(ValueError):
    pass


class _Sites:
    """place id (any merged provider ID or canonical ID) → (website, menu url) from the discovery index — the only sites this
    service will read. Backed by the shared place store, so the index is held in memory once."""
    def get(self, key, default=None):
        from .places import store
        r = store().raw(key)
        return (r.get('web'), r.get('menu')) if r and (r.get('web') or r.get('menu')) else default


def place_sites():
    return _Sites()


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
    host=(u.hostname or '').rstrip('.').lower()
    platforms=('yelp.com','booking.com','expedia.com','tripadvisor.com','ubereats.com','doordash.com','grubhub.com')
    if any(host==d or host.endswith('.'+d) for d in platforms) or host=='maps.google.com' or (host in ('google.com','www.google.com') and u.path.startswith('/maps')):
        raise UnsafeURL('This platform requires an authorized API; page scraping is not enabled')
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


def safe_get(url, max_bytes=MAX_BYTES, hops=3, deadline=None):
    """GET with SSRF checks on every hop; returns (final_url, content_type, body bytes, headers)."""
    deadline = deadline if deadline is not None else time.monotonic()+TIMEOUT_S
    for _ in range(hops + 1):
        if time.monotonic() >= deadline: raise TimeoutError('menu request time budget exhausted')
        u, ip = check_url(url)
        remaining=min(TIMEOUT_S,deadline-time.monotonic())
        if remaining <= 0: raise TimeoutError('menu request time budget exhausted')
        conn = (_Pinned(u.hostname, ip, timeout=remaining, context=ssl.create_default_context()) if u.scheme == 'https'
                else _PinnedHTTP(u.hostname, ip, timeout=remaining))
        path = (u.path or '/') + ('?' + u.query if u.query else '')
        try:
            conn.request('GET', path, headers={'User-Agent': UA, 'Accept': 'text/html,application/xhtml+xml,application/pdf;q=0.9,text/plain;q=0.8'})
            r = conn.getresponse()
            if r.status in (301, 302, 303, 307, 308) and r.getheader('Location'):
                url = parse.urljoin(url, r.getheader('Location'))
                continue
            if r.status >= 400:
                raise OSError(f'HTTP {r.status}')
            chunks,total=[],0
            while True:
                remaining=deadline-time.monotonic()
                if remaining <= 0: raise TimeoutError('menu response time budget exhausted')
                if conn.sock is not None: conn.sock.settimeout(min(TIMEOUT_S,remaining))
                chunk=r.read1(min(65536,max_bytes+1-total))
                if not chunk: break
                chunks.append(chunk);total+=len(chunk)
                if total>max_bytes: raise OSError('menu response exceeds size limit')
            body=b''.join(chunks)
            return url, (r.getheader('Content-Type') or '').lower(), body, dict(r.getheaders())
        finally:
            conn.close()
    raise OSError('too many redirects')


def _allowed(url, deadline=None):
    try:
        final, ctype, body, _ = safe_get(parse.urljoin(url, '/robots.txt'), max_bytes=200_000, deadline=deadline)
    except UnsafeURL:
        raise
    except OSError as e:
        return str(e).startswith(('HTTP 404', 'HTTP 410'))
    except Exception:
        return False  # unreachable robots.txt: do not assume permission to crawl
    rp = robotparser.RobotFileParser()
    rp.parse(body.decode('utf-8', 'replace').splitlines())
    return rp.can_fetch(UA, url)


def _html_text(page):
    page = re.sub(r'(?is)<(script|style|noscript)[^>]*>.*?</\1>', ' ', page)
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'(?s)<[^>]+>', ' ', page))).strip()


def _title(page):
    m = re.search(r'(?is)<title[^>]*>(.*?)</title>', page)
    return html.unescape(m.group(1)).strip() if m else ''


def _menu_body_text(page, place_name):
    """Page chrome and the business name are not evidence of a dish listing."""
    page = re.sub(r'(?is)<(head|title|header|nav|footer)\b[^>]*>.*?</\1>', ' ', page)
    text = _html_text(page)
    if place_name:
        text = re.sub(re.escape(place_name), ' ', text, flags=re.I)
    return text.strip()


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
            price = re.match(r'\s*[:.\-–—]*\s*\$\s?(\d{1,3}(?:\.\d{2})?)', text[m.end(): m.end() + 40])
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


def image_text(data):
    tool = shutil.which('tesseract')
    if not tool: return ''
    try:
        result = subprocess.run([tool,'stdin','stdout','--psm','6'],input=data,capture_output=True,timeout=5)
        return result.stdout[:200000].decode('utf-8','replace') if result.returncode == 0 else ''
    except (OSError,subprocess.TimeoutExpired): return ''


def structured_menu_items(page):
    """Only publisher JSON-LD MenuItem objects; never infer dishes or nearby prices."""
    found = []
    for raw in re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', page, re.I|re.S):
        try: pending = [json.loads(html.unescape(raw))]
        except (ValueError, RecursionError): continue
        count = 0
        while pending and count < 2000:
            node = pending.pop(); count += 1
            if isinstance(node, list): pending.extend(node); continue
            if not isinstance(node, dict): continue
            kind = node.get('@type')
            if (kind == 'MenuItem' or isinstance(kind, list) and 'MenuItem' in kind) and isinstance(node.get('name'), str):
                offer = node.get('offers') or {}
                if isinstance(offer, list): offer = next((o for o in offer if isinstance(o, dict)), {})
                if not isinstance(offer, dict): offer = {}
                price = offer.get('price'); currency = offer.get('priceCurrency')
                try:
                    price = float(price) if price is not None else None
                    if price is not None and (not 0 <= price <= 10000): price = None
                except (ValueError, TypeError): price = None
                found.append({'name': node['name'][:160], 'description': str(node.get('description') or '')[:500] or None,
                              'price': price, 'currency': currency if isinstance(currency,str) and re.fullmatch('[A-Z]{3}',currency) else None})
            pending.extend(v for v in node.values() if isinstance(v,(dict,list)))
    return found


def menu_profile(out):
    """Add typed item evidence; this is not a claim to have a complete menu."""
    status = out.get('status')
    grade = {'confirmed_menu_match':'verified','probable_match_review':'probable',
             'not_found_in_checked_sources':'not_found'}.get(status,'unverified')
    out['menu'] = {'restaurant_id':out.get('place_id'), 'menu_source':out.get('source_url'),
        'source_type':out.get('evidence_type'), 'checked_at':out.get('checked_at'), 'complete':False,
        'items':[{'name':out['matched_item'],'category':None,'description':None,'price':out.get('price'),
                  'currency':out.get('currency'),'dietary_tags':[],'evidence_url':out.get('source_url'),
                  'verification_status':grade}] if out.get('matched_item') else []}
    return out


def _identity(pid):
    from .places import store
    place = store().get(pid)
    return place['place_id'] if place else pid


def cached_evidence(pid, item):
    entry = CACHE.get((_identity(pid), item.lower()))
    if entry and 0 <= time.time()-entry[0] < TTL:
        return entry[1]
    return None


def verify(doc, now=None):
    item = str(doc.get('item') or '').strip()[:60]
    if not item:
        raise ValueError('item is required')
    pid, name = str(doc.get('place_id') or '')[:120], str(doc.get('name') or '')[:160]
    from .places import store
    known = store().get(pid)
    if known: name = known['name']
    checked = (now or datetime.now(timezone.utc)).isoformat(timespec='seconds')
    base = {'place_id': pid, 'name': name, 'requested_item': item, 'item': item, 'matched_item': None, 'evidence_type': None,
            'menu_source_url': None, 'source_url': None, 'evidence': None, 'menu_date': None, 'menu_date_basis': None,
            'checked_at': checked, 'price': None, 'currency': None, 'pages_checked': [],
            'price_verification': None, 'freshness': 'unknown',
            'note': 'A menu listing does not confirm today’s availability, price or stock. Branches may differ.'}
    site, menu_url = place_sites().get(pid, (None, None))
    # A browser-sent menu URL is only used when it is on the indexed official site (never an arbitrary target).
    u = doc.get('menu_url')
    if not menu_url and isinstance(u, str) and site and parse.urlsplit(u).hostname == parse.urlsplit(site).hostname:
        menu_url = u
    if not site and not menu_url:
        return menu_profile({**base, 'status': 'unverified', 'reason': 'No official website is recorded for this place in the checked sources (OpenStreetMap).'})
    key = (_identity(pid), item.lower())
    if key in CACHE and time.time() - CACHE[key][0] < (TTL if CACHE[key][1].get('status')=='confirmed_menu_match' else 300):
        return {**CACHE[key][1], 'cached': True}
    queue = ([(menu_url, True)] if menu_url else []) + ([(site, False)] if site else [])
    seen, start, reasons, pages = set(), time.monotonic(), [], []
    while queue and len(seen) < MAX_PAGES:
        url, is_menu = queue.pop(0)
        if url in seen:
            continue
        if time.monotonic() - start > DEADLINE_S:
            reasons.append('time limit reached')
            break
        seen.add(url)
        try:
            if not _allowed(url, deadline=start+DEADLINE_S):
                reasons.append(f'{url}: robots.txt does not allow automated reading')
                continue
            final, ctype, body, headers = safe_get(url, deadline=start+DEADLINE_S)
        except UnsafeURL as e:
            reasons.append(f'{url}: refused ({e})')
            continue
        except (OSError, ssl.SSLError, http.client.HTTPException) as e:
            reasons.append(f'{url}: {e}')
            continue
        structured = []
        if 'pdf' in ctype or body[:5] == b'%PDF-':
            text, kind, menu_page = pdf_text(body), 'pdf_menu', True
            if len(text) < 15:
                reasons.append(f'{final}: PDF text could not be extracted (scanned or custom-encoded menu)')
                continue
        elif ctype.startswith('image/'):
            text, kind, menu_page = image_text(body), 'image_menu_ocr', True
            if not text:
                reasons.append(f'{final}: image menu could not be read (OCR unavailable or failed)')
                continue
        else:
            page = body.decode('utf-8', 'replace')
            structured = structured_menu_items(page)
            text, kind = _menu_body_text(page, name), 'html_menu_page'
            menu_page = is_menu or bool(re.search(r'menu', final + ' ' + _title(page), re.I))
            if not menu_page:
                queue += [(m, True) for m in _menu_links(final, page)]
                kind = 'website_page'
            if len(text) < 200 and menu_page:
                reasons.append(f'{final}: page text is nearly empty (menu probably drawn by scripts)')
        date, basis = _menu_date(headers, text)
        pages.append({'url': final, 'menu_page': menu_page, 'type': kind, 'text': text, 'date': date, 'date_basis': basis, 'structured_items': structured})
    base['pages_checked'] = [{'url': p['url'], 'menu_page': p['menu_page'], 'type': p['type']} for p in pages]
    best = None
    for p in pages:
        grade, matched, snippet, price = match_item(item, p['text'])
        if p['type']=='image_menu_ocr' and grade:
            grade, price = 'probable', None
        if grade and (best is None or (p['menu_page'], grade == 'confirmed') > (best[0]['menu_page'], best[1] == 'confirmed')):
            best = (p, grade, matched, snippet, price)
    structured_match = next(((p, entry) for p in pages for entry in p.get('structured_items', []) if match_item(item,entry['name'])[0] == 'confirmed'), None)
    if structured_match:
        p, entry = structured_match
        out = {**base, 'status': 'confirmed_menu_match', 'matched_item': entry['name'], 'evidence_type': 'official_jsonld_menu_item',
               'source_url': p['url'], 'menu_source_url': p['url'], 'evidence': entry['name'], 'menu_date': p['date'],
               'menu_date_basis': p['date_basis'], 'price': entry['price'], 'currency': entry['currency'],
               'price_verification': 'structured_source', 'reason': 'The requested item is explicitly listed in official MenuItem structured data.'}
    elif best and best[0]['menu_page']:
        p, grade, matched, snippet, price = best
        out = {**base, 'status': 'confirmed_menu_match' if grade == 'confirmed' else 'probable_match_review', 'matched_item': matched,
               'evidence_type': p['type'], 'menu_source_url': p['url'], 'source_url': p['url'], 'evidence': snippet, 'menu_date': p['date'],
               'menu_date_basis': p['date_basis'], 'price': price if grade == 'confirmed' else None, 'currency': None,
               'price_verification': 'adjacent_menu_text' if price and grade == 'confirmed' else None,
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
    if out.get('menu_date'):
        try:
            date = datetime.fromisoformat(out['menu_date']).date()
            age = ((now or datetime.now(timezone.utc)).date()-date).days
            out['freshness'] = 'stale' if age > 365 else 'dated_source' if age >= 0 else 'future_date_unverified'
            if age > 365 or age < 0:
                out.update(status='unverified', price=None, currency=None, price_verification=None,
                           reason='Dated menu evidence is stale or future-dated; current item availability and price are unverified.')
        except ValueError: pass
    out = menu_profile(out)
    CACHE[key] = (time.time(), out)
    return out
