"""Concurrency admission and exact source-coordinate regression (no live API mocks)."""
import concurrent.futures
import gzip
import json
import threading
import time
import unittest
from unittest import mock
from routing.capacity import Admission
from routing.engine import get_planner, GRAPH, xy
from routing.geometry_store import PackedPolylines, ProjectedPolylines


class CapacityTests(unittest.TestCase):
    def test_handler_releases_slot_after_an_unexpected_error(self):
        import server
        gate = Admission(1, 0)
        handler = object.__new__(server.Handler)
        handler.path = '/api/routes'
        handler.post_admitted = mock.Mock(side_effect=RuntimeError('test failure'))
        with mock.patch.object(server, 'HEAVY_REQUESTS', gate), mock.patch.object(server, 'rate_ok', return_value=True):
            with self.assertRaises(RuntimeError): handler.do_POST()
        self.assertEqual(gate.status()['active'], 0)

    def test_full_queue_and_timeout_do_not_leak_slots(self):
        gate = Admission(1, 1)
        self.assertTrue(gate.acquire(0))
        with concurrent.futures.ThreadPoolExecutor(1) as pool:
            waiting = pool.submit(gate.acquire, .1)
            deadline = time.monotonic() + 1
            while not gate.status()['queued'] and time.monotonic() < deadline:
                threading.Event().wait(.001)
            self.assertFalse(gate.acquire(0))
            self.assertFalse(waiting.result(1))
        gate.release()
        self.assertTrue(gate.acquire(0))
        gate.release()
        self.assertEqual(gate.status()['rejected'], 2)
        self.assertEqual(gate.status()['queued'], 0)

    def test_three_clients_finish_under_two_active_limit(self):
        gate, start = Admission(2, 3), threading.Barrier(3)
        def work(_):
            start.wait()
            self.assertTrue(gate.acquire(2))
            try:
                threading.Event().wait(.03)
                self.assertLessEqual(gate.status()['active'], 2)
                return True
            finally:
                gate.release()
        with concurrent.futures.ThreadPoolExecutor(3) as pool:
            self.assertEqual(list(pool.map(work, range(3))), [True] * 3)
        self.assertEqual(gate.status()['peak_active'], 2)
        self.assertEqual(gate.status()['active'], 0)

    def test_every_real_polyline_and_projected_vertex_is_unchanged(self):
        net = get_planner().net
        with gzip.open(GRAPH, 'rt') as f:
            source = json.load(f)['geoms']
        self.assertEqual(len(net.geoms), len(source))
        self.assertIsInstance(net.geoms, PackedPolylines)
        self.assertIsInstance(net.gxy, ProjectedPolylines)
        for i, line in enumerate(source):
            self.assertEqual(net.geoms[i], line, f'original coordinates: {i}')
            self.assertEqual(net.gxy[i], [xy(*p) for p in line], f'original projection: {i}')
        self.assertLess(net.geoms.packed_bytes, 10 * 1024 * 1024)
        for cache in (net.geoms, net.gxy):
            status = cache.cache_status()
            self.assertLessEqual(status['lines'], status['max_lines'])
            self.assertLessEqual(status['vertices'], status['max_vertices'])
