#!/usr/bin/env python3
"""Build the post-flight report for a Cruza -> quad link test.

Typical use (on the laptop, after run-linktest.ps1 collect):

  python linktest/report.py --collected linktest-results/2026-10-23_1405 \
      --cruza-log logs/2026-10-23/download-.../log_00031.BIN

Inputs
  --collected   folder holding the sender and echo session folders copied off
                the Pis (any depth). The newest sender run is used unless --run.
  --cruza-log   the Cruza's ArduPilot DataFlash .BIN (or a .tlog) for GPS,
                altitude and arm/disarm times. Optional but needed for range.
  --cruza-track alternative to --cruza-log: CSV with time_utc,lat,lon,alt_m.
  --quad-log    NAME=PATH, a quad's own .BIN/.tlog to get its position track.
  --plan        plan.json (criteria, quad fixed positions). Defaults to the
                plan recorded by the sender at the start of the run.

Output: report.html (self-contained, prints well) plus CSV files and
summary.json in --out (default: <collected>/report).
"""
import argparse
import base64
import bisect
import csv
import datetime as dt
import html
import io
import json
import math
from pathlib import Path
import statistics
import sys

# Same private dependency folder the other flight-log tools use (see tools/).
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".flightlog-deps"))

GPS_EPOCH = 315964800      # 1980-01-06 in Unix time
LEAP_SECONDS = 18          # GPS - UTC since 2017

DEFAULT_CRITERIA = {
    "uplink_delivery_pct": 98.0,   # overall share of probes that reached the quad
    "window_s": 10,                # length of the rolling window
    "window_min_pct": 90.0,        # a window "passes" at or above this delivery
    "windows_pass_pct": 95.0,      # share of windows that must pass
    "rtt_p95_ms": 1000.0,          # 95th-percentile round-trip time
    "max_outage_s": 5.0,           # longest continuous loss allowed
    "burst_complete_pct": 90.0,    # share of data bursts fully delivered
    "burst_min_kbps": 64.0,        # median burst throughput (kbit/s)
    "min_probes": 300,             # fewer airborne probes -> inconclusive
    "min_distance_m": 1000.0,      # must fly at least this far for a range verdict
    "distance_bin_m": 250.0,
}


# ---------------------------------------------------------------- loading

def read_events(folder):
    for path in sorted(Path(folder).glob("events-*.jsonl")):
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    yield json.loads(line)
                except ValueError:
                    continue      # a torn final line after power loss


def find_sessions(root):
    sessions = []
    for meta_dir in {p.parent for p in Path(root).rglob("events-*.jsonl")}:
        if meta_dir.name.startswith("current-"):
            continue
        for rec in read_events(meta_dir):
            if rec.get("k") == "meta":
                sessions.append((meta_dir, rec))
            break
    return sessions


def load_sender(folder, run_id):
    s = {"meta": None, "tx": {}, "rx": {}, "bitmaps": {}, "bursts": {}, "ctx": [], "end": None,
         "notes": [], "hello": {}}
    for r in read_events(folder):
        k = r.get("k")
        if k == "meta":
            s["meta"] = r
        elif k == "tx":
            s["tx"].setdefault(r["t"], {})[r["seq"]] = (r["tw"], r.get("err"))
        elif k == "rx":
            s["rx"].setdefault(r["t"], {}).setdefault(r["seq"], r)
            s["bitmaps"].setdefault(r["t"], []).append((r["hi"], r["mask"]))
        elif k == "bs":
            s["bursts"].setdefault(r["t"], {})[r["bid"]] = {"time": r["w"], "n": r["chunks"], "ok": False,
                                                            "kbps": None, "got": None, "acked": False}
        elif k == "ba":
            b = s["bursts"].setdefault(r["t"], {}).setdefault(r["bid"], {"time": r["w"], "n": r["n"]})
            b.update(ok=bool(r.get("ok")), kbps=r.get("kbps"), got=r.get("got"), acked=True)
        elif k == "ctx":
            s["ctx"].append(r)
        elif k == "end":
            s["end"] = r
        elif k in ("note", "err"):
            s["notes"].append(r)
    if s["meta"] is None or (run_id and s["meta"].get("run") != run_id):
        return None
    return s


def load_echo(folder, run_id):
    """Returns meta, {target_name: {seq: rx_wall}} for probes from this run,
    and per target the (first, last) probe number this session received."""
    got, meta = {}, None
    for r in read_events(folder):
        if r.get("k") == "meta":
            meta = r
        elif r.get("k") == "rx" and r.get("run") == run_id and not r.get("dup"):
            got.setdefault(r.get("to"), {})[r["seq"]] = r["w"]
    spans = {t: (min(v), max(v)) for t, v in got.items()}
    return meta, got, spans


def load_track_bin(path):
    """GPS track and arm/disarm times from a DataFlash .BIN or a .tlog."""
    from pymavlink import mavutil      # only needed when a flight log is given
    conn = mavutil.mavlink_connection(str(path))
    track, armed, disarmed = [], [], []
    last_utc = None
    stat_armed = False
    is_tlog = str(path).lower().endswith(".tlog")
    while True:
        m = conn.recv_match(type=["GPS", "ARM", "EV", "STAT", "MSG", "GLOBAL_POSITION_INT", "HEARTBEAT"])
        if m is None:
            break
        t = m.get_type()
        if t == "GPS" and getattr(m, "Status", 0) >= 3 and getattr(m, "GWk", 0) > 0:
            utc = GPS_EPOCH + m.GWk * 604800 + m.GMS / 1000.0 - LEAP_SECONDS
            last_utc = (utc, m.TimeUS)
            track.append((utc, m.Lat, m.Lng, m.Alt, m.Spd))
        elif t in ("ARM", "EV", "STAT", "MSG") and last_utc:
            # Arming shows up in different records depending on firmware and
            # when logging started: ARM/EV events, the periodic STAT.Armed
            # flag, or the "Throttle armed" text. Any of them is enough.
            utc = last_utc[0] + (m.TimeUS - last_utc[1]) / 1e6
            text = getattr(m, "Message", "") if t == "MSG" else ""
            if t == "STAT":
                state = bool(m.Armed)
                if state != stat_armed:
                    (armed if state else disarmed).append(utc)
                    stat_armed = state
            elif (t == "ARM" and m.ArmState == 1) or (t == "EV" and m.Id == 10) or \
                    text.startswith(("Throttle armed", "Arming motors")):
                armed.append(utc)
            elif (t == "ARM" and m.ArmState == 0) or (t == "EV" and m.Id == 11) or \
                    text.startswith(("Throttle disarmed", "Disarming motors")):
                disarmed.append(utc)
        elif is_tlog and t == "GLOBAL_POSITION_INT":
            ts = getattr(m, "_timestamp", None)
            if ts and m.lat:
                track.append((ts, m.lat / 1e7, m.lon / 1e7, m.alt / 1000.0, math.hypot(m.vx, m.vy) / 100))
        elif is_tlog and t == "HEARTBEAT" and m.get_srcComponent() == 1:
            ts = getattr(m, "_timestamp", None)
            is_armed = bool(m.base_mode & 128)
            if ts and is_armed and (not armed or (disarmed and disarmed[-1] > armed[-1])):
                armed.append(ts)
            if ts and not is_armed and armed and (not disarmed or disarmed[-1] < armed[-1]):
                disarmed.append(ts)
    track.sort()
    flights = []
    starts = []
    for x in sorted(armed):
        if not starts or x - starts[-1] > 3:
            starts.append(x)
    for a in starts:
        later = [d for d in disarmed if d > a]
        flights.append((a, min(later) if later else (track[-1][0] if track else a)))
    merged = []
    for a, d in flights:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(d, merged[-1][1]))
        else:
            merged.append((a, d))
    return track, merged


def load_track_csv(path):
    track = []
    with open(path, newline="") as handle:
        for row in csv.DictReader(handle):
            t = row["time_utc"]
            try:
                utc = float(t)
            except ValueError:
                utc = dt.datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp()
            track.append((utc, float(row["lat"]), float(row["lon"]), float(row.get("alt_m") or 0), None))
    track.sort()
    return track, []


# ---------------------------------------------------------------- geometry

def metres(lat1, lon1, lat2, lon2):
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class Track:
    def __init__(self, rows):
        self.rows = rows
        self.times = [r[0] for r in rows]

    def at(self, t, max_gap=3.0):
        """Linear interpolation; None outside the track or across a gap."""
        if not self.rows:
            return None
        i = bisect.bisect_left(self.times, t)
        if i == 0 or i >= len(self.rows):
            if i < len(self.rows) and abs(self.times[i] - t) <= 1:
                return self.rows[i][1:4]
            if i and abs(self.times[i - 1] - t) <= 1:
                return self.rows[i - 1][1:4]
            return None
        a, b = self.rows[i - 1], self.rows[i]
        if b[0] - a[0] > max_gap:
            # Logging gap (e.g. not logging while disarmed): use a sample within 1 s.
            near = a if t - a[0] < b[0] - t else b
            return near[1:4] if abs(near[0] - t) <= 1 else None
        f = (t - a[0]) / (b[0] - a[0]) if b[0] > a[0] else 0
        return tuple(a[j] + (b[j] - a[j]) * f for j in (1, 2, 3))


# ---------------------------------------------------------------- analysis

def pct(values, q):
    if not values:
        return None
    v = sorted(values)
    k = (len(v) - 1) * q / 100
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def context_at(ctx_list, ctx_times, t):
    i = bisect.bisect_right(ctx_times, t) - 1
    if i < 0:
        return {}
    return ctx_list[i] if t - ctx_times[i] < 30 else {}


def analyse_target(name, spec, sender, echo_rx, cruza, quad_pos, quad_track, home, flights, crit, period):
    tx = sender["tx"].get(name, {})
    rx = sender["rx"].get(name, {})
    seqs = sorted(tx)
    # Probes the quad confirmed in its replies (each reply carries a 64-probe bitmap).
    confirmed = set()
    for hi, mask in sender["bitmaps"].get(name, []):
        for i in range(64):
            if mask >> i & 1:
                confirmed.add(hi - i)
    # The quad's own receive log is authoritative for the stretch of probes each
    # collected echo session saw (by sequence number, so a wrong quad clock does
    # not matter). Outside that (echo restarted, log missing) fall back to replies.
    received, spans = (echo_rx or ({}, []))
    covered = lambda seq: any(a <= seq <= b for a, b in spans)
    delivered, from_log = {}, 0
    for s in seqs:
        if covered(s):
            delivered[s] = s in received or s in confirmed
            from_log += 1
        else:
            delivered[s] = s in confirmed
    if from_log == len(seqs) and seqs:
        delivered_src = "quad's own receive log"
    elif from_log:
        delivered_src = "quad's receive log for %.0f%% of probes, quad replies for the rest" % (
            100.0 * from_log / len(seqs))
    else:
        delivered_src = "quad replies only (no quad log collected for this period)"
    ctx_list = sender["ctx"]
    ctx_times = [c["w"] for c in ctx_list]
    rows = []
    for s in seqs:
        tw, err = tx[s]
        rep = rx.get(s)
        pos = cruza.at(tw) if cruza else None
        airborne = any(a <= tw <= d for a, d in flights) if flights else None
        d_home = metres(home[0], home[1], pos[0], pos[1]) if pos and home else None
        alt = (pos[2] - home[2]) if pos and home else None
        qp = quad_track.at(tw) if quad_track else quad_pos
        d_quad = None
        if pos and qp:
            horiz = metres(qp[0], qp[1], pos[0], pos[1])
            dz = (pos[2] - qp[2]) if (len(qp) > 2 and qp[2] is not None) else 0
            d_quad = math.hypot(horiz, dz)
        c = context_at(ctx_list, ctx_times, tw)
        route = (c.get("routes") or {}).get(spec["addr"], {})
        tsp = (c.get("tailscale") or {}).get(spec["addr"], {})
        modem = c.get("modem") or {}
        wifi_up = any(v.get("state") == "up" for k, v in (c.get("ifaces") or {}).items() if k.startswith("wl"))
        rows.append({"seq": s, "t": tw, "delivered": delivered[s], "send_error": err,
                     "reply": rep is not None, "rtt_ms": rep.get("rtt") if rep else None,
                     "qrx": rep.get("qrx") if rep else None, "qtx": rep.get("qtx") if rep else None,
                     "lat": pos[0] if pos else None, "lon": pos[1] if pos else None,
                     "alt_m": alt, "dist_home_m": d_home, "dist_quad_m": d_quad, "airborne": airborne,
                     "dev": route.get("dev"), "ts_path": tsp.get("path"),
                     "lte_signal_pct": modem.get("signal_pct"), "lte_tech": modem.get("tech"),
                     "wifi_up": wifi_up})
    scope = [r for r in rows if r["airborne"]] if flights else rows
    scope_label = "airborne (armed) period from the flight log" if flights else "whole test session (no flight log given)"
    result = {"name": name, "spec": spec, "rows": rows, "scope_label": scope_label,
              "delivered_source": delivered_src}
    if not scope:
        result.update(verdict="INCONCLUSIVE", reasons=["No probes were sent during the airborne period."],
                      checks=[], windows=[], outages=[], bursts=[], bins=[], metrics={})
        return result

    # rolling windows
    w = float(crit["window_s"])
    t0 = scope[0]["t"]
    windows = {}
    for r in scope:
        windows.setdefault(int((r["t"] - t0) // w), []).append(r)
    win_rows = []
    for k in sorted(windows):
        rs = windows[k]
        rtts = [r["rtt_ms"] for r in rs if r["rtt_ms"] is not None]
        dists = [r["dist_home_m"] for r in rs if r["dist_home_m"] is not None]
        dq = [r["dist_quad_m"] for r in rs if r["dist_quad_m"] is not None]
        sig = [r["lte_signal_pct"] for r in rs if r["lte_signal_pct"] is not None]
        win_rows.append({"start": t0 + k * w, "probes": len(rs),
                         "uplink_pct": 100.0 * sum(r["delivered"] for r in rs) / len(rs),
                         "reply_pct": 100.0 * sum(r["reply"] for r in rs) / len(rs),
                         "rtt_p50_ms": pct(rtts, 50), "rtt_p95_ms": pct(rtts, 95),
                         "dist_home_m": statistics.median(dists) if dists else None,
                         "dist_quad_m": statistics.median(dq) if dq else None,
                         "lte_signal_pct": statistics.median(sig) if sig else None,
                         "dev": rs[-1]["dev"], "ts_path": rs[-1]["ts_path"], "wifi_up": rs[-1]["wifi_up"]})

    # outages: runs of consecutive undelivered probes
    outages, run_start = [], None
    for i, r in enumerate(scope + [None]):
        lost = r is not None and not r["delivered"]
        if lost and run_start is None:
            run_start = i
        elif not lost and run_start is not None:
            first, last = scope[run_start], scope[i - 1]
            outages.append({"start": first["t"], "duration_s": last["t"] - first["t"] + period,
                            "probes_lost": i - run_start, "dist_home_m": first["dist_home_m"],
                            "dist_quad_m": first["dist_quad_m"], "alt_m": first["alt_m"],
                            "dev": first["dev"], "ts_path": first["ts_path"],
                            "lte_signal_pct": first["lte_signal_pct"]})
            run_start = None

    # bursts
    bursts = []
    session_end = scope[-1]["t"]
    for bid, b in sorted(sender["bursts"].get(name, {}).items()):
        if flights and not any(a <= b["time"] <= d for a, d in flights):
            continue
        if not b.get("acked") and b["time"] > session_end - 5:
            continue      # cut off by the end of the test, not a link failure
        pos = cruza.at(b["time"]) if cruza else None
        bursts.append({"bid": bid, "time": b["time"], "complete": bool(b.get("ok")), "acked": b.get("acked", False),
                       "chunks_got": b.get("got"), "chunks": b.get("n"), "kbps": b.get("kbps"),
                       "dist_home_m": metres(home[0], home[1], pos[0], pos[1]) if pos and home else None})

    # distance bins
    bin_m = float(crit["distance_bin_m"])
    key = "dist_quad_m" if any(r["dist_quad_m"] is not None for r in scope) else "dist_home_m"
    bins = {}
    for r in scope:
        if r[key] is not None:
            bins.setdefault(int(r[key] // bin_m), []).append(r)
    bin_rows = []
    for k in sorted(bins):
        rs = bins[k]
        rtts = [r["rtt_ms"] for r in rs if r["rtt_ms"] is not None]
        bin_rows.append({"from_m": k * bin_m, "to_m": (k + 1) * bin_m, "probes": len(rs),
                         "uplink_pct": 100.0 * sum(r["delivered"] for r in rs) / len(rs),
                         "rtt_p95_ms": pct(rtts, 95)})
    good_range = 0.0
    for b in bin_rows:
        if b["uplink_pct"] >= crit["window_min_pct"] and b["probes"] >= 10:
            good_range = b["to_m"]
        else:
            break
    far = [r[key] for r in scope if r[key] is not None]
    far_ok = [r[key] for r in scope if r[key] is not None and r["delivered"]]

    rtts = [r["rtt_ms"] for r in scope if r["rtt_ms"] is not None]
    uplink = 100.0 * sum(r["delivered"] for r in scope) / len(scope)
    win_pass = 100.0 * sum(1 for x in win_rows if x["uplink_pct"] >= crit["window_min_pct"]) / len(win_rows)
    longest = max((o["duration_s"] for o in outages), default=0.0)
    kbps = [b["kbps"] for b in bursts if b["kbps"] is not None and b["complete"]]
    burst_ok = 100.0 * sum(b["complete"] for b in bursts) / len(bursts) if bursts else None
    offsets = [((r["qrx"] - r["t"]) + (r["qtx"] - (r["t"] + r["rtt_ms"] / 1000))) / 2
               for r in scope if r["qrx"] and r["qtx"] and r["rtt_ms"] is not None]
    metrics = {"probes": len(scope), "uplink_pct": uplink, "windows": len(win_rows), "windows_pass_pct": win_pass,
               "rtt_p50_ms": pct(rtts, 50), "rtt_p95_ms": pct(rtts, 95), "rtt_max_ms": max(rtts) if rtts else None,
               "reply_pct": 100.0 * sum(r["reply"] for r in scope) / len(scope),
               "longest_outage_s": longest, "outages_over_1s": sum(1 for o in outages if o["duration_s"] >= 1),
               "bursts": len(bursts), "burst_complete_pct": burst_ok,
               "burst_median_kbps": statistics.median(kbps) if kbps else None,
               "distance_basis": "distance to the quad" if key == "dist_quad_m" else "distance from the Cruza's launch point",
               "max_distance_m": max(far) if far else None,
               "max_distance_delivered_m": max(far_ok) if far_ok else None,
               "contiguous_good_range_m": good_range if far else None,
               "max_alt_m": max((r["alt_m"] for r in scope if r["alt_m"] is not None), default=None),
               "clock_offset_s": statistics.median(offsets) if offsets else None,
               "send_errors": sum(1 for r in scope if r["send_error"]),
               "time_on_wifi_pct": 100.0 * sum(r["wifi_up"] for r in scope) / len(scope),
               "paths": sorted({str(r["ts_path"]) for r in scope if r["ts_path"]}),
               "routes": sorted({str(r["dev"]) for r in scope if r["dev"]})}

    checks = []

    def check(label, value, limit, ok, unit=""):
        checks.append({"label": label, "value": value, "limit": limit, "unit": unit, "ok": ok})
    check("Overall delivery to the quad", uplink, ">= %g" % crit["uplink_delivery_pct"],
          uplink >= crit["uplink_delivery_pct"], "%")
    check("%g s windows at or above %g%% delivery" % (w, crit["window_min_pct"]), win_pass,
          ">= %g" % crit["windows_pass_pct"], win_pass >= crit["windows_pass_pct"], "%")
    check("Round-trip time, 95th percentile", metrics["rtt_p95_ms"], "<= %g" % crit["rtt_p95_ms"],
          None if metrics["rtt_p95_ms"] is None else metrics["rtt_p95_ms"] <= crit["rtt_p95_ms"], " ms")
    check("Longest continuous loss", longest, "<= %g" % crit["max_outage_s"], longest <= crit["max_outage_s"], " s")
    if bursts:
        check("Data bursts fully delivered", burst_ok, ">= %g" % crit["burst_complete_pct"],
              burst_ok >= crit["burst_complete_pct"], "%")
        check("Median burst throughput", metrics["burst_median_kbps"], ">= %g" % crit["burst_min_kbps"],
              None if metrics["burst_median_kbps"] is None else metrics["burst_median_kbps"] >= crit["burst_min_kbps"],
              " kbit/s")
    reasons = []
    if len(scope) < crit["min_probes"]:
        reasons.append("Only %d probes in scope (need %d)." % (len(scope), crit["min_probes"]))
    if not cruza:
        reasons.append("No Cruza flight log or track: distance and airborne period unknown.")
    elif metrics["max_distance_m"] is None or metrics["max_distance_m"] < crit["min_distance_m"]:
        reasons.append("The Cruza only reached %s m (need %g m) - range not demonstrated." % (
            "%.0f" % metrics["max_distance_m"] if metrics["max_distance_m"] is not None else "?",
            crit["min_distance_m"]))
    if any(c["ok"] is False for c in checks):
        verdict = "FAIL"
    elif reasons:
        verdict = "INCONCLUSIVE"
    else:
        verdict = "PASS"
    result.update(verdict=verdict, reasons=reasons, checks=checks, windows=win_rows, outages=outages,
                  bursts=bursts, bins=bin_rows, metrics=metrics, distance_key=key)
    return result


# ---------------------------------------------------------------- charts

def png(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    import matplotlib.pyplot as plt
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


COLOURS = ["#2a6fdb", "#d9822b", "#2e9e5b", "#9b51e0", "#c0392b", "#16a2b8"]


def charts(results, cruza, flights, home, crit, quad_positions, t_ref):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    out = {}
    tz = dt.timezone.utc

    def clock(t):
        return dt.datetime.fromtimestamp(t, tz)

    # 1. timeline
    fig, axes = plt.subplots(4, 1, figsize=(11, 10), sharex=True,
                             gridspec_kw={"height_ratios": [1.1, 1.2, 1, 0.8]})
    ax = axes[0]
    any_dist = False
    for i, res in enumerate(results):
        rs = [r for r in res["rows"] if r["dist_home_m"] is not None]
        if rs and i == 0:
            ax.plot([clock(r["t"]) for r in rs], [r["dist_home_m"] / 1000 for r in rs], color="#444", lw=1.2,
                    label="distance from launch (km)")
            ax2 = ax.twinx()
            ax2.plot([clock(r["t"]) for r in rs], [r["alt_m"] for r in rs], color="#999", lw=0.8, ls="--",
                     label="height above launch (m)")
            ax2.set_ylabel("height (m)")
            any_dist = True
    ax.set_ylabel("km from launch")
    ax.set_title("Cruza position" if any_dist else "Cruza position (no flight log provided)")
    for i, res in enumerate(results):
        c = COLOURS[i % len(COLOURS)]
        wr = res["windows"]
        axes[1].plot([clock(x["start"]) for x in wr], [x["uplink_pct"] for x in wr], color=c, lw=1.3,
                     label=res["name"])
        axes[2].plot([clock(x["start"]) for x in wr], [x["rtt_p95_ms"] for x in wr], color=c, lw=1.1,
                     label=res["name"] + " p95")
        for o in res["outages"]:
            if o["duration_s"] >= 1:
                axes[1].axvspan(clock(o["start"]), clock(o["start"] + o["duration_s"]), color=c, alpha=0.15)
    axes[1].axhline(crit["window_min_pct"], color="#c0392b", lw=0.8, ls=":")
    axes[1].set_ylim(-3, 103)
    axes[1].set_ylabel("% delivered")
    axes[1].set_title("Data delivered to each quad (%g s windows; shading = continuous loss)" % crit["window_s"])
    axes[1].legend(loc="lower left", fontsize=8)
    axes[2].axhline(crit["rtt_p95_ms"], color="#c0392b", lw=0.8, ls=":")
    axes[2].set_yscale("log")
    axes[2].set_ylabel("ms")
    axes[2].set_title("Round-trip time, 95th percentile")
    axes[2].legend(loc="upper left", fontsize=8)
    if results and results[0]["windows"]:
        wr = results[0]["windows"]
        sig = [(clock(x["start"]), x["lte_signal_pct"]) for x in wr if x["lte_signal_pct"] is not None]
        if sig:
            axes[3].plot([s[0] for s in sig], [s[1] for s in sig], color="#16a2b8", lw=1.2, label="LTE signal %")
        wifi = [(clock(x["start"]), 100 if x["wifi_up"] else 0) for x in wr]
        axes[3].step([w[0] for w in wifi], [w[1] for w in wifi], color="#d9822b", lw=0.8, where="post",
                     label="Cruza Wi-Fi connected (100=yes)")
        axes[3].set_ylim(-5, 105)
        axes[3].legend(loc="lower left", fontsize=8)
    axes[3].set_title("Cruza companion radio state")
    for a in axes:
        a.grid(alpha=0.25)
        for f0, f1 in flights:
            a.axvspan(clock(f0), clock(f1), color="#2e9e5b", alpha=0.05)
    axes[-1].set_xlabel("UTC time (green tint = armed)")
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=tz))
    out["timeline"] = png(fig)

    # 2. delivery and RTT vs distance
    if any(res.get("bins") for res in results):
        fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
        width = crit["distance_bin_m"] / 1000 / (len(results) + 1)
        for i, res in enumerate(results):
            b = res.get("bins") or []
            x = [bb["from_m"] / 1000 + width * (i + 0.5) for bb in b]
            axes[0].bar(x, [bb["uplink_pct"] for bb in b], width=width, color=COLOURS[i % len(COLOURS)],
                        label=res["name"])
            axes[1].plot([(bb["from_m"] + bb["to_m"]) / 2000 for bb in b], [bb["rtt_p95_ms"] for bb in b], "o-",
                         color=COLOURS[i % len(COLOURS)], label=res["name"], ms=3)
        bases = {res["metrics"].get("distance_basis") for res in results if res.get("bins")}
        basis = bases.pop() if len(bases) == 1 else "distance (to the quad where its position is known, else from launch)"
        axes[0].axhline(crit["window_min_pct"], color="#c0392b", lw=0.8, ls=":")
        axes[0].set_ylim(0, 103)
        axes[0].set_title("Delivery by " + basis)
        axes[0].set_xlabel("km")
        axes[0].set_ylabel("% delivered")
        axes[1].axhline(crit["rtt_p95_ms"], color="#c0392b", lw=0.8, ls=":")
        axes[1].set_title("RTT p95 by " + basis)
        axes[1].set_xlabel("km")
        axes[1].set_ylabel("ms")
        axes[0].legend(fontsize=8, loc="lower left")
        axes[1].legend(fontsize=8, loc="upper left")
        for a in axes:
            a.grid(alpha=0.25)
            a.title.set_fontsize(10)
        out["distance"] = png(fig)

    # 3. map per target: track coloured by delivery
    mapped = [res for res in results if any(r["lat"] is not None for r in res["rows"])]
    if mapped and home:
        n = len(mapped)
        fig, axes = plt.subplots(1, n, figsize=(5.5 * n, 5.2), squeeze=False)
        k = 111320.0
        for i, res in enumerate(mapped):
            ax = axes[0][i]
            rs = [r for r in res["rows"] if r["lat"] is not None and (r["airborne"] is not False)]
            xs = lambda r: (r["lon"] - home[1]) * k * math.cos(math.radians(home[0])) / 1000
            ys = lambda r: (r["lat"] - home[0]) * k / 1000
            ok = [r for r in rs if r["delivered"]]
            bad = [r for r in rs if not r["delivered"]]
            ax.scatter([xs(r) for r in ok], [ys(r) for r in ok], s=3, color="#2e9e5b", label="delivered")
            ax.scatter([xs(r) for r in bad], [ys(r) for r in bad], s=9, color="#c0392b", label="lost")
            ax.plot([0], [0], "k^", ms=9, label="Cruza launch")
            qp = quad_positions.get(res["spec"]["quad"])
            if qp:
                ax.plot([(qp[1] - home[1]) * k * math.cos(math.radians(home[0])) / 1000],
                        [(qp[0] - home[0]) * k / 1000], "s", color="#9b51e0", ms=8, label=res["spec"]["quad"])
            ax.set_aspect("equal", adjustable="datalim")
            ax.set_title(res["name"])
            ax.set_xlabel("km east of launch")
            ax.set_ylabel("km north of launch")
            ax.grid(alpha=0.25)
            ax.legend(fontsize=8, loc="best")
        out["map"] = png(fig)

    # 4. bursts
    if any(res.get("bursts") for res in results):
        fig, ax = plt.subplots(figsize=(11, 3.4))
        for i, res in enumerate(results):
            bs = res.get("bursts") or []
            good = [b for b in bs if b["complete"] and b["kbps"]]
            bad = [b for b in bs if not b["complete"]]
            ax.scatter([clock(b["time"]) for b in good], [b["kbps"] for b in good], color=COLOURS[i % len(COLOURS)],
                       s=18, label=res["name"] + " complete")
            ax.scatter([clock(b["time"]) for b in bad], [0 for _ in bad], marker="x", color=COLOURS[i % len(COLOURS)],
                       s=30, label=res["name"] + " incomplete")
        ax.axhline(crit["burst_min_kbps"], color="#c0392b", lw=0.8, ls=":")
        ax.set_ylabel("kbit/s")
        ax.set_title("Data bursts: throughput of each burst (x at 0 = not fully delivered)")
        ax.grid(alpha=0.25)
        ax.legend(fontsize=8, ncol=2)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=tz))
        ax.set_xlabel("UTC time")
        out["bursts"] = png(fig)
    return out


# ---------------------------------------------------------------- output

def f(value, digits=0, unit=""):
    if value is None:
        return "&ndash;"
    if isinstance(value, float):
        return ("%.*f" % (digits, value)) + unit
    return html.escape(str(value)) + unit


def utc(t):
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC") if t else "&ndash;"


def write_csvs(out, results):
    for res in results:
        safe = res["name"].replace("/", "_")
        for key, rows in (("probes", res["rows"]), ("windows", res["windows"]), ("outages", res["outages"]),
                          ("bursts", res["bursts"]), ("distance_bins", res.get("bins") or [])):
            if not rows:
                continue
            with open(out / ("%s_%s.csv" % (safe, key)), "w", newline="") as handle:
                w = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)


def build_html(info, results, imgs, crit, sample):
    v_class = {"PASS": "pass", "FAIL": "fail", "INCONCLUSIVE": "inc"}
    parts = ["""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cruza Quad Link Test</title><style>
:root{--ink:#1d232b;--muted:#5d6874;--line:#d9dee4;--pass:#1f7a46;--fail:#b3261e;--inc:#8a5a00;--bg:#fff}
body{font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:var(--ink);background:var(--bg);margin:0}
main{max-width:1100px;margin:0 auto;padding:24px 16px 60px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:18px;margin:32px 0 8px;border-bottom:1px solid var(--line);padding-bottom:4px}
h3{font-size:15px;margin:20px 0 6px}.muted{color:var(--muted)}
.banner{background:#fff4d6;border:1px solid #e8c766;padding:10px 12px;border-radius:6px;margin:12px 0}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;margin:12px 0}
.card{border:1px solid var(--line);border-radius:8px;padding:12px}
.verdict{font-weight:700;font-size:20px}.pass{color:var(--pass)}.fail{color:var(--fail)}.inc{color:var(--inc)}
table{border-collapse:collapse;width:100%;margin:6px 0 10px;font-size:13px}
th,td{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}
th{background:#f4f6f8;font-weight:600}td.num{text-align:right;font-variant-numeric:tabular-nums}
img{max-width:100%;height:auto;border:1px solid var(--line);border-radius:6px;margin:6px 0}
.ok{color:var(--pass);font-weight:600}.no{color:var(--fail);font-weight:600}.na{color:var(--muted)}
ul{margin:4px 0 10px 20px;padding:0}
@media print{main{max-width:none}h2{break-after:avoid}img{break-inside:avoid}}
</style></head><body><main>"""]
    parts.append("<h1>Cruza &rarr; quad data-link test</h1>")
    parts.append('<div class="muted">Run %s &middot; report generated %s</div>' % (
        html.escape(info["run"]), utc(info["generated"])))
    if sample:
        parts.append('<div class="banner"><b>SAMPLE REPORT.</b> %s</div>' % html.escape(sample))
    parts.append("<h2>Result</h2><div class='cards'>")
    for res in results:
        m = res["metrics"]
        parts.append("<div class='card'><div class='muted'>%s &middot; %s</div><div class='verdict %s'>%s</div>"
                     "<div>%s delivered &middot; RTT p95 %s &middot; longest loss %s</div>"
                     "<div class='muted'>Max %s: %s; data still delivered at %s</div></div>" % (
                         html.escape(res["name"]), html.escape(res["spec"]["addr"]), v_class[res["verdict"]],
                         res["verdict"], f(m.get("uplink_pct"), 1, "%"), f(m.get("rtt_p95_ms"), 0, " ms"),
                         f(m.get("longest_outage_s"), 1, " s"), html.escape(m.get("distance_basis", "distance")),
                         f(m.get("max_distance_m") / 1000 if m.get("max_distance_m") is not None else None, 2, " km"),
                         f(m.get("max_distance_delivered_m") / 1000 if m.get("max_distance_delivered_m") is not None else None, 2, " km")))
    parts.append("</div>")
    parts.append("<p>A quad passes when every check below is met during the %s. "
                 "<b>Inconclusive</b> means nothing failed but the flight did not produce enough evidence "
                 "(too few packets, no flight log, or not flown far enough).</p>" % html.escape(
                     results[0]["scope_label"] if results else "test"))

    parts.append("<h2>Checks</h2>")
    for res in results:
        parts.append("<h3>%s</h3><table><tr><th>Check</th><th>Measured</th><th>Requirement</th><th>Result</th></tr>"
                     % html.escape(res["name"]))
        for c in res["checks"]:
            mark = "<span class='ok'>met</span>" if c["ok"] else ("<span class='no'>not met</span>"
                                                                  if c["ok"] is False else "<span class='na'>no data</span>")
            parts.append("<tr><td>%s</td><td class='num'>%s</td><td>%s%s</td><td>%s</td></tr>" % (
                html.escape(c["label"]), f(c["value"], 1, c["unit"]), html.escape(c["limit"]), c["unit"], mark))
        parts.append("</table>")
        for r in res["reasons"]:
            parts.append("<div class='inc'>&#9888; %s</div>" % html.escape(r))
        parts.append("<div class='muted'>Delivery judged from the %s. Range basis: %s. "
                     "Contiguous range meeting the %g%% window target: %s.</div>" % (
                         html.escape(res["delivered_source"]), html.escape(res["metrics"].get("distance_basis", "-")),
                         crit["window_min_pct"],
                         f(res["metrics"].get("contiguous_good_range_m") / 1000
                           if res["metrics"].get("contiguous_good_range_m") is not None else None, 2, " km")))

    parts.append("<h2>Timeline</h2><img alt='timeline' src='data:image/png;base64,%s'>" % imgs["timeline"])
    if "distance" in imgs:
        parts.append("<h2>Performance by distance</h2><img alt='distance' src='data:image/png;base64,%s'>" % imgs["distance"])
    if "map" in imgs:
        parts.append("<h2>Where packets were lost</h2><img alt='map' src='data:image/png;base64,%s'>" % imgs["map"])
    if "bursts" in imgs:
        parts.append("<h2>Bulk data</h2><p>Every %s s the Cruza sends a %s-byte burst, paced at up to %s kbit/s, "
                     "and the quad reports how much arrived.</p><img alt='bursts' src='data:image/png;base64,%s'>" % (
                         info["plan"]["burst"]["interval_s"], info["plan"]["burst"]["bytes"],
                         info["plan"]["burst"]["max_kbps"], imgs["bursts"]))

    parts.append("<h2>Losses longer than one second</h2>")
    any_out = False
    for res in results:
        long = [o for o in res["outages"] if o["duration_s"] >= 1]
        if not long:
            continue
        any_out = True
        parts.append("<h3>%s</h3><table><tr><th>Start</th><th>Duration</th><th>Probes lost</th><th>From launch</th>"
                     "<th>To quad</th><th>Height</th><th>Route</th><th>VPN path</th><th>LTE signal</th></tr>"
                     % html.escape(res["name"]))
        for o in sorted(long, key=lambda o: -o["duration_s"])[:40]:
            parts.append("<tr><td>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td>"
                         "<td class='num'>%s</td><td class='num'>%s</td><td>%s</td><td>%s</td><td class='num'>%s</td></tr>" % (
                             utc(o["start"])[11:19], f(o["duration_s"], 1, " s"), o["probes_lost"],
                             f(o["dist_home_m"], 0, " m"), f(o["dist_quad_m"], 0, " m"), f(o["alt_m"], 0, " m"),
                             f(o["dev"]), f(o["ts_path"]), f(o["lte_signal_pct"], 0, "%")))
        parts.append("</table>")
    if not any_out:
        parts.append("<p>None.</p>")

    parts.append("<h2>Test details</h2><table>")
    rows = [("Run ID", info["run"]), ("Sender (Cruza Pi)", info["sender_host"]),
            ("Session", "%s &rarr; %s" % (utc(info["start"]), utc(info["end"]))),
            ("Flight(s) from log", "; ".join("%s &rarr; %s" % (utc(a)[11:19], utc(b)[11:19]) for a, b in info["flights"])
             or "no flight log"),
            ("Cruza flight log", info["cruza_log"] or "not provided"),
            ("Probe stream", "%s per second, %s bytes each" % (info["plan"]["probe"]["rate_hz"],
                                                              info["plan"]["probe"]["size_bytes"])),
            ("Cruza clock synchronized", {True: "yes", False: "NO - time matching with the flight log may be off",
                                          None: "unknown"}[info["clock_sync"]]),
            ("Quad echo logs", ", ".join(info["echo_hosts"]) or "none collected"),
            ("End of session", info["end_reason"])]
    for k, v in rows:
        parts.append("<tr><th style='width:28%%'>%s</th><td>%s</td></tr>" % (k, v if "&" in str(v) else html.escape(str(v))))
    parts.append("</table><table><tr><th>Target</th><th>Probes judged</th><th>Replies back</th><th>Routes seen</th>"
                 "<th>VPN paths seen</th><th>Wi-Fi up</th><th>Quad clock offset</th><th>Send errors</th></tr>")
    for res in results:
        m = res["metrics"]
        parts.append("<tr><td>%s</td><td class='num'>%s</td><td class='num'>%s</td><td>%s</td><td>%s</td>"
                     "<td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td></tr>" % (
                         html.escape(res["name"]), m.get("probes"), f(m.get("reply_pct"), 1, "%"),
                         html.escape(", ".join(m.get("routes", [])) or "-"),
                         html.escape(", ".join(m.get("paths", [])) or "-"), f(m.get("time_on_wifi_pct"), 0, "%"),
                         f(m.get("clock_offset_s"), 2, " s"), m.get("send_errors")))
    parts.append("</table>")
    parts.append("""<h2>What this test does and does not show</h2><ul>
<li>It measures application data (UDP test packets) leaving the Cruza's companion Pi and arriving at each quad's Pi,
over whatever network path the Pis were using. "Delivered" is counted by the quad itself when its log is collected.</li>
<li>It does not send anything to either flight controller and is not a test of flight control over this path.</li>
<li>Round-trip time includes the quad's reply leg. Clock offsets between the Pis are estimated, not assumed zero.</li>
<li>"Route" is the Cruza Pi's outgoing interface (e.g. wwan0 = LTE, wlan0 = Wi-Fi, tailscale0 = VPN). "VPN path"
shows whether Tailscale reached the quad directly or through a DERP relay server.</li>
<li>If the Cruza's Wi-Fi was connected, some data may have used Wi-Fi rather than LTE; see the Wi-Fi column.</li>
</ul>""")
    parts.append("<p class='muted'>Data files: per-probe, per-window, outage, burst and distance tables are saved as "
                 "CSV next to this report, with summary.json.</p></main></body></html>")
    return "".join(parts)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--collected", required=True)
    ap.add_argument("--run")
    ap.add_argument("--plan")
    ap.add_argument("--cruza-log")
    ap.add_argument("--cruza-track")
    ap.add_argument("--quad-log", action="append", default=[], help="NAME=PATH")
    ap.add_argument("--out")
    ap.add_argument("--sample-note", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    sessions = find_sessions(args.collected)
    senders = [(d, m) for d, m in sessions if m.get("role") == "sender"]
    if args.run:
        senders = [(d, m) for d, m in senders if m.get("run") == args.run]
    if not senders:
        raise SystemExit("No sender session found under %s" % args.collected)
    sender_dir, meta = max(senders, key=lambda x: x[1]["w"])
    run_id = meta["run"]
    sender = load_sender(sender_dir, run_id)
    plan = json.loads(Path(args.plan).read_text()) if args.plan else meta["plan"]
    crit = dict(DEFAULT_CRITERIA)
    crit.update(plan.get("criteria") or {})
    period = 1.0 / float(plan["probe"]["rate_hz"])

    echo_by_target, echo_hosts = {}, []
    for d, m in sessions:
        if m.get("role") != "echo":
            continue
        emeta, got, span = load_echo(d, run_id)
        if got:
            echo_hosts.append("%s (%s)" % (emeta.get("name"), emeta.get("host")))
            for tgt in got:
                received, spans = echo_by_target.setdefault(tgt, ({}, []))
                received.update(got[tgt])
                spans.append(span[tgt])

    track, flights = [], []
    if args.cruza_log:
        track, flights = load_track_bin(args.cruza_log)
    elif args.cruza_track:
        track, flights = load_track_csv(args.cruza_track)
    cruza = Track(track) if track else None
    session_start = meta["w"]
    session_end = (sender["end"] or {}).get("w") or max(
        (tw for t in sender["tx"].values() for tw, _ in t.values()), default=session_start)
    overlapping = [(a, b) for a, b in flights if b > session_start and a < session_end]
    flights = [(max(a, session_start), min(b, session_end)) for a, b in overlapping]
    home = None
    if cruza:
        # Home is where the flight launched, even if the sender started after takeoff.
        t_home = overlapping[0][0] if overlapping else track[0][0]
        home = cruza.at(t_home) or track[0][1:4]

    quad_positions, quad_tracks = {}, {}
    for q in plan.get("quads", []):
        pos = q.get("position")
        if pos:
            quad_positions[q["name"]] = (pos["lat"], pos["lon"], pos.get("alt_m"))
    for item in args.quad_log:
        name, path = item.split("=", 1)
        qt, _ = load_track_bin(path)
        if qt:
            quad_tracks[name] = Track(qt)
            quad_positions.setdefault(name, qt[len(qt) // 2][1:4])

    results = []
    for spec in meta["targets"]:
        name = spec["name"]
        res = analyse_target(name, spec, sender, echo_by_target.get(name), cruza,
                             quad_positions.get(spec["quad"]), quad_tracks.get(spec["quad"]),
                             home, flights, crit, period)
        results.append(res)

    out = Path(args.out) if args.out else Path(args.collected) / "report"
    out.mkdir(parents=True, exist_ok=True)
    imgs = charts(results, cruza, flights, home, crit, quad_positions, session_start)
    info = {"run": run_id, "generated": dt.datetime.now(dt.timezone.utc).timestamp(), "plan": plan,
            "sender_host": meta.get("host"), "start": session_start, "end": session_end, "flights": flights,
            "cruza_log": args.cruza_log or args.cruza_track, "clock_sync": (meta.get("clock") or {}).get("ntp_synchronized"),
            "echo_hosts": echo_hosts, "end_reason": (sender["end"] or {}).get("reason", "no end record (power cut?)")}
    (out / "report.html").write_text(build_html(info, results, imgs, crit, args.sample_note), encoding="utf-8")
    write_csvs(out, results)
    summary = {"run": run_id, "criteria": crit, "flights": flights,
               "targets": {r["name"]: {"verdict": r["verdict"], "reasons": r["reasons"], "metrics": r["metrics"],
                                       "checks": r["checks"]} for r in results}}
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    plain = lambda v, d: "-" if v is None else "%.*f" % (d, v)
    for r in results:
        m = r["metrics"]
        print("%-20s %-12s delivered %s%%  rtt95 %s ms  longest loss %s s%s" % (
            r["name"], r["verdict"], plain(m.get("uplink_pct"), 1), plain(m.get("rtt_p95_ms"), 0),
            plain(m.get("longest_outage_s"), 1), "".join("\n    - " + x for x in r["reasons"])))
    print("Report: %s" % (out / "report.html"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
