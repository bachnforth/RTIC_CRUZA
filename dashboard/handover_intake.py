"""Receives image chips for the mission handover queue, alongside the
observation store, without changing the store or its readers.

Intake wraps the shared ObservationStore. Each observation reader still calls
`observations.add(record, source=...)` exactly as before; Intake takes the
records that are image chip parts and passes every other record to the store
unchanged. For each detection the store keeps, Intake notes which store entry
its record number ("seq") went to, so the handover queue can find the image
that belongs to a cue. Everything else (snapshot, sources, ...) is the store's own.

A chip is one small JPEG of a detection, sent as numbered parts so that every
datagram stays inside the observation taps' existing 512-byte cap:
    {"chip": <seq of the detection>, "part": i, "parts": n, "jpg": "<base64>"}
Like the store, the aircraft name comes from the reader that owns the link,
never from the record. Nothing is written to disk here.
"""
import base64
import binascii
from collections import deque
import re
import threading
import time

from observations import SOURCE_RE, ObservationStore, validate

CHIP_PART_CHARS = 400   # base64 characters per part
CHIP_MAX_PARTS = 64
CHIP_MAX_BYTES = 24576  # decoded JPEG
CHIP_ASSEMBLY_S = 15    # an unfinished chip is dropped after this
CHIP_KEEP_S = 120       # a finished chip is kept this long for the handover queue
CHIP_MAX_PENDING = 8    # unfinished chips per aircraft
CHIP_MAX_DONE = 32
SEQS_KEPT = 16          # recent record numbers remembered per store entry
B64_RE = re.compile(r"[A-Za-z0-9+/]+={0,2}")


def is_chip(record):
    return isinstance(record, dict) and "jpg" in record


class ChipAssembler:
    """Reassembles image chips from their parts, per aircraft."""
    def __init__(self):
        self.lock = threading.Lock()
        self.pending = {}  # (src, seq) -> {"parts", "got", "started"}
        self.done = {}     # (src, seq) -> (jpeg bytes, finished)

    def add(self, record, now=None, source="cruza"):
        """Take one part. Returns True if it was well formed."""
        now = time.monotonic() if now is None else now
        if not isinstance(source, str) or not SOURCE_RE.fullmatch(source):
            return False
        seq, part, parts, data = (record.get(k) for k in ("chip", "part", "parts", "jpg"))
        if not all(isinstance(v, int) and not isinstance(v, bool) for v in (seq, part, parts)):
            return False
        if not (0 <= seq < 2**31 and 1 <= parts <= CHIP_MAX_PARTS and 0 <= part < parts):
            return False
        if not isinstance(data, str) or not 0 < len(data) <= CHIP_PART_CHARS or not B64_RE.fullmatch(data):
            return False
        try:
            raw = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError):
            return False
        key = (source, seq)
        with self.lock:
            self._expire(now)
            if key in self.done:
                return True
            chip = self.pending.get(key)
            if chip is None or chip["parts"] != parts:
                mine = [k for k in self.pending if k[0] == source]
                if len(mine) >= CHIP_MAX_PENDING:
                    del self.pending[min(mine, key=lambda k: self.pending[k]["started"])]
                chip = self.pending[key] = {"parts": parts, "got": {}, "started": now}
            chip["got"][part] = raw
            if len(chip["got"]) < parts:
                return True
            del self.pending[key]
            jpeg = b"".join(chip["got"][i] for i in range(parts))
            if (len(jpeg) <= CHIP_MAX_BYTES and jpeg[:3] == b"\xff\xd8\xff"
                    and jpeg[-2:] == b"\xff\xd9"):
                if len(self.done) >= CHIP_MAX_DONE:
                    del self.done[min(self.done, key=lambda k: self.done[k][1])]
                self.done[key] = (jpeg, now)
        return True

    def _expire(self, now):
        for k in [k for k, c in self.pending.items() if now - c["started"] > CHIP_ASSEMBLY_S]:
            del self.pending[k]
        for k in [k for k, (_, t) in self.done.items() if now - t > CHIP_KEEP_S]:
            del self.done[k]

    def find(self, source, seqs, now=None):
        """The newest finished chip for any of these record numbers, or None."""
        now = time.monotonic() if now is None else now
        with self.lock:
            self._expire(now)
            for seq in reversed(list(seqs or [])):
                hit = self.done.get((source, seq))
                if hit:
                    return hit[0]
        return None


class Intake:
    """Stands in for the ObservationStore at the readers' call site."""
    def __init__(self, store=None, chips=None):
        self.store = store or ObservationStore()
        self.chips = chips or ChipAssembler()
        self.lock = threading.Lock()
        self.seqs = {}  # store entry id -> recent record numbers

    def add(self, record, now=None, source="cruza"):
        if is_chip(record):
            return self.chips.add(record, now=now, source=source)
        kept = self.store.add(record, now=now, source=source)
        seq = record.get("seq") if isinstance(record, dict) else None
        if kept and isinstance(seq, int) and not isinstance(seq, bool) and 0 <= seq < 2**31:
            # The same key the store just filed this record under.
            key = ObservationStore._key(validate(record), source)
            with self.lock:
                self.seqs.setdefault(key, deque(maxlen=SEQS_KEPT)).append(seq)
                if len(self.seqs) > 4 * self.store.max_entries:
                    for old in [k for k in self.seqs if k not in self.store.items]:
                        del self.seqs[old]
        return kept

    def image_for(self, cue):
        """The image chip for a geolocated cue, if one has arrived."""
        with self.lock:
            seqs = list(self.seqs.get(cue.get("id"), ()))
        return self.chips.find(cue.get("src"), seqs)

    def __getattr__(self, name):
        return getattr(self.store, name)
