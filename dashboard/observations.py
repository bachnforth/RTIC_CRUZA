"""Validated, bounded, in-memory store of observation records from the fleet.

Holds the recent advisory detections each aircraft's observer publishes. Every
record is validated and clamped before it is kept; malformed, non-finite or
out-of-range fields are dropped, mirroring the telemetry decoder's discipline.
Nothing is written to disk and nothing is ever sent to an aircraft. A detection
that stays in view updates its existing entry rather than piling up, so the
dashboard shows one row per distinct area of interest.

Records are tagged with the aircraft that reported them. The source name comes
from the reader that owns the SSH session, never from the record itself, so a
malformed or hostile datagram cannot claim to be another aircraft. Two aircraft
seeing the same object stay separate entries here; correlating them into one
area of interest is swarm.py's job, from the geolocated points.

Operator validation (confirm/dismiss) stays in the browser; this store only
keeps clean, expiring facts.
"""
import math
import re
import threading
import time

CLASS_RE = re.compile(r"[A-Za-z0-9 _-]{1,40}")
SOURCE_RE = re.compile(r"[a-z0-9_-]{1,16}")
TTL_SECONDS = 20        # drop an area of interest this long after its last sighting
MAX_ENTRIES = 50        # hard cap on tracked areas of interest, fleet-wide
AZIMUTH_BUCKET = 5      # degrees; one source's same class in one bucket is one AOI
DEFAULT_SOURCE = "cruza"


def _finite(value):
    return isinstance(value, (int, float)) and math.isfinite(value)


def _clamp(value, lo, hi):
    return lo if value < lo else hi if value > hi else float(value)


def validate(record):
    """Return a clean observation dict, or None if the record is unusable."""
    if not isinstance(record, dict):
        return None
    name = record.get("cls")
    if not isinstance(name, str):
        return None
    match = CLASS_RE.fullmatch(name.strip())
    if not match:
        return None
    score = record.get("score")
    az = record.get("az_rel_deg")
    el = record.get("el_rel_deg")
    if not (_finite(score) and _finite(az) and _finite(el)):
        return None
    if not 0.0 <= score <= 1.0 or not -90 <= az <= 90 or not -90 <= el <= 90:
        return None
    bbox = record.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4 or not all(_finite(v) for v in bbox):
        return None
    bbox = [_clamp(v, 0.0, 1.0) for v in bbox]
    return {"cls": match.group(0), "score": float(score),
            "az_rel_deg": float(az), "el_rel_deg": float(el), "bbox": bbox}


class ObservationStore:
    def __init__(self, ttl=TTL_SECONDS, max_entries=MAX_ENTRIES):
        self.ttl = ttl
        self.max_entries = max_entries
        self.lock = threading.Lock()
        self.items = {}  # key -> entry dict
        self.last_record = 0.0

    @staticmethod
    def _key(obs, source):
        return f"{source}/{obs['cls']}@{round(obs['az_rel_deg'] / AZIMUTH_BUCKET)}"

    def add(self, record, now=None, source=DEFAULT_SOURCE):
        """Validate and merge one record. Returns True if it was kept.

        `source` is the reporting aircraft, supplied by the reader that owns the
        link. A record cannot name its own source.
        """
        now = time.monotonic() if now is None else now
        if not isinstance(source, str) or not SOURCE_RE.fullmatch(source):
            return False
        obs = validate(record)
        if obs is None:
            return False
        key = self._key(obs, source)
        with self.lock:
            self.last_record = now
            entry = self.items.get(key)
            if entry is None:
                if len(self.items) >= self.max_entries:
                    self._evict_oldest(now)
                entry = {"id": key, "src": source, "cls": obs["cls"],
                         "first_seen": now, "count": 0}
                self.items[key] = entry
            entry["last_seen"] = now
            entry["count"] += 1
            # Keep the latest geometry; keep the strongest score seen.
            entry["score"] = max(obs["score"], entry.get("score", 0.0))
            entry["az_rel_deg"] = obs["az_rel_deg"]
            entry["el_rel_deg"] = obs["el_rel_deg"]
            entry["bbox"] = obs["bbox"]
        return True

    def _evict_oldest(self, now):
        oldest = min(self.items.values(), key=lambda e: e["last_seen"])
        del self.items[oldest["id"]]

    def expire(self, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            for key in [k for k, e in self.items.items() if now - e["last_seen"] > self.ttl]:
                del self.items[key]

    def snapshot(self, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            out = []
            for e in self.items.values():
                if now - e["last_seen"] > self.ttl:
                    continue
                out.append({"id": e["id"], "src": e["src"], "cls": e["cls"],
                            "score": round(e["score"], 3),
                            "az_rel_deg": round(e["az_rel_deg"], 2),
                            "el_rel_deg": round(e["el_rel_deg"], 2),
                            "bbox": [round(v, 4) for v in e["bbox"]],
                            "count": e["count"],
                            "first_seen_age": round(now - e["first_seen"], 1),
                            "last_seen_age": round(now - e["last_seen"], 1)})
            # Strongest, most recent first.
            out.sort(key=lambda o: (-o["score"], o["last_seen_age"]))
            return out

    def sources(self, now=None):
        """Aircraft that have a live area of interest, for the fleet summary."""
        return sorted({o["src"] for o in self.snapshot(now)})
