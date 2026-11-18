"""street_photos.py: Mapillary photos along a route. No network: the provider is replaced by a fake opener.
Run: python3 -m unittest tests.test_street_photos
"""
import io, json, os, pathlib, sys, unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import street_photos as sp

COORDS = json.loads((ROOT / 'tests' / 'fixtures' / 'route-response.json').read_text())['routes'][0]['geometry']['coordinates']
TOKEN = 'MLY|123|abc'
T2024 = 1718000000000   # June 2024, milliseconds
T2019 = 1560000000000


def image(point, **kw):
    """A provider record at `north` metres from the point, facing `heading`."""
    north = kw.pop('north', 5)
    doc = {'id': kw.pop('id', '1'), 'computed_geometry': {'type': 'Point', 'coordinates': [point['lon'], point['lat'] + north / 111320]},
           'computed_compass_angle': kw.pop('heading', point['bearing']), 'captured_at': T2024, 'is_pano': False,
           'thumb_1024_url': 'https://example.invalid/t.jpg', 'creator': {'username': 'walker', 'id': '9'}}
    doc.update(kw)
    return doc


class FakeProvider:
    def __init__(self, by_call): self.by_call, self.requests = by_call, []
    def __call__(self, req, timeout=None):
        self.requests.append(req)
        data = self.by_call(len(self.requests) - 1)
        if isinstance(data, Exception): raise data
        return io.BytesIO(json.dumps({'data': data}).encode())


class StreetPhotos(unittest.TestCase):
    def setUp(self):
        sp._cache.clear()
        self.points = sp.sample_points(sp.validate(COORDS))

    def test_sampling_is_inside_the_route_and_ordered(self):
        self.assertEqual(len(self.points), sp.POINTS)
        at = [p['at_m'] for p in self.points]
        self.assertEqual(at, sorted(at))
        self.assertGreaterEqual(at[0], sp.SKIP_END_M)
        self.assertTrue(all(0 <= p['bearing'] < 360 for p in self.points))
        self.assertEqual(sp.sample_points(COORDS[:2]), [], 'a line shorter than the end margins is not sampled')

    def test_choose_prefers_looking_along_the_walk_then_newest(self):
        p = self.points[0]
        back = image(p, id='back', heading=(p['bearing'] + 180) % 360)
        old = image(p, id='old', captured_at=T2019)
        new = image(p, id='new')
        self.assertEqual(sp.choose([back, old, new], p)['image_id'], 'new')
        self.assertEqual(sp.choose([back, old], p)['image_id'], 'old', 'facing the walk beats newer but facing away')
        got = sp.choose([back], p)
        self.assertEqual(got['image_id'], 'back'); self.assertFalse(got['looks_along_walk'])
        self.assertEqual(got['captured_on'], '2024-06-10'); self.assertEqual(got['username'], 'walker')
        self.assertTrue(got['page'].endswith('pKey=back')); self.assertLessEqual(got['distance_m'], sp.RADIUS_M)

    def test_choose_never_substitutes(self):
        p = self.points[0]
        self.assertIsNone(sp.choose([], p))
        self.assertIsNone(sp.choose([image(p, north=40)], p), 'beyond 25 m is not this street')
        self.assertIsNone(sp.choose([image(p, is_pano=True)], p), 'panoramas are skipped')
        self.assertIsNone(sp.choose([image(p, thumb_1024_url=None)], p))
        self.assertIsNone(sp.choose([image(p, captured_at=None)], p), 'a photo without a date is not shown')
        self.assertIsNone(sp.choose([{'id': 'x'}, 'junk', None], p))

    def test_not_configured_makes_no_request(self):
        fake = FakeProvider(lambda i: [])
        with mock.patch.dict(os.environ, {'MAPILLARY_TOKEN': ''}):
            out = sp.along_route(COORDS, opener=fake)
        self.assertEqual((out['configured'], out['photos'], len(fake.requests)), (False, [], 0))
        with mock.patch.dict(os.environ, {'MAPILLARY_TOKEN': 'not-a-token'}):
            self.assertFalse(sp.configured())

    def test_along_route_uses_the_header_not_the_url_for_the_token(self):
        fake = FakeProvider(lambda i: [image(self.points[i], id=f'im{i}')] if i != 2 else [])
        with mock.patch.dict(os.environ, {'MAPILLARY_TOKEN': TOKEN}):
            out = sp.along_route(COORDS, opener=fake)
        self.assertTrue(out['configured']); self.assertEqual(out['checked_points'], 5); self.assertEqual(out['failed_points'], 0)
        self.assertEqual([x['image_id'] for x in out['photos']], ['im0', 'im1', 'im3', 'im4'], 'a point with no photo is left out, not filled')
        self.assertEqual([x['at_m'] for x in out['photos']], [self.points[i]['at_m'] for i in (0, 1, 3, 4)])
        for req in fake.requests:
            self.assertEqual(req.get_header('Authorization'), 'OAuth ' + TOKEN)
            self.assertNotIn(TOKEN, req.full_url); self.assertIn('radius=25', req.full_url)
        self.assertNotIn(TOKEN, json.dumps(out), 'the token never reaches the browser')
        self.assertEqual(out['attribution'], 'Images from Mapillary, CC BY-SA')

    def test_provider_failure_is_reported_not_hidden(self):
        fake = FakeProvider(lambda i: OSError('down') if i < 2 else [image(self.points[i], id=f'im{i}')])
        with mock.patch.dict(os.environ, {'MAPILLARY_TOKEN': TOKEN}):
            out = sp.along_route(COORDS, opener=fake)
        self.assertEqual(out['failed_points'], 2); self.assertEqual(len(out['photos']), 3)

    def test_results_are_cached_briefly(self):
        fake = FakeProvider(lambda i: [image(self.points[i % 5], id=f'im{i % 5}')])
        with mock.patch.dict(os.environ, {'MAPILLARY_TOKEN': TOKEN}):
            sp.along_route(COORDS, opener=fake); sp.along_route(COORDS, opener=fake)
            self.assertEqual(len(fake.requests), 5, 'a second look at the same route asks nothing new')
            sp.along_route(COORDS, opener=fake, now=lambda: __import__('time').time() + sp.CACHE_SECONDS + 1)
            self.assertEqual(len(fake.requests), 10, 'signed thumbnail URLs expire, so the cache does too')

    def test_only_answers_for_the_app_area_and_sane_input(self):
        for bad in (None, [], [[0, 0]], [[-73.98, 40.75], [2.35, 48.85]], [[-73.98, 40.75], ['a', 'b']], [[-73.98, 40.75], [True, 40.7]],
                    [[-73.98, 40.75]] * (sp.MAX_COORDS + 1)):
            with mock.patch.dict(os.environ, {'MAPILLARY_TOKEN': TOKEN}), self.assertRaises((ValueError, TypeError)):
                sp.along_route(bad, opener=FakeProvider(lambda i: []))


if __name__ == '__main__':
    unittest.main()
