"""Tests for the link test. Run from the repo root:  python linktest/test_linktest.py

The end-to-end test runs a real sender and two real echoes on this computer's
loopback addresses for about 20 seconds, with 10% simulated loss on one quad,
then builds a report from their logs and a made-up GPS track.
"""
import csv
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import linktest  # noqa: E402
import report    # noqa: E402


class Bitmap(unittest.TestCase):
    def test_in_order_out_of_order_and_duplicates(self):
        p = linktest.Peer()
        for seq in (1, 2, 3, 5):
            self.assertTrue(p.record(seq))
        self.assertEqual((p.got, p.hi), (4, 5))
        self.assertEqual(p.mask & 0b11111, 0b11101)   # bit0 = seq5, bit1 = seq4 missing
        self.assertTrue(p.record(4))                   # late arrival fills the hole
        self.assertFalse(p.record(4))                  # duplicate not counted
        self.assertEqual(p.got, 5)
        self.assertTrue(p.record(200))                 # big jump resets the window
        self.assertEqual(p.mask, 1)

    def test_sender_marks_from_bitmap(self):
        t = linktest.Target({"name": "q/vpn", "addr": "127.0.0.1", "port": 1}, "run")
        for _ in range(10):
            t.tx_mono.append(0.0)
            t.confirmed.append(0)
        t.mark(10, 0b1011)          # 10, 9 and 7 received
        self.assertEqual([i + 1 for i, v in enumerate(t.confirmed) if v], [7, 9, 10])
        pct, judged = t.uplink(100.0)
        self.assertEqual((round(pct), judged), (30, 10))


class TailscalePaths(unittest.TestCase):
    def test_specific_gateway_route_takes_precedence(self):
        status = {"Peer": {
            "a": {"HostName": "alien03", "PrimaryRoutes": ["10.223.0.0/16"]},
            "b": {"HostName": "alien08", "PrimaryRoutes": ["10.223.79.20/32"]}}}
        result = linktest.tailscale_paths(json.dumps(status), ["10.223.79.20"])
        self.assertEqual(result["10.223.79.20"]["peer"], "alien08")

    def test_direct_relay_and_subnet_router(self):
        status = {"Peer": {
            "a": {"HostName": "quadpi", "TailscaleIPs": ["100.100.0.10"], "CurAddr": "1.2.3.4:41641",
                  "Relay": "dfw", "Online": True},
            "b": {"HostName": "tfwdrone", "TailscaleIPs": ["100.100.0.6"], "CurAddr": "", "Relay": "ord",
                  "Online": True},
            "c": {"HostName": "alien03", "TailscaleIPs": ["100.100.0.29"], "PrimaryRoutes": ["10.223.0.0/16"],
                  "CurAddr": "", "Relay": "dfw"}}}
        out = linktest.tailscale_paths(json.dumps(status), ["100.100.0.10", "100.100.0.6", "10.223.79.20", "8.8.8.8"])
        self.assertEqual(out["100.100.0.10"]["path"], "direct")
        self.assertEqual(out["100.100.0.6"]["path"], "derp:ord")
        self.assertEqual(out["10.223.79.20"]["peer"], "alien03")
        self.assertEqual(out["10.223.79.20"]["via"], "subnet-router")
        self.assertIsNone(out["8.8.8.8"]["peer"])


class PlanChecks(unittest.TestCase):
    def test_shipped_plan_is_valid_and_mesh_paths_are_enabled(self):
        plan = linktest.load_plan(HERE / "plan.json")
        names = [t["name"] for t in linktest.targets_from_plan(plan)]
        self.assertEqual(names, ["quadpi/vpn", "quadpi/mesh", "tfwdrone/vpn", "tfwdrone/mesh"])
        self.assertEqual([t["name"] for t in linktest.targets_from_plan(plan, ["quadpi"])], ["quadpi/vpn", "quadpi/mesh"])

    def test_rejects_unsafe_rates(self):
        plan = json.loads((HERE / "plan.json").read_text())
        plan["probe"]["rate_hz"] = 500
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(plan, f)
        with self.assertRaises(ValueError):
            linktest.load_plan(f.name)
        os.unlink(f.name)


class EndToEnd(unittest.TestCase):
    """Real processes on loopback; simulated 10% loss at quad A only."""

    def test_send_echo_and_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            plan = {"port": 15797, "duration_s": 20, "cruza": {"tailnet_ip": "127.0.0.1"},
                    "probe": {"rate_hz": 10, "size_bytes": 200},
                    "burst": {"interval_s": 6, "bytes": 10000, "chunk_bytes": 1000, "max_kbps": 400},
                    "quads": [{"name": "quadA", "bind": ["127.0.0.1"], "position": {"lat": 33.7236, "lon": -85.9071},
                               "paths": [{"label": "vpn", "addr": "127.0.0.1"}]},
                              {"name": "quadB", "bind": ["127.0.0.2"],
                               "paths": [{"label": "vpn", "addr": "127.0.0.2"}]}],
                    "criteria": {"min_probes": 50, "min_distance_m": 500}}
            (tmp / "plan.json").write_text(json.dumps(plan))
            py = [sys.executable, str(HERE / "linktest.py")]
            env = dict(os.environ)
            procs = []
            for name, loss in (("quadA", "0.1"), ("quadB", "0")):
                e = dict(env, LINKTEST_LOG_ROOT=str(tmp / name), LINKTEST_SIMULATE_LOSS=loss)
                procs.append(subprocess.Popen(py + ["echo", "--plan", str(tmp / "plan.json"), "--name", name],
                                              env=e, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            time.sleep(1)
            start = time.time()
            send = subprocess.run(py + ["send", "--plan", str(tmp / "plan.json")],
                                  env=dict(env, LINKTEST_LOG_ROOT=str(tmp / "cruza")),
                                  capture_output=True, text=True, timeout=60)
            self.assertEqual(send.returncode, 0, send.stderr)
            for name, p in zip(("quadA", "quadB"), procs):
                subprocess.run(py + ["stop", "--role", "echo"], env=dict(env, LINKTEST_LOG_ROOT=str(tmp / name)),
                               capture_output=True, timeout=15)
                p.wait(timeout=10)

            # A straight 2 km outbound leg over the test period, armed throughout.
            with open(tmp / "track.csv", "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["time_utc", "lat", "lon", "alt_m"])
                for i in range(0, 260):
                    t = start - 3 + i * 0.1
                    w.writerow([t, 33.7236 + (i / 259) * 2000 / 111320, -85.9071, 290])

            out = tmp / "report"
            code = report.main(["--collected", str(tmp), "--cruza-track", str(tmp / "track.csv"),
                                "--out", str(out)])
            self.assertEqual(code, 0)
            summary = json.loads((out / "summary.json").read_text())
            a = summary["targets"]["quadA/vpn"]
            b = summary["targets"]["quadB/vpn"]
            # quadB: clean link
            self.assertGreater(b["metrics"]["uplink_pct"], 99)
            self.assertEqual(b["verdict"], "PASS")
            # quadA: ~10% loss each way -> fails the 98% delivery check
            self.assertTrue(80 < a["metrics"]["uplink_pct"] < 97, a["metrics"]["uplink_pct"])
            self.assertEqual(a["verdict"], "FAIL")
            # range: the track reached ~2 km from launch / quad A
            self.assertGreater(a["metrics"]["max_distance_m"], 1500)
            self.assertIn("distance to the quad", a["metrics"]["distance_basis"])
            self.assertTrue((out / "report.html").stat().st_size > 50_000)
            self.assertTrue((out / "quadA_vpn_probes.csv").exists())

            # The quad's log, not the replies, decides delivery: replies were lost too.
            sender_dir = next((tmp / "cruza").glob("*_sender_*"))
            replies = sum(1 for line in next(sender_dir.glob("events-*.jsonl")).read_text().splitlines()
                          if '"k":"rx"' in line and "quadA" in line)
            echo_dir = next((tmp / "quadA").glob("*_echo_*"))
            received = sum(1 for line in next(echo_dir.glob("events-*.jsonl")).read_text().splitlines()
                           if '"k":"rx"' in line and '"run":"20' in line and "preflight" not in line)
            self.assertLess(replies, received)


class Geometry(unittest.TestCase):
    def test_session_metadata_after_low_disk_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "session"
            folder.mkdir()
            meta = {"k": "meta", "role": "sender", "run": "test"}
            (folder / "events-0001.jsonl").write_text(
                json.dumps({"k": "note", "low_disk": True}) + "\n" + json.dumps(meta) + "\n")
            self.assertEqual(report.find_sessions(tmp), [(folder, meta)])

    def test_metres(self):
        self.assertAlmostEqual(report.metres(33.0, -86.0, 33.01, -86.0), 1111.95, delta=1)

    def test_track_interpolation_and_gap(self):
        tr = report.Track([(0, 33.0, -86.0, 100, 0), (1, 33.001, -86.0, 110, 0), (100, 34.0, -86.0, 0, 0)])
        lat, lon, alt = tr.at(0.5)
        self.assertAlmostEqual(lat, 33.0005)
        self.assertAlmostEqual(alt, 105)
        self.assertIsNone(tr.at(50))          # inside a logging gap
        self.assertIsNotNone(tr.at(99.5))     # within a second of a sample


if __name__ == "__main__":
    unittest.main()
