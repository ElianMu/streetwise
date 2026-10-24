"""Lossless coordinate storage; materialization caches are bounded by vertex count.

The graph's JSON numbers are stored as IEEE float64, just like Python floats.
Projection and routing still use the original formula and original vertices.
"""
from array import array
from collections import OrderedDict
import operator
import threading


class _Polylines:
    def __init__(self):
        self._cache = OrderedDict()
        self._vertices = 0
        self._lock = threading.Lock()

    def __iter__(self):
        return (self[i] for i in range(len(self)))

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(len(self))) ]
        index = operator.index(index)
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError(index)
        with self._lock:
            cached = self._cache.get(index)
            if cached is not None:
                self._cache.move_to_end(index)
                return cached
        value = self._materialize(index)
        # An unusually long line must not evict and then exceed the cache budget.
        if len(value) <= 8192:
            with self._lock:
                if index not in self._cache:
                    self._cache[index] = value
                    self._vertices += len(value)
                    while len(self._cache) > 256 or self._vertices > 8192:
                        self._vertices -= len(self._cache.popitem(last=False)[1])
        return value

    def cache_status(self):
        with self._lock:
            return {'lines': len(self._cache), 'vertices': self._vertices,
                    'max_lines': 256, 'max_vertices': 8192}


class PackedPolylines(_Polylines):
    def __init__(self, lines):
        super().__init__()
        self.coordinates = array('d')
        self.offsets = array('I', [0])
        for line in lines:
            for lon, lat in line:
                self.coordinates.extend((lon, lat))
            self.offsets.append(len(self.coordinates))

    def __len__(self):
        return len(self.offsets) - 1

    def _materialize(self, index):
        start, end = self.offsets[index:index + 2]
        return [[self.coordinates[i], self.coordinates[i + 1]] for i in range(start, end, 2)]

    @property
    def packed_bytes(self):
        return len(self.coordinates) * self.coordinates.itemsize + len(self.offsets) * self.offsets.itemsize


class ProjectedPolylines(_Polylines):
    def __init__(self, source, project):
        super().__init__()
        self.source, self.project = source, project

    def __len__(self):
        return len(self.source)

    def _materialize(self, index):
        return [self.project(*point) for point in self.source[index]]
