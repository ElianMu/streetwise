"""Business-data provider adapters (ratings, review counts, price level; hotel rooms and prices).

Keys live only in the Render environment, never in the browser. Without a key an adapter answers
{'status': 'blocked_by_provider_access'}; it never returns a simulated rating, price or room.

Ratings are kept per provider (Google 4.5/5 and Yelp 4.0/5 stay separate; no blended score). A provider result is used only when
it matches our place (name words + within 75 m); otherwise 'no_confident_match'. Third-party content is not cached by default until the deployment-specific provider terms are confirmed; nothing is written to disk.

Adapters:
  google_places   Places API (New) Text Search — rating, userRatingCount, priceLevel, regularOpeningHours, websiteUri, googleMapsUri
                  env GOOGLE_PLACES_API_KEY · attribution: "Google" (Google Maps Platform terms)
  yelp_fusion     Yelp Fusion /v3/businesses/search — rating, review_count, price, url · env YELP_API_KEY · attribution + link required
  foursquare      Foursquare Places /v3/places/search — rating (0–10), stats.total_ratings, price · env FOURSQUARE_API_KEY
  booking_demand, expedia_rapid   lodging content / rates / availability: partner programmes (contract + credentials); not callable here.
"""
import json, math, os, re, time
from urllib import error, parse, request

CACHE_SECONDS = 0  # No default third-party content cache without confirmed provider terms.
TIMEOUT = 8
_cache = {}


def _norm(s):
    return set(w for w in re.findall(r'[a-z0-9]+', str(s or '').lower()) if w not in ('the', 'and', 'of', 'nyc', 'new', 'york', 'cafe', 'restaurant', 'hotel'))


def _metres(a, b):
    return math.hypot((a[0] - b[0]) * 84414.3, (a[1] - b[1]) * 111049.7)


def _same_place(place, name, lon, lat, address=None):
    a, b = _norm(place['name']), _norm(name)
    words = bool(a and b) and len(a & b) >= max(1, min(len(a), len(b)) / 2)
    def address_parts(value):
        text=str(value or '').lower()
        for a,b in [('street','st'),('avenue','av'),('ave','av'),('road','rd')]:text=re.sub(r'\b'+a+r'\b',b,text)
        house=re.match(r'\s*(\d+[a-z]?(?:-\d+)?)\b',text)
        return house.group(1) if house else None,set(re.findall('[a-z0-9]+',text))
    number,left=address_parts(place.get('address')); other,right=address_parts(address)
    address_match=bool(number and number==other and left and right and (left <= right or right <= left))
    return words and address_match and lon is not None and lat is not None and _metres((place['lon'], place['lat']), (lon, lat)) < 75


def _http(url, headers=None, data=None):
    req = request.Request(url, data=json.dumps(data).encode() if data is not None else None, headers={'Accept': 'application/json', **(headers or {})},
                          method='POST' if data is not None else 'GET')
    try:
        with request.urlopen(req, timeout=TIMEOUT) as r:
            payload=json.load(r)
            if not isinstance(payload,dict): raise RuntimeError('invalid_provider_response')
            return payload
    except (json.JSONDecodeError, UnicodeError):
        raise RuntimeError('invalid_provider_json')
    except error.HTTPError as e:
        raise RuntimeError(f'HTTP {e.code}')
    except (error.URLError, TimeoutError, OSError) as e:
        raise RuntimeError(type(getattr(e, 'reason', e)).__name__)


def _key(name):
    value = os.environ.get(name, '').strip()
    if any(not 33 <= ord(c) <= 126 for c in value): raise RuntimeError('invalid_key_format')
    return value


def google_places(place):
    key = _key('GOOGLE_PLACES_API_KEY')
    if not key:
        return None
    body = {'textQuery': f"{place['name']} {place.get('address') or ''} New York", 'maxResultCount': 3,
            'locationBias': {'circle': {'center': {'latitude': place['lat'], 'longitude': place['lon']}, 'radius': 150.0}}}
    d = _http('https://places.googleapis.com/v1/places:searchText', {'X-Goog-Api-Key': key, 'Content-Type': 'application/json',
              'X-Goog-FieldMask': 'places.id,places.displayName,places.location,places.formattedAddress,places.rating,places.userRatingCount,places.priceLevel,places.regularOpeningHours,places.currentOpeningHours,places.websiteUri,places.googleMapsUri'}, body)
    for c in d.get('places', []):
        loc = c.get('location') or {}
        if _same_place(place, (c.get('displayName') or {}).get('text'), loc.get('longitude'), loc.get('latitude'), c.get('formattedAddress')):
            return {'provider': 'Google', 'provider_place_id': c.get('id'), 'rating': c.get('rating'), 'rating_scale': 5, 'review_count': c.get('userRatingCount'),
                    'price_level': c.get('priceLevel'), 'opening_hours_text': (c.get('regularOpeningHours') or {}).get('weekdayDescriptions'),
                    'open_now': (c.get('currentOpeningHours') or {}).get('openNow'), 'url': c.get('googleMapsUri'), 'attribution': 'Google'}
    return {'provider': 'Google', 'status': 'no_confident_match'}


def yelp_fusion(place):
    key = _key('YELP_API_KEY')
    if not key:
        return None
    q = parse.urlencode({'term': place['name'], 'latitude': place['lat'], 'longitude': place['lon'], 'radius': 150, 'limit': 3})
    d = _http('https://api.yelp.com/v3/businesses/search?' + q, {'Authorization': 'Bearer ' + key})
    for c in d.get('businesses', []):
        co = c.get('coordinates') or {}
        if _same_place(place, c.get('name'), co.get('longitude'), co.get('latitude'), ' '.join((c.get('location') or {}).get('display_address') or [])):
            return {'provider': 'Yelp', 'provider_place_id': c.get('id'), 'rating': c.get('rating'), 'rating_scale': 5, 'review_count': c.get('review_count'),
                    'price_level': c.get('price'), 'is_closed': c.get('is_closed'), 'url': c.get('url'), 'attribution': 'Yelp'}
    return {'provider': 'Yelp', 'status': 'no_confident_match'}


def foursquare(place):
    key = _key('FOURSQUARE_API_KEY')
    if not key:
        return None
    q = parse.urlencode({'query': place['name'], 'll': f"{place['lat']},{place['lon']}", 'radius': 150, 'limit': 3,
                         'fields': 'fsq_id,name,geocodes,location,rating,stats,price,closed_bucket'})
    d = _http('https://api.foursquare.com/v3/places/search?' + q, {'Authorization': key})
    for c in d.get('results', []):
        g = (c.get('geocodes') or {}).get('main') or {}
        if _same_place(place, c.get('name'), g.get('longitude'), g.get('latitude'), (c.get('location') or {}).get('formatted_address')):
            return {'provider': 'Foursquare', 'provider_place_id': c.get('fsq_id'), 'rating': c.get('rating'), 'rating_scale': 10,
                    'review_count': (c.get('stats') or {}).get('total_ratings'), 'price_level': c.get('price'), 'attribution': 'Foursquare'}
    return {'provider': 'Foursquare', 'status': 'no_confident_match'}


RATING_PROVIDERS = [('google_places', google_places), ('yelp_fusion', yelp_fusion), ('foursquare', foursquare)]


def configured():
    """Which providers have credentials (booleans only; never the keys)."""
    return {'google_places': bool(os.environ.get('GOOGLE_PLACES_API_KEY', '').strip()), 'yelp_fusion': bool(os.environ.get('YELP_API_KEY', '').strip()),
            'foursquare': bool(os.environ.get('FOURSQUARE_API_KEY', '').strip()),
            'booking_demand': bool(os.environ.get('BOOKING_DEMAND_API_KEY', '').strip()), 'expedia_rapid': bool(os.environ.get('EXPEDIA_RAPID_API_KEY', '').strip())}


def ratings(place):
    """Per-provider ratings for a canonical place. Never merged into one number."""
    key = ('ratings', place['place_id'])
    if key in _cache and time.time() - _cache[key][0] < CACHE_SECONDS:
        return _cache[key][1]
    results, blocked, errors = [], [], []
    for name, fn in RATING_PROVIDERS:
        try:
            r = fn(place)
        except RuntimeError as e:
            errors.append({'provider': name, 'error': str(e)})
            continue
        if r is None:
            blocked.append(name)
        elif r.get('status') == 'no_confident_match':
            errors.append({'provider': name, 'error': 'no confident match for this place'})
        else:
            results.append(r)
    out = {'place_id': place['place_id'], 'status': 'ok' if results else 'blocked_by_provider_access' if len(blocked) == len(RATING_PROVIDERS) else 'unavailable',
           'ratings': results, 'not_configured': blocked, 'errors': errors, 'checked_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
           'note': 'Ratings are shown per provider and never combined. Review text is not stored.'}
    if CACHE_SECONDS > 0:
        _cache[key] = (time.time(), out)
    return out


def validate_stay(checkin, checkout, guests, beds=None, max_price=None):
    from datetime import date
    if type(guests) is not int or not 1 <= guests <= 12: raise ValueError('guests must be 1-12')
    if beds is not None and (type(beds) is not int or not 1 <= beds <= 6): raise ValueError('beds must be 1-6')
    if max_price is not None and (type(max_price) not in (int,float) or not math.isfinite(max_price) or max_price < 0): raise ValueError('max_price must be a non-negative number')
    if checkin or checkout:
        if not checkin or not checkout: raise ValueError('Both checkin and checkout are required')
        start, end = date.fromisoformat(checkin), date.fromisoformat(checkout)
        if start >= end: raise ValueError('checkout must be after checkin')
        if start < date.today(): raise ValueError('checkin cannot be in the past')
    return {'checkin':checkin,'checkout':checkout,'guests':guests,'beds':beds,'max_price_usd':max_price}


def hotel_rooms(place, checkin, checkout, guests, beds=None, max_price=None):
    """Room types, prices and availability need a lodging partner (date- and party-specific)."""
    criteria = validate_stay(checkin,checkout,guests,beds,max_price)
    cfg = configured()
    if not (cfg['booking_demand'] or cfg['expedia_rapid']):
        return {'place_id': place['place_id'], 'status': 'blocked_by_provider_access', 'rooms': [], 'requirements': criteria, 'checkin': checkin, 'checkout': checkout, 'guests': guests,
                'reason': 'Room types, prices and availability require a lodging partner API (Booking.com Demand API or Expedia Rapid) with a signed agreement. '
                          'None is configured, so no room, price or availability is shown.'}
    # A configured partner still needs its contract-specific client (property ID mapping, signed requests); not implemented here.
    return {'place_id': place['place_id'], 'status': 'not_implemented', 'rooms': [], 'requirements': criteria, 'checkin': checkin, 'checkout': checkout, 'guests': guests,
            'reason': 'A lodging partner key is present, but the partner-specific client (property mapping, request signing) is not implemented.'}
