#!/usr/bin/env python3
"""Cruza -> quad data-link test.

Measures whether the Cruza's companion Pi can pass data to each quad while
flying, and logs evidence for a post-flight report.

Roles
  send       on the Cruza Pi. Sends small numbered test packets ("probes") at a
             steady rate to every quad path in the plan, plus a short data burst
             every few seconds to check sustained throughput.
  echo       on each quad Pi. Logs every probe it receives and answers with a
             small reply that says which probes it has seen.
  preflight  on the Cruza Pi, with the echoes running. A quick ground check.
  watch      on either Pi (normally over SSH). Live status table.
  stop       stops a running send/echo started in the background.

Safety: this program never opens the flight-controller UART, never sends
MAVLink, and uses its own UDP port (default 15700). It touches no flight
service, route, firewall or parameter. Only Python's standard library is used.
"""
import argparse
import array
import bisect
import datetime as dt
import ipaddress
import json
import os
from pathlib import Path
import random
import select
import shutil
import signal
import socket
import statistics
import string
import subprocess
import sys
import threading
import time

VERSION = "1.0.0"
DEFAULT_PORT = 15700
LOG_ROOT = Path(os.environ.get("LINKTEST_LOG_ROOT", str(Path.home() / "linktest-logs")))
MAX_DURATION = 4 * 3600
MASK_BITS = 64
MASK_ALL = (1 << MASK_BITS) - 1
SETTLE_S = 3.0          # a probe is judged only after this long (reply in flight)


# ---------------------------------------------------------------- helpers

def wall():
    return time.time()


def mono():
    return time.monotonic()


def utc_stamp(t=None):
    return dt.datetime.fromtimestamp(t or wall(), dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def run(cmd, timeout=4):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except (OSError, subprocess.TimeoutExpired) as error:
        return -1, "", str(error)


def percentile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * q / 100.0
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def encode(obj):
    return json.dumps(obj, separators=(",", ":")).encode()


def padded(obj, size):
    """Encode obj, padding it with filler text up to roughly `size` bytes."""
    raw = encode(obj)
    if len(raw) + 10 < size:
        obj = dict(obj, pad="x" * (size - len(raw) - 10))
        raw = encode(obj)
    return raw


def decode(data):
    if len(data) > 4096:
        return None
    try:
        obj = json.loads(data.decode())
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(obj, dict) or obj.get("v") != 1 or not isinstance(obj.get("k"), str):
        return None
    return obj


def load_plan(path):
    plan = json.loads(Path(path).read_text())
    plan.setdefault("port", DEFAULT_PORT)
    plan.setdefault("probe", {})
    plan["probe"].setdefault("rate_hz", 5)
    plan["probe"].setdefault("size_bytes", 300)
    plan.setdefault("burst", {})
    plan["burst"].setdefault("interval_s", 30)
    plan["burst"].setdefault("bytes", 50000)
    plan["burst"].setdefault("chunk_bytes", 1000)
    plan["burst"].setdefault("max_kbps", 512)
    plan.setdefault("duration_s", 3600)
    plan.setdefault("criteria", {})
    validate_plan(plan)
    return plan


def validate_plan(plan):
    if not 1024 <= int(plan["port"]) <= 65535:
        raise ValueError("port must be 1024..65535")
    if not 0.2 <= float(plan["probe"]["rate_hz"]) <= 20:
        raise ValueError("probe.rate_hz must be 0.2..20")
    if not 64 <= int(plan["probe"]["size_bytes"]) <= 1400:
        raise ValueError("probe.size_bytes must be 64..1400")
    b = plan["burst"]
    if b["bytes"] and not (200 <= int(b["chunk_bytes"]) <= 1400 and 8 <= float(b["max_kbps"]) <= 4000
                           and 5 <= float(b["interval_s"]) and int(b["bytes"]) <= 1_000_000):
        raise ValueError("burst settings out of range")
    if not 10 <= int(plan["duration_s"]) <= MAX_DURATION:
        raise ValueError("duration_s must be 10..%d" % MAX_DURATION)
    names = set()
    for quad in plan.get("quads", []):
        for path in quad.get("paths", []):
            ipaddress.ip_address(path["addr"])
            name = quad["name"] + "/" + path["label"]
            if name in names:
                raise ValueError("duplicate target " + name)
            names.add(name)
    ipaddress.ip_address(plan["cruza"]["tailnet_ip"])


def targets_from_plan(plan, only=None):
    out = []
    for quad in plan.get("quads", []):
        if quad.get("enabled", True) is False:
            continue
        for path in quad.get("paths", []):
            name = quad["name"] + "/" + path["label"]
            if path.get("enabled", True) is False:
                continue
            if only and name not in only and quad["name"] not in only:
                continue
            out.append({"name": name, "quad": quad["name"], "path": path["label"],
                        "addr": path["addr"], "port": int(plan["port"])})
    return out


# ---------------------------------------------------------------- logging

class SessionLog:
    """Newline-delimited JSON log in rotating segments with a size cap.

    Low disk space drops packet-level records first but keeps summaries,
    context samples and start/end records, and says so in the log.
    """
    ESSENTIAL = {"meta", "ctx", "sum", "end", "ba", "bend", "note", "err"}

    def __init__(self, role, segment_bytes=8 << 20, max_bytes=256 << 20, min_free=300 << 20):
        LOG_ROOT.mkdir(parents=True, exist_ok=True)
        self.dir = LOG_ROOT / ("%s_%s_%s" % (utc_stamp(), role, socket.gethostname()))
        self.dir.mkdir()
        link = LOG_ROOT / ("current-" + role)
        try:
            if link.is_symlink() or link.exists():
                link.unlink()
            link.symlink_to(self.dir.name)
        except OSError:
            pass
        self.segment_bytes, self.max_bytes, self.min_free = segment_bytes, max_bytes, min_free
        self.lock = threading.Lock()
        self.index, self.size, self.file = 0, 0, None
        self.dropped = 0
        self.next_disk_check = 0
        self.low_disk = False
        self._open()

    def _open(self):
        if self.file:
            self.file.close()
        self.index += 1
        self.file = open(self.dir / ("events-%04d.jsonl" % self.index), "a", buffering=1 << 16)
        self.size = 0
        segments = sorted(self.dir.glob("events-*.jsonl"))
        total = sum(p.stat().st_size for p in segments)
        while total > self.max_bytes and len(segments) > 1:
            total -= segments[0].stat().st_size
            segments[0].unlink()
            segments.pop(0)

    def write(self, kind, **fields):
        record = {"k": kind, "w": round(wall(), 4), "m": round(mono(), 4)}
        record.update(fields)
        line = json.dumps(record, separators=(",", ":")) + "\n"
        with self.lock:
            now = mono()
            if now >= self.next_disk_check:
                self.next_disk_check = now + 10
                low = shutil.disk_usage(self.dir).free < self.min_free
                if low != self.low_disk:
                    self.low_disk = low
                    self.file.write(json.dumps({"k": "note", "w": wall(), "m": now,
                                                "low_disk": low}) + "\n")
            if self.low_disk and kind not in self.ESSENTIAL:
                self.dropped += 1
                return
            self.file.write(line)
            self.size += len(line)
            if self.size >= self.segment_bytes:
                self._open()

    def flush(self):
        with self.lock:
            self.file.flush()

    def close(self):
        with self.lock:
            self.file.close()

    def status(self, data):
        tmp = self.dir / "status.json.tmp"
        tmp.write_text(json.dumps(data, separators=(",", ":")))
        tmp.replace(self.dir / "status.json")


def write_pid(role):
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    pidfile = LOG_ROOT / (role + ".pid")
    if pidfile.exists():
        try:
            old = int(pidfile.read_text())
            if b"linktest" in Path("/proc/%d/cmdline" % old).read_bytes():
                raise SystemExit("A linktest %s is already running (pid %d). Run 'stop' first." % (role, old))
        except (ValueError, OSError):
            pass
    pidfile.write_text(str(os.getpid()))
    return pidfile


# ---------------------------------------------------------------- context

class Context:
    """Samples the network situation every few seconds in a background thread.

    Records which interface each target is routed through, whether the
    Tailscale path is direct or relayed (DERP), LTE signal, interface byte
    counters, Wi-Fi state, CPU temperature and throttling. Commands that keep
    failing are retried rarely so a missing tool does not cost CPU.
    """

    def __init__(self, log, addresses, interval=5.0):
        self.log, self.addresses, self.interval = log, list(addresses), interval
        self.latest = {}
        self.stop = threading.Event()
        self.failures = {}
        self.modem = None
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        self.thread.start()

    def _try(self, key, cmd, timeout=4):
        fails, until = self.failures.get(key, (0, 0))
        if fails >= 3 and mono() < until:
            return None
        code, out, err = run(cmd, timeout)
        if code != 0:
            fails += 1
            self.failures[key] = (fails, mono() + 120 if fails >= 3 else 0)
            return None
        self.failures[key] = (0, 0)
        return out

    def add_address(self, addr):
        if addr not in self.addresses:
            self.addresses.append(addr)

    def sample(self):
        ctx = {}
        routes = {}
        for addr in list(self.addresses):
            out = self._try("route", ["ip", "-j", "route", "get", addr])
            if out:
                try:
                    r = json.loads(out)[0]
                    routes[addr] = {"dev": r.get("dev"), "src": r.get("prefsrc"), "via": r.get("gateway")}
                except (ValueError, IndexError, KeyError):
                    pass
        ctx["routes"] = routes
        ts = self._try("tailscale", ["tailscale", "status", "--json"])
        if ts:
            ctx["tailscale"] = tailscale_paths(ts, self.addresses)
        ifaces = {}
        for path in Path("/sys/class/net").glob("*"):
            if path.name == "lo":
                continue
            try:
                ifaces[path.name] = {
                    "state": (path / "operstate").read_text().strip(),
                    "rx": int((path / "statistics/rx_bytes").read_text()),
                    "tx": int((path / "statistics/tx_bytes").read_text())}
            except OSError:
                pass
        ctx["ifaces"] = ifaces
        modem = self._modem()
        if modem:
            ctx["modem"] = modem
        try:
            ctx["temp_c"] = int(Path("/sys/class/thermal/thermal_zone0/temp").read_text()) / 1000
        except (OSError, ValueError):
            pass
        thr = self._try("vcgencmd", ["vcgencmd", "get_throttled"])
        if thr and "=" in thr:
            ctx["throttled"] = thr.split("=", 1)[1]
        return ctx

    def _modem(self):
        if self.modem is None:
            out = self._try("mmcli-list", ["mmcli", "-L", "-J"])
            if not out:
                return None
            try:
                listing = json.loads(out).get("modem-list") or []
                self.modem = listing[0].rsplit("/", 1)[1] if listing else None
            except (ValueError, IndexError):
                return None
            if self.modem is None:
                return None
        out = self._try("mmcli", ["mmcli", "-m", self.modem, "-J"])
        if not out:
            self.modem = None
            return None
        try:
            m = json.loads(out)["modem"]
            g, gpp = m.get("generic", {}), m.get("3gpp", {})
            sq = g.get("signal-quality", {})
            return {"state": g.get("state"), "signal_pct": int(sq.get("value")) if sq.get("value") else None,
                    "tech": ",".join(g.get("access-technologies") or []),
                    "operator": gpp.get("operator-name"), "registration": gpp.get("registration-state")}
        except (ValueError, KeyError, TypeError):
            return None

    def _loop(self):
        while not self.stop.is_set():
            try:
                ctx = self.sample()
                self.latest = ctx
                self.log.write("ctx", **ctx)
            except Exception as error:   # never let sampling stop the test
                self.log.write("err", where="context", detail=str(error)[:300])
            self.stop.wait(self.interval)


def tailscale_paths(status_json, addresses):
    """For each address, report the Tailscale peer that carries it and whether
    that peer is reached directly or relayed through a DERP server."""
    try:
        status = json.loads(status_json)
    except ValueError:
        return {}
    peers = list((status.get("Peer") or {}).values())
    result = {}
    for addr in addresses:
        ip = ipaddress.ip_address(addr)
        found = None
        for peer in peers:
            if addr in (peer.get("TailscaleIPs") or []):
                found, kind = peer, "peer"
                break
        if found is None:
            for peer in peers:
                for net in peer.get("PrimaryRoutes") or []:
                    try:
                        if ip in ipaddress.ip_network(net, strict=False):
                            found, kind = peer, "subnet-router"
                            break
                    except ValueError:
                        continue
                if found:
                    break
        if found is None:
            result[addr] = {"peer": None}
            continue
        cur = found.get("CurAddr") or ""
        result[addr] = {"peer": found.get("HostName"), "via": kind, "online": found.get("Online"),
                        "path": "direct" if cur else ("derp:" + (found.get("Relay") or "?")),
                        "endpoint": cur or None}
    return result


# ---------------------------------------------------------------- sender

class Target:
    def __init__(self, spec, run_id):
        self.__dict__.update(spec)
        self.run = run_id
        self.sockaddr = (spec["addr"], spec["port"])
        self.tx_mono = array.array("d")      # index = seq-1
        self.confirmed = bytearray()          # 1 once the quad's bitmap shows the seq
        self.rtts = []                        # (mono_rx, rtt_ms) recent window
        self.replies = 0
        self.max_rseq = 0
        self.last_reply = None
        self.longest_silence = 0.0
        self.send_errors = 0
        self.burst_id = 0
        self.burst = None
        self.burst_results = []
        self.next_probe = 0.0
        self.next_burst = 0.0

    @property
    def sent(self):
        return len(self.tx_mono)

    def mark(self, hi, mask):
        for i in range(MASK_BITS):
            if mask >> i & 1:
                seq = hi - i
                if 1 <= seq <= len(self.confirmed):
                    self.confirmed[seq - 1] = 1

    def uplink(self, now, window=None):
        """Percent of probes the quad confirmed, among probes old enough to judge."""
        k = bisect.bisect_right(self.tx_mono, now - SETTLE_S)
        lo = bisect.bisect_left(self.tx_mono, now - SETTLE_S - window) if window else 0
        judged = k - lo
        if judged <= 0:
            return None, 0
        return 100.0 * self.confirmed[lo:k].count(1) / judged, judged


def make_run_id():
    return utc_stamp() + "-" + "".join(random.choice(string.ascii_lowercase) for _ in range(4))


def sender(args):
    plan = load_plan(args.plan)
    duration = min(args.duration or plan["duration_s"], MAX_DURATION)
    specs = targets_from_plan(plan, args.target)
    if not specs:
        raise SystemExit("No enabled targets in the plan.")
    pidfile = write_pid("sender")
    log = SessionLog("sender")
    run_id = make_run_id()
    targets = [Target(s, run_id) for s in specs]
    by_name = {t.name: t for t in targets}
    rate = float(plan["probe"]["rate_hz"])
    size = int(plan["probe"]["size_bytes"])
    b = plan["burst"]
    burst_chunks = max(1, int(b["bytes"]) // int(b["chunk_bytes"])) if b["bytes"] else 0
    chunk_gap = int(b["chunk_bytes"]) * 8 / (float(b["max_kbps"]) * 1000)
    period = 1.0 / rate

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 0))
    sock.setblocking(False)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 18)
    try:
        os.nice(5)
    except OSError:
        pass

    log.write("meta", role="sender", version=VERSION, run=run_id, host=socket.gethostname(),
              boot_id=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
              clock=clock_status(), plan=plan, targets=specs, duration_s=duration,
              local_port=sock.getsockname()[1])
    ctx = Context(log, [t.addr for t in targets])
    ctx.start()

    running = [True]

    def stop(*_):
        running[0] = False
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    start = mono()
    end = start + duration
    for i, t in enumerate(targets):
        t.next_probe = start + i * period / len(targets)
        t.next_burst = start + 10 + i * float(b["interval_s"]) / len(targets)
    next_summary = start + 1
    started_wall = wall()
    print("linktest sender run %s -> %s; logging to %s" % (
        run_id, ", ".join("%s (%s)" % (t.name, t.addr) for t in targets), log.dir), flush=True)

    def transmit(t, raw):
        try:
            sock.sendto(raw, t.sockaddr)
            return None
        except BlockingIOError:
            return "buffer_full"
        except OSError as error:
            t.send_errors += 1
            return error.strerror or str(error)

    while running[0]:
        now = mono()
        if now >= end:
            break
        due = [next_summary, end] + [t.next_probe for t in targets]
        for t in targets:
            if t.burst:
                due.append(t.burst["next"])
            elif burst_chunks:
                due.append(t.next_burst)
        wait = max(0.0, min(due) - now)
        try:
            ready, _, _ = select.select([sock], [], [], min(wait, 0.5))
        except InterruptedError:
            continue
        if ready:
            for _ in range(256):
                try:
                    data, src = sock.recvfrom(4096)
                except (BlockingIOError, InterruptedError):
                    break
                except OSError:
                    break
                handle_reply(data, src, by_name, run_id, log)
        now = mono()
        for t in targets:
            # Probes. If the loop fell behind (e.g. a stalled write), skip
            # missed slots rather than bursting to catch up.
            if now - t.next_probe > 1.0:
                log.write("note", target=t.name, skipped_s=round(now - t.next_probe, 2))
                t.next_probe = now
            while t.next_probe <= now:
                seq = t.sent + 1
                tx_wall = wall()
                raw = padded({"v": 1, "k": "p", "run": run_id, "to": t.name, "seq": seq,
                              "tx": round(tx_wall, 4)}, size)
                t.tx_mono.append(mono())
                t.confirmed.append(0)
                error = transmit(t, raw)
                log.write("tx", t=t.name, seq=seq, tw=round(tx_wall, 4), n=len(raw),
                          **({"err": error} if error else {}))
                t.next_probe += period
            # Data burst: paced chunks, then three end markers asking for a tally.
            if burst_chunks:
                if t.burst is None and now >= t.next_burst:
                    t.burst_id += 1
                    t.burst = {"id": t.burst_id, "i": 0, "next": now, "ends": 0, "start": now,
                               "start_wall": wall()}
                    t.next_burst += float(b["interval_s"])
                    log.write("bs", t=t.name, bid=t.burst_id, chunks=burst_chunks,
                              bytes=burst_chunks * int(b["chunk_bytes"]))
                bu = t.burst
                while bu and bu["next"] <= now:
                    if bu["i"] < burst_chunks:
                        raw = padded({"v": 1, "k": "b", "run": run_id, "to": t.name, "bid": bu["id"],
                                      "i": bu["i"], "n": burst_chunks}, int(b["chunk_bytes"]))
                        transmit(t, raw)
                        bu["i"] += 1
                        bu["next"] += chunk_gap
                    elif bu["ends"] < 3:
                        transmit(t, encode({"v": 1, "k": "be", "run": run_id, "to": t.name,
                                            "bid": bu["id"], "n": burst_chunks}))
                        bu["ends"] += 1
                        bu["next"] = now + 0.4
                    else:
                        # No tally after the third marker: record the burst as unconfirmed.
                        if not bu.get("acked"):
                            log.write("bend", t=t.name, bid=bu["id"], acked=False)
                            t.burst_results.append({"bid": bu["id"], "ok": False, "kbps": None,
                                                    "got": None, "n": burst_chunks})
                        t.burst = bu = None
        if now >= next_summary:
            next_summary += 1
            if now - next_summary > 2:
                next_summary = now + 1
            status = summarize(targets, now, plan, run_id, started_wall, ctx.latest, log)
            log.status(status)

    ctx.stop.set()
    final = summarize(targets, mono(), plan, run_id, started_wall, ctx.latest, log, final=True)
    log.status(final)
    log.write("end", run=run_id, reason="duration" if running[0] else "stopped",
              dropped_low_disk=log.dropped,
              totals={t.name: {"sent": t.sent, "uplink_pct": t.uplink(mono() + SETTLE_S)[0],
                               "replies": t.replies, "send_errors": t.send_errors} for t in targets})
    log.close()
    try:
        pidfile.unlink()
    except OSError:
        pass
    print("linktest sender finished; logs in %s" % log.dir, flush=True)


def handle_reply(data, src, by_name, run_id, log):
    msg = decode(data)
    if not msg or msg.get("run") != run_id:
        return
    t = by_name.get(msg.get("to"))
    if t is None:
        return
    now = mono()
    kind = msg["k"]
    if kind == "r":
        try:
            seq, hi, mask, rseq = int(msg["seq"]), int(msg["hi"]), int(msg["mask"]), int(msg["rseq"])
        except (KeyError, TypeError, ValueError):
            return
        rtt = None
        if 1 <= seq <= t.sent:
            rtt = (now - t.tx_mono[seq - 1]) * 1000
            t.rtts.append((now, rtt))
            if len(t.rtts) > 2000:
                del t.rtts[:1000]
        t.mark(hi, mask & MASK_ALL)
        t.replies += 1
        t.max_rseq = max(t.max_rseq, rseq)
        if t.last_reply is not None:
            t.longest_silence = max(t.longest_silence, now - t.last_reply)
        t.last_reply = now
        log.write("rx", t=t.name, seq=seq, rtt=round(rtt, 1) if rtt is not None else None,
                  qrx=msg.get("qrx"), qtx=msg.get("qtx"), got=msg.get("got"), hi=hi, mask=mask,
                  rseq=rseq, host=msg.get("host"),
                  **({"rsrc": src[0]} if src[0] != t.addr else {}))
    elif kind == "ba":
        span = msg.get("span") or 0
        nbytes = msg.get("bytes") or 0
        got = msg.get("got") or 0
        # span runs first->last chunk, i.e. got-1 chunk intervals; scale to got.
        kbps = round(nbytes * 8 / (span * got / (got - 1)) / 1000, 1) if span and span > 0 and got > 1 else None
        bu = t.burst
        if bu and bu["id"] == msg.get("bid") and not bu.get("acked"):
            bu["acked"] = True
            ok = msg.get("got") == msg.get("n")
            t.burst_results.append({"bid": bu["id"], "ok": ok, "kbps": kbps,
                                    "got": msg.get("got"), "n": msg.get("n")})
            log.write("ba", t=t.name, bid=bu["id"], got=msg.get("got"), n=msg.get("n"),
                      bytes=nbytes, span=span, kbps=kbps, ok=ok,
                      dur=round(now - bu["start"], 3))
            # Stop sending further end markers once the tally arrived.
            bu["ends"] = 3
    elif kind == "ha":
        log.write("hello", t=t.name, host=msg.get("host"), ver=msg.get("ver"))


def summarize(targets, now, plan, run_id, started_wall, latest_ctx, log, final=False):
    crit = plan.get("criteria", {})
    window = float(crit.get("window_s", 10))
    rows = []
    for t in targets:
        up_w, judged_w = t.uplink(now, window)
        up_all, judged = t.uplink(now)
        recent = [r for (m, r) in t.rtts if now - m <= window]
        silence = (now - t.last_reply) if t.last_reply is not None else (now - (t.tx_mono[0] if t.sent else now))
        down = 100.0 * t.replies / t.max_rseq if t.max_rseq else None
        last_burst = t.burst_results[-1] if t.burst_results else None
        route = (latest_ctx.get("routes") or {}).get(t.addr, {})
        tsp = (latest_ctx.get("tailscale") or {}).get(t.addr, {})
        row = {"name": t.name, "addr": t.addr, "sent": t.sent, "judged": judged,
               "uplink_pct_window": round(up_w, 1) if up_w is not None else None,
               "uplink_pct_all": round(up_all, 2) if up_all is not None else None,
               "downlink_pct": round(down, 1) if down is not None else None,
               "rtt_p50_ms": round(percentile(recent, 50), 0) if recent else None,
               "rtt_p95_ms": round(percentile(recent, 95), 0) if recent else None,
               "silence_s": round(silence, 1), "longest_silence_s": round(t.longest_silence, 1),
               "send_errors": t.send_errors,
               "bursts_ok": sum(1 for r in t.burst_results if r["ok"]), "bursts": len(t.burst_results),
               "last_burst_kbps": last_burst["kbps"] if last_burst else None,
               "dev": route.get("dev"), "path": tsp.get("path")}
        rows.append(row)
        if not final:
            log.write("sum", **{k: v for k, v in row.items() if k != "addr"})
    modem = latest_ctx.get("modem") or {}
    ifaces = latest_ctx.get("ifaces") or {}
    return {"role": "sender", "version": VERSION, "run": run_id, "host": socket.gethostname(),
            "updated": wall(), "elapsed_s": round(wall() - started_wall, 1), "final": final,
            "criteria": crit, "targets": rows,
            "lte": {"signal_pct": modem.get("signal_pct"), "tech": modem.get("tech"),
                    "state": modem.get("state")},
            "wifi": {k: v.get("state") for k, v in ifaces.items() if k.startswith("wl")},
            "temp_c": latest_ctx.get("temp_c"), "throttled": latest_ctx.get("throttled")}


def clock_status():
    code, out, _ = run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"])
    return {"ntp_synchronized": out == "yes" if code == 0 else None, "utc": utc_stamp()}


# ---------------------------------------------------------------- echo

class Peer:
    def __init__(self):
        self.got = 0
        self.hi = 0
        self.mask = 0
        self.rseq = 0
        self.last_rx = None
        self.rx_times = []
        self.bursts = {}
        self.tokens = 100.0
        self.token_time = mono()

    def record(self, seq):
        """Track probe receipt; returns False for a duplicate."""
        if seq > self.hi:
            shift = seq - self.hi
            self.mask = ((self.mask << shift) | 1) & MASK_ALL if shift < MASK_BITS else 1
            self.hi = seq
        elif self.hi - seq < MASK_BITS:
            bit = 1 << (self.hi - seq)
            if self.mask & bit:
                return False
            self.mask |= bit
        self.got += 1
        return True

    def allow_reply(self, limit=100.0):
        now = mono()
        self.tokens = min(limit, self.tokens + (now - self.token_time) * limit)
        self.token_time = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


def echo(args):
    plan = load_plan(args.plan)
    name = args.name
    port = int(plan["port"])
    allowed = [ipaddress.ip_network(plan["cruza"]["tailnet_ip"] + "/32")]
    allowed += [ipaddress.ip_network(n, strict=False) for n in plan["cruza"].get("extra_allow", [])]
    # The echo outlives the sender by 15 minutes so it never stops first.
    duration = min((args.duration or plan["duration_s"]) + 900, MAX_DURATION + 900)
    pidfile = write_pid("echo")
    log = SessionLog("echo")
    host = socket.gethostname()
    quad = next((q for q in plan.get("quads", []) if q.get("name") == name), {})
    binds = args.bind or quad.get("bind") or ["0.0.0.0"]
    socks = []
    for addr in binds:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind((addr, port))
        s.setblocking(False)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 18)
        socks.append(s)
    try:
        os.nice(5)
    except OSError:
        pass
    log.write("meta", role="echo", version=VERSION, name=name, host=host, port=port, binds=binds,
              allowed=[str(n) for n in allowed], boot_id=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
              clock=clock_status(), duration_s=duration)
    ctx = Context(log, [plan["cruza"]["tailnet_ip"]])
    ctx.start()
    print("linktest echo '%s' listening on UDP %s:%d; logging to %s" % (
        name, ",".join(binds), port, log.dir), flush=True)
    running = [True]

    def stop(*_):
        running[0] = False
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    peers = {}
    rejected = {}
    end = mono() + duration
    next_status = mono() + 1
    started = wall()
    sim_loss = float(os.environ.get("LINKTEST_SIMULATE_LOSS", "0") or 0)   # tests only

    while running[0] and mono() < end:
        try:
            ready, _, _ = select.select(socks, [], [], 0.5)
        except InterruptedError:
            continue
        for s in ready:
            for _ in range(256):
                try:
                    data, src = s.recvfrom(4096)
                except (BlockingIOError, InterruptedError):
                    break
                except OSError:
                    break
                rx_wall, rx_mono = wall(), mono()
                ip = ipaddress.ip_address(src[0])
                if not any(ip in n for n in allowed):
                    count = rejected.get(src[0], 0) + 1
                    rejected[src[0]] = count
                    if count in (1, 10, 100, 1000):
                        log.write("note", rejected_source=src[0], count=count)
                    continue
                if sim_loss and random.random() < sim_loss:
                    continue
                msg = decode(data)
                if not msg or not isinstance(msg.get("run"), str):
                    continue
                key = (src[0], msg["run"], str(msg.get("to")))
                peer = peers.get(key)
                if peer is None:
                    if len(peers) > 64:
                        peers.pop(next(iter(peers)))
                    peer = peers[key] = Peer()
                    ctx.add_address(src[0])
                    log.write("note", new_sender=src[0], run=msg["run"], to=msg.get("to"))
                kind = msg["k"]
                if kind == "p":
                    try:
                        seq = int(msg["seq"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    if seq < 1:
                        continue
                    fresh = peer.record(seq)
                    peer.last_rx = rx_mono
                    peer.rx_times.append(rx_mono)
                    if len(peer.rx_times) > 400:
                        del peer.rx_times[:200]
                    log.write("rx", src=src[0], run=msg["run"], to=msg.get("to"), seq=seq,
                              tx=msg.get("tx"), n=len(data), **({} if fresh else {"dup": True}))
                    if peer.allow_reply():
                        peer.rseq += 1
                        reply = {"v": 1, "k": "r", "run": msg["run"], "to": msg.get("to"), "seq": seq,
                                 "qrx": round(rx_wall, 4), "qtx": round(wall(), 4), "host": host,
                                 "got": peer.got, "hi": peer.hi, "mask": peer.mask, "rseq": peer.rseq}
                        try:
                            s.sendto(encode(reply), src)
                        except OSError as error:
                            log.write("err", where="reply", detail=error.strerror or str(error))
                elif kind == "b":
                    bid = msg.get("bid")
                    st = peer.bursts.get(bid)
                    if st is None:
                        if len(peer.bursts) > 8:
                            peer.bursts.pop(next(iter(peer.bursts)))
                        st = peer.bursts[bid] = {"first": rx_mono, "last": rx_mono, "got": set(),
                                                 "bytes": 0, "n": msg.get("n"), "logged": False}
                    i = msg.get("i")
                    if isinstance(i, int) and i not in st["got"]:
                        st["got"].add(i)
                        st["bytes"] += len(data)
                        st["last"] = rx_mono
                elif kind == "be":
                    bid = msg.get("bid")
                    st = peer.bursts.get(bid) or {"first": rx_mono, "last": rx_mono, "got": set(),
                                                  "bytes": 0, "n": msg.get("n"), "logged": False}
                    span = st["last"] - st["first"]
                    if not st["logged"]:
                        st["logged"] = True
                        log.write("brx", src=src[0], run=msg["run"], to=msg.get("to"), bid=bid,
                                  got=len(st["got"]), n=msg.get("n"), bytes=st["bytes"], span=round(span, 4))
                    ack = {"v": 1, "k": "ba", "run": msg["run"], "to": msg.get("to"), "bid": bid,
                           "got": len(st["got"]), "n": msg.get("n"), "bytes": st["bytes"],
                           "span": round(span, 4), "host": host}
                    try:
                        s.sendto(encode(ack), src)
                    except OSError:
                        pass
                elif kind == "h":
                    try:
                        s.sendto(encode({"v": 1, "k": "ha", "run": msg["run"], "to": msg.get("to"),
                                         "host": host, "ver": VERSION, "qtx": wall()}), src)
                    except OSError:
                        pass
        if mono() >= next_status:
            next_status = mono() + 1
            now = mono()
            rows = []
            for (src, run_id, to), p in list(peers.items()):
                if p.last_rx is None:
                    continue
                recent = [x for x in p.rx_times if now - x <= 10]
                rows.append({"from": src, "run": run_id, "to": to, "got": p.got, "hi": p.hi,
                             "rate_hz_10s": round(len(recent) / 10, 1),
                             "last_rx_age_s": round(now - p.last_rx, 1)})
            rows.sort(key=lambda r: r["last_rx_age_s"])
            latest = ctx.latest
            status = {"role": "echo", "version": VERSION, "name": name, "host": host, "updated": wall(),
                      "elapsed_s": round(wall() - started, 1), "port": port, "senders": rows[:8],
                      "rejected": rejected, "routes": latest.get("routes"),
                      "tailscale": latest.get("tailscale"),
                      "ifaces": {k: v.get("state") for k, v in (latest.get("ifaces") or {}).items()},
                      "temp_c": latest.get("temp_c")}
            log.status(status)
            log.write("sum", senders=rows[:8])
    ctx.stop.set()
    log.write("end", reason="duration" if running[0] else "stopped",
              peers={"%s|%s|%s" % k: {"got": p.got, "hi": p.hi} for k, p in peers.items()})
    log.close()
    try:
        pidfile.unlink()
    except OSError:
        pass
    print("linktest echo finished; logs in %s" % log.dir, flush=True)


# ---------------------------------------------------------------- preflight

def preflight(args):
    plan = load_plan(args.plan)
    specs = targets_from_plan(plan, args.target)
    print("Cruza link-test preflight  (linktest %s, %s UTC)\n" % (VERSION, utc_stamp()))
    problems = 0

    def line(ok, label, detail):
        nonlocal problems
        mark = {True: "PASS", False: "FAIL", None: "WARN"}[ok]
        if ok is False:
            problems += 1
        print("  [%s] %-28s %s" % (mark, label, detail))

    code, out, _ = run(["tailscale", "ip", "-4"])
    mine = out.splitlines()[0] if code == 0 and out else None
    line(mine == plan["cruza"]["tailnet_ip"] if mine else False, "This Pi's VPN address",
         "%s (plan expects %s)" % (mine, plan["cruza"]["tailnet_ip"]))
    clock = clock_status()
    line(True if clock["ntp_synchronized"] else None, "Clock synchronized (NTP)",
         "yes" if clock["ntp_synchronized"] else "NOT confirmed - report time-matching may be off")
    free = shutil.disk_usage(Path.home()).free / 1e6
    line(free > 500, "Free disk space", "%.0f MB" % free)
    lte_if = plan["cruza"].get("lte_interface")
    if lte_if:
        state_path = Path("/sys/class/net") / lte_if / "operstate"
        state = state_path.read_text().strip() if state_path.exists() else "missing"
        line(state in ("up", "unknown"), "LTE interface " + lte_if, state)
    for wl in sorted(Path("/sys/class/net").glob("wl*")):
        state = (wl / "operstate").read_text().strip()
        line(None if state == "up" else True, "Wi-Fi " + wl.name,
             state + (" - traffic may use Wi-Fi on the ground; it should drop out once airborne"
                      if state == "up" else ""))
    ctx = Context(None, [s["addr"] for s in specs])
    sample = ctx.sample()
    print()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 0))
    sock.settimeout(0.2)
    run_id = "preflight-" + make_run_id()
    for spec in specs:
        t = Target(spec, run_id)
        hello = None
        for _ in range(3):
            try:
                sock.sendto(encode({"v": 1, "k": "h", "run": run_id, "to": t.name}), t.sockaddr)
            except OSError as error:
                hello = "send failed: %s" % (error.strerror or error)
                break
        rtts = []
        for seq in range(1, 11):
            t.tx_mono.append(mono())
            t.confirmed.append(0)
            try:
                sock.sendto(padded({"v": 1, "k": "p", "run": run_id, "to": t.name, "seq": seq,
                                    "tx": wall()}, int(plan["probe"]["size_bytes"])), t.sockaddr)
            except OSError:
                pass
            deadline = mono() + 0.25
            while mono() < deadline:
                try:
                    data, src = sock.recvfrom(4096)
                except socket.timeout:
                    break
                except OSError:
                    break
                msg = decode(data)
                if not msg or msg.get("to") != t.name:
                    continue
                if msg["k"] == "ha":
                    hello = "echo on %s (v%s)" % (msg.get("host"), msg.get("ver"))
                elif msg["k"] == "r":
                    s = int(msg.get("seq", 0))
                    if 1 <= s <= t.sent:
                        rtts.append((mono() - t.tx_mono[s - 1]) * 1000)
                    t.mark(int(msg.get("hi", 0)), int(msg.get("mask", 0)))
        time.sleep(0.5)
        try:
            while True:
                data, src = sock.recvfrom(4096)
                msg = decode(data)
                if msg and msg.get("k") == "r" and msg.get("to") == t.name:
                    t.mark(int(msg.get("hi", 0)), int(msg.get("mask", 0)))
                    rtts.append(None)
                elif msg and msg.get("k") == "ha" and msg.get("to") == t.name:
                    hello = "echo on %s (v%s)" % (msg.get("host"), msg.get("ver"))
        except (socket.timeout, OSError):
            pass
        got = sum(t.confirmed)
        route = sample.get("routes", {}).get(t.addr, {})
        tsp = sample.get("tailscale", {}).get(t.addr, {})
        valid = [r for r in rtts if r is not None]
        detail = "%d/10 probes delivered, RTT median %s ms; route via %s%s; %s" % (
            got, "%.0f" % statistics.median(valid) if valid else "-", route.get("dev") or "?",
            (", tailscale " + tsp["path"] + " via " + str(tsp.get("peer"))) if tsp.get("path") else "",
            hello or "no answer from echo")
        line(got >= 9 if got else False, t.name + " " + t.addr, detail)
    print()
    if problems:
        print("%d check(s) FAILED. Fix these before flying the test." % problems)
        print("Hints: no answer at all usually means the echo is not running on that quad,\n"
              "a VPN access rule blocks UDP %d, or (mesh path) the quad has no route back to\n"
              "the Cruza's VPN address." % plan["port"])
    else:
        print("All required checks passed.")
    return 1 if problems else 0


# ---------------------------------------------------------------- watch / stop

def colour(text, level):
    codes = {"good": "32", "warn": "33", "bad": "31", "dim": "2"}
    return "\033[%sm%s\033[0m" % (codes[level], text) if sys.stdout.isatty() else text


def fmt(value, unit=""):
    return "-" if value is None else ("%s%s" % (value, unit))


def watch(args):
    status_path = (LOG_ROOT / ("current-" + args.role) / "status.json") if not args.dir else Path(args.dir) / "status.json"
    while True:
        try:
            st = json.loads(status_path.read_text())
        except (OSError, ValueError):
            st = None
        out = ["\033[2J\033[H" if sys.stdout.isatty() else "",
               "Cruza link test - %s   (%s UTC)   Ctrl+C to quit watching (the test keeps running)\n" % (
                   args.role, dt.datetime.now(dt.timezone.utc).strftime("%H:%M:%S"))]
        if st is None:
            out.append("No status yet at %s. Is the %s running?" % (status_path, args.role))
        else:
            age = wall() - st.get("updated", 0)
            if st.get("final"):
                out.append(colour("Test finished.", "warn"))
            elif age > 5:
                out.append(colour("Status is %.0f s old - the %s may have stopped." % (age, args.role), "bad"))
            out.append("Host %s   run %s   elapsed %s s" % (st.get("host"), st.get("run", "-"), st.get("elapsed_s")))
            if st["role"] == "sender":
                crit = st.get("criteria") or {}
                need_up = crit.get("window_min_pct", 90)
                need_rtt = crit.get("rtt_p95_ms", 1000)
                lte = st.get("lte") or {}
                out.append("LTE signal %s%%  %s  %s   Wi-Fi %s   CPU %s C  throttled %s\n" % (
                    fmt(lte.get("signal_pct")), fmt(lte.get("tech")), fmt(lte.get("state")),
                    ", ".join("%s=%s" % kv for kv in (st.get("wifi") or {}).items()) or "-",
                    fmt(st.get("temp_c")), fmt(st.get("throttled"))))
                out.append("%-18s %6s %8s %8s %7s %7s %7s %8s %9s %-7s %s" % (
                    "TARGET", "SENT", "UP 10s", "UP all", "DOWN", "RTT50", "RTT95",
                    "SILENT", "BURSTS", "ROUTE", "PATH"))
                for r in st.get("targets", []):
                    up = r.get("uplink_pct_window")
                    level = "good" if up is not None and up >= need_up else ("warn" if up and up >= 50 else "bad")
                    rtt95 = r.get("rtt_p95_ms")
                    if rtt95 is not None and rtt95 > need_rtt and level == "good":
                        level = "warn"
                    if r.get("silence_s", 0) > 5:
                        level = "bad"
                    text = "%-18s %6s %7s%% %7s%% %6s%% %6sms %6sms %7ss %9s %-7s %s" % (
                        r["name"], r["sent"], fmt(up), fmt(r.get("uplink_pct_all")), fmt(r.get("downlink_pct")),
                        fmt(r.get("rtt_p50_ms")), fmt(r.get("rtt_p95_ms")), fmt(r.get("silence_s")),
                        "%s/%s %s" % (r.get("bursts_ok"), r.get("bursts"),
                                      ("%skb/s" % int(r["last_burst_kbps"])) if r.get("last_burst_kbps") else ""),
                        fmt(r.get("dev")), fmt(r.get("path")))
                    out.append(colour(text, level))
                out.append("\nUP = probes the quad confirmed receiving. DOWN = quad replies that got back.\n"
                           "SILENT = seconds since the last reply. Green >= %s%% delivered in the last 10 s." % need_up)
            else:
                out.append("Interfaces: %s   CPU %s C\n" % (
                    ", ".join("%s=%s" % kv for kv in (st.get("ifaces") or {}).items()), fmt(st.get("temp_c"))))
                out.append("%-16s %-24s %-18s %8s %8s %10s" % ("FROM", "RUN", "TARGET", "GOT", "RATE", "LAST RX"))
                for r in st.get("senders", []):
                    level = "good" if r["last_rx_age_s"] < 2 else ("warn" if r["last_rx_age_s"] < 5 else "bad")
                    out.append(colour("%-16s %-24s %-18s %8s %6sHz %8ss ago" % (
                        r["from"], r["run"], r["to"], r["got"], r["rate_hz_10s"], r["last_rx_age_s"]), level))
                if not st.get("senders"):
                    out.append("Nothing received from the Cruza yet.")
                if st.get("rejected"):
                    out.append(colour("Ignored packets from unexpected addresses: %s" % st["rejected"], "warn"))
        print("\n".join(out), flush=True)
        if args.once:
            return 0
        try:
            time.sleep(1)
        except KeyboardInterrupt:
            return 0


def stop_role(args):
    pidfile = LOG_ROOT / (args.role + ".pid")
    if not pidfile.exists():
        print("No running %s found." % args.role)
        return 0
    try:
        pid = int(pidfile.read_text())
        if b"linktest" not in Path("/proc/%d/cmdline" % pid).read_bytes():
            raise OSError
    except (ValueError, OSError):
        print("Stale pid file removed; nothing was running.")
        pidfile.unlink()
        return 0
    os.kill(pid, signal.SIGTERM)
    for _ in range(50):
        if not Path("/proc/%d" % pid).exists():
            break
        time.sleep(0.1)
    print("Stopped %s (pid %d). Logs: %s" % (args.role, pid, (LOG_ROOT / ("current-" + args.role)).resolve()))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=VERSION)
    sub = parser.add_subparsers(dest="cmd", required=True)
    here = Path(__file__).resolve().parent / "plan.json"
    p = sub.add_parser("send", help="run on the Cruza Pi")
    p.add_argument("--plan", default=str(here))
    p.add_argument("--target", action="append", help="limit to a quad or quad/path (repeatable)")
    p.add_argument("--duration", type=int, help="seconds (default from plan)")
    p = sub.add_parser("echo", help="run on a quad Pi")
    p.add_argument("--plan", default=str(here))
    p.add_argument("--name", required=True, help="this quad's name, as in the plan")
    p.add_argument("--bind", action="append", help="local address to listen on (repeatable; default all)")
    p.add_argument("--duration", type=int)
    p = sub.add_parser("preflight", help="ground check, on the Cruza Pi")
    p.add_argument("--plan", default=str(here))
    p.add_argument("--target", action="append")
    p = sub.add_parser("watch", help="live status table")
    p.add_argument("--role", choices=["sender", "echo"], default="sender")
    p.add_argument("--dir", help="session folder (default: the current one)")
    p.add_argument("--once", action="store_true")
    p = sub.add_parser("stop", help="stop a background send/echo")
    p.add_argument("--role", choices=["sender", "echo"], required=True)
    args = parser.parse_args(argv)
    if args.cmd == "send":
        return sender(args)
    if args.cmd == "echo":
        return echo(args)
    if args.cmd == "preflight":
        return preflight(args)
    if args.cmd == "watch":
        return watch(args)
    if args.cmd == "stop":
        return stop_role(args)


if __name__ == "__main__":
    sys.exit(main() or 0)
