"""Bound expensive concurrent work before reading request bodies or allocating routes.

Lightweight health checks and navigation progress remain independent. Queue slots
hold only waiting HTTP handlers, never constructed graphs or candidate responses.
"""
import threading
import time
from collections import deque


class Admission:
    def __init__(self, active_limit=2, queue_limit=3):
        self.active_limit, self.queue_limit = active_limit, queue_limit
        self.active = self.peak_active = self.rejected = 0
        self.queue = deque()
        self.condition = threading.Condition()

    def acquire(self, timeout):
        deadline = time.monotonic() + timeout
        with self.condition:
            if not self.queue and self.active < self.active_limit:
                self.active += 1
                self.peak_active = max(self.peak_active, self.active)
                return True
            if len(self.queue) >= self.queue_limit:
                self.rejected += 1
                return False
            token = object()
            self.queue.append(token)
            while True:
                if self.queue[0] is token and self.active < self.active_limit:
                    self.queue.popleft()
                    self.active += 1
                    self.peak_active = max(self.peak_active, self.active)
                    self.condition.notify_all()
                    return True
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.queue.remove(token)
                    self.rejected += 1
                    self.condition.notify_all()
                    return False
                self.condition.wait(remaining)

    def release(self):
        with self.condition:
            self.active -= 1
            self.condition.notify_all()

    def status(self):
        with self.condition:
            return {'active': self.active, 'queued': len(self.queue), 'rejected': self.rejected,
                    'peak_active': self.peak_active, 'active_limit': self.active_limit, 'queue_limit': self.queue_limit}


HEAVY_REQUESTS = Admission()
