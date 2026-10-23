#!/usr/bin/env python3
"""Cruza IMX500 observation detector. No FC, MAVLink, routing or modem access.

Runs on-sensor object detection on the IMX500 AI camera and emits bounded JSON
observation records to a loopback UDP port. It reads the camera only; it never
opens a serial device, a MAVLink socket, a route or the modem, and it issues no
flight command. Each record is advisory: it says "something worth a human look
is in view", with the pixel position expressed as angles off the camera
boresight. Geolocation and operator validation happen later, on the laptop
dashboard, by joining these angles with the Cruza's own telemetry. Nothing here
moves an aircraft.

The loopback consumer is companion/observe-tap.py (deployed to
/opt/cruza-observe-tap.py), started by the laptop dashboard over SSH, exactly
like the video and telemetry observers. Records are newline-free JSON, one per
UDP datagram, kept small (< 512 bytes).

Angles use the camera boresight as origin: az_rel_deg is positive to the right,
el_rel_deg is positive up. They are small-angle estimates from the detection box
centre and the configured camera field of view; they are cueing hints, not a
calibrated sensor line. Validate the field-of-view values against the lens
before trusting the bearings.
"""
import argparse
import datetime as dt
import json
import math
import os
import re
import signal
import socket
import sys
import time
from pathlib import Path

# A short, safe allowlist for the class-name characters we are willing to emit.
CLASS_RE = re.compile(r"[A-Za-z0-9 _-]{1,40}")


def load_config(path):
    c = json.loads(Path(path).read_text())
    o = c.get("observe", {})
    model = o.get("model", "/usr/share/imx500-models/"
                  "imx500_network_ssd_mobilenetv2_fpnlite_320x320_pp.rpk")
    if not re.fullmatch(r"[\w./-]+\.rpk", model):
        raise ValueError("Invalid observe.model path")
    port = o.get("loopback_port", 15620)
    if not isinstance(port, int) or not 15620 <= port <= 15629:
        raise ValueError("observe.loopback_port must be an int 15620..15629")
    min_score = o.get("min_score", 0.55)
    if not isinstance(min_score, (int, float)) or not 0.05 <= min_score <= 0.99:
        raise ValueError("observe.min_score must be 0.05..0.99")
    max_rate = o.get("max_rate_hz", 5)
    if not isinstance(max_rate, (int, float)) or not 0.2 <= max_rate <= 30:
        raise ValueError("observe.max_rate_hz must be 0.2..30")
    repeat = o.get("repeat_seconds", 3.0)
    if not isinstance(repeat, (int, float)) or not 0.5 <= repeat <= 60:
        raise ValueError("observe.repeat_seconds must be 0.5..60")
    hfov = o.get("hfov_deg", 66.0)
    vfov = o.get("vfov_deg", 49.0)
    for name, value in (("hfov_deg", hfov), ("vfov_deg", vfov)):
        if not isinstance(value, (int, float)) or not 10 <= value <= 160:
            raise ValueError(f"observe.{name} must be 10..160 degrees")
    classes = o.get("classes", [])
    if not isinstance(classes, list) or any(not isinstance(x, str) for x in classes):
        raise ValueError("observe.classes must be a list of class names")
    classes = {x.lower() for x in classes}
    return dict(model=model, port=port, min_score=float(min_score),
                max_rate=float(max_rate), repeat=float(repeat),
                hfov=float(hfov), vfov=float(vfov), classes=classes)


def emit_log(event, **fields):
    """Structured line to stderr/journal. Never mixed with the UDP record feed."""
    print(json.dumps({"time": dt.datetime.now(dt.timezone.utc).isoformat(),
                      "event": event, **fields}), file=sys.stderr, flush=True)


class Publisher:
    """Sends one compact JSON record per detection to the loopback port."""

    def __init__(self, port):
        self.addr = ("127.0.0.1", port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.seq = 0

    def send(self, cls, score, cx, cy, bbox, hfov, vfov):
        # Box centre -> angles off boresight. Small-angle planar estimate; good
        # enough to cue a look, not a survey instrument.
        az = (cx - 0.5) * hfov
        el = (0.5 - cy) * vfov
        self.seq += 1
        record = {"t": round(time.time(), 2), "seq": self.seq,
                  "cls": cls, "score": round(float(score), 3),
                  "az_rel_deg": round(az, 2), "el_rel_deg": round(el, 2),
                  "bbox": [round(float(v), 4) for v in bbox]}
        data = json.dumps(record, allow_nan=False).encode()
        if len(data) > 512:
            return
        try:
            self.sock.sendto(data, self.addr)
        except OSError:
            pass


def clamp01(v):
    return 0.0 if v < 0 else 1.0 if v > 1 else float(v)


def detections(np_outputs, intr):
    """Yield (class_index, score, [x, y, w, h]) from a post-processed SSD head.

    Boxes arrive normalised in input-tensor space. Honour the intrinsics'
    declared box order; default to the fpnlite SSD layout [y0, x0, y1, x1].
    Unexpected shapes yield nothing rather than raising, so one odd frame cannot
    stop the service.
    """
    try:
        boxes, scores, classes = np_outputs[0][0], np_outputs[1][0], np_outputs[2][0]
    except (IndexError, TypeError):
        return
    order = getattr(intr, "bbox_order", "yx") or "yx"
    for box, score, cls in zip(boxes, scores, classes):
        if len(box) != 4:
            continue
        if order == "xy":
            x0, y0, x1, y1 = box
        else:
            y0, x0, y1, x1 = box
        x0, y0, x1, y1 = clamp01(x0), clamp01(y0), clamp01(x1), clamp01(y1)
        if x1 < x0:
            x0, x1 = x1, x0
        if y1 < y0:
            y0, y1 = y1, y0
        yield int(cls), float(score), [x0, y0, x1 - x0, y1 - y0]


def run(cfg):
    # Imported here so --synthetic works on a laptop with no camera stack.
    from picamera2 import Picamera2
    from picamera2.devices import IMX500
    from picamera2.devices.imx500 import NetworkIntrinsics

    if not Path(cfg["model"]).exists():
        raise RuntimeError(f"IMX500 model not found: {cfg['model']}. Install the "
                           "imx500-all firmware package and confirm the path.")
    imx500 = IMX500(cfg["model"])
    intr = imx500.network_intrinsics or NetworkIntrinsics()
    if not getattr(intr, "task", None):
        intr.task = "object detection"
    intr.update_with_defaults()
    labels = [l for l in (getattr(intr, "labels", None) or []) if l and l != "-"]

    picam2 = Picamera2(imx500.camera_num)
    rate = getattr(intr, "inference_rate", None) or 10
    config = picam2.create_preview_configuration(
        controls={"FrameRate": rate}, buffer_count=12)
    imx500.show_network_fw_progress_bar()
    picam2.start(config, show_preview=False)
    emit_log("observe_start", model=cfg["model"], port=cfg["port"],
             min_score=cfg["min_score"], classes=sorted(cfg["classes"]) or "all",
             labels=len(labels))

    pub = Publisher(cfg["port"])
    running = {"on": True}
    signal.signal(signal.SIGTERM, lambda *_: running.update(on=False))
    signal.signal(signal.SIGINT, lambda *_: running.update(on=False))

    min_interval = 1.0 / cfg["max_rate"]
    last_emit = 0.0
    last_seen = {}  # class name -> monotonic time last published (debounce)
    try:
        while running["on"]:
            metadata = picam2.capture_metadata()
            np_outputs = imx500.get_outputs(metadata, add_batch=True)
            if np_outputs is None:
                continue
            now = time.monotonic()
            if now - last_emit < min_interval:
                continue
            best = None
            for cls_idx, score, bbox in detections(np_outputs, intr):
                if score < cfg["min_score"]:
                    continue
                name = labels[cls_idx] if 0 <= cls_idx < len(labels) else str(cls_idx)
                name = (CLASS_RE.match(name) or [None])[0] if CLASS_RE.match(name) else None
                if not name:
                    continue
                if cfg["classes"] and name.lower() not in cfg["classes"]:
                    continue
                # One record per frame: the strongest in-scope detection. A
                # persistent object repeats only every repeat_seconds.
                if best is None or score > best[1]:
                    best = (name, score, bbox)
            if best is None:
                continue
            name, score, bbox = best
            if now - last_seen.get(name, 0) < cfg["repeat"]:
                continue
            last_seen[name] = now
            last_emit = now
            cx, cy = bbox[0] + bbox[2] / 2, bbox[1] + bbox[3] / 2
            pub.send(name, score, cx, cy, bbox, cfg["hfov"], cfg["vfov"])
    finally:
        try:
            picam2.stop()
        except Exception:  # noqa: BLE001 - best-effort shutdown
            pass
        emit_log("observe_stop")


def synthetic(cfg, count):
    """Emit canned records to the loopback port with no camera, for bench tests
    of the laptop dashboard chain. Clearly marked; never a live detection."""
    pub = Publisher(cfg["port"])
    samples = [("person", 0.82, 0.30, 0.62), ("car", 0.74, 0.70, 0.55),
               ("boat", 0.66, 0.50, 0.58), ("truck", 0.71, 0.18, 0.60)]
    emit_log("observe_synthetic_start", port=cfg["port"], count=count)
    for i in range(count):
        name, score, cx, cy = samples[i % len(samples)]
        bbox = [clamp01(cx - 0.06), clamp01(cy - 0.08), 0.12, 0.16]
        pub.send(name, score, cx, cy, bbox, cfg["hfov"], cfg["vfov"])
        time.sleep(max(0.1, 1.0 / cfg["max_rate"]))
    emit_log("observe_synthetic_done")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="/etc/cruza/config.json")
    parser.add_argument("--synthetic", type=int, default=0, metavar="N",
                        help="emit N canned records (no camera) for bench tests")
    args = parser.parse_args()
    cfg = load_config(args.config)
    if args.synthetic:
        synthetic(cfg, args.synthetic)
    else:
        run(cfg)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError) as error:
        emit_log("observe_error", detail=str(error))
        sys.exit(1)
