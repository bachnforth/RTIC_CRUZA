#!/usr/bin/env python3
"""Cruza IMX500 combined video + observation service. One camera, one process.

The IMX500 is a single AI camera that must have its network firmware loaded to
stream, and only one process can own it. So this service does both jobs from one
picamera2 capture: it H264-encodes the main stream and fans it out over RTP to
every configured phone (plus an optional loopback mirror the dashboard taps), and
it reads the on-sensor inference metadata from the same frames to publish advisory
detection records to a loopback UDP port.

It replaces the separate cruza-video (rpicam-vid) and cruza-observe services. It
opens only the camera, a gstreamer subprocess and loopback/UDP sockets to the
configured Tailscale phones; it has no serial, MAVLink, route or modem access and
issues no flight command. Advisory only: records never move an aircraft.
"""
import argparse
import datetime as dt
import json
import re
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

CLASS_RE = re.compile(r"[A-Za-z0-9 _-]{1,40}")
PROFILES = {"economy": (640, 480, 15, 300000), "standard": (640, 480, 15, 400000),
            "detail": (960, 540, 15, 500000)}


def tail_ip(value):
    import ipaddress
    addr = ipaddress.ip_address(value)
    if addr not in ipaddress.ip_network("100.64.0.0/10"):
        raise ValueError("Endpoint must be an explicit Tailscale IPv4 address")
    return str(addr)


def load_config(path):
    c = json.loads(Path(path).read_text())
    if c["video_profile"] not in PROFILES:
        raise ValueError("Unknown video profile")
    if not isinstance(c["video_port"], int) or not 1024 <= c["video_port"] <= 65535:
        raise ValueError("Invalid video_port")
    mirror = c.get("video_mirror_port", 0)
    if type(mirror) is not int or (mirror != 0 and not 15600 <= mirror <= 15609):
        raise ValueError("Video mirror must be 0 or a loopback port 15600..15609")
    dests = [tail_ip(c["android_ip"])] if c.get("android_ip") else []
    extra = c.get("android_ip2") or []
    for e in ([extra] if isinstance(extra, str) else extra):
        if e:
            dests.append(tail_ip(e))
    if not dests:
        raise ValueError("No phone destinations: set android_ip (and android_ip2)")
    o = c.get("observe", {})
    model = o.get("model", "/usr/share/imx500-models/"
                  "imx500_network_ssd_mobilenetv2_fpnlite_320x320_pp.rpk")
    if not re.fullmatch(r"[\w./-]+\.rpk", model):
        raise ValueError("Invalid observe.model path")
    port = o.get("loopback_port", 15620)
    if not isinstance(port, int) or not 15620 <= port <= 15629:
        raise ValueError("observe.loopback_port must be 15620..15629")
    min_score = float(o.get("min_score", 0.55))
    max_rate = float(o.get("max_rate_hz", 5))
    repeat = float(o.get("repeat_seconds", 3.0))
    hfov = float(o.get("hfov_deg", 66.0))
    vfov = float(o.get("vfov_deg", 49.0))
    classes = {x.lower() for x in o.get("classes", []) if isinstance(x, str)}
    return dict(profile=c["video_profile"], video_port=c["video_port"], mirror=mirror,
                dests=dests, model=model, port=port, min_score=min_score,
                max_rate=max_rate, repeat=repeat, hfov=hfov, vfov=vfov, classes=classes)


def emit_log(event, **fields):
    print(json.dumps({"time": dt.datetime.now(dt.timezone.utc).isoformat(),
                      "event": event, **fields}), file=sys.stderr, flush=True)


class Publisher:
    def __init__(self, port):
        self.addr = ("127.0.0.1", port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.seq = 0

    def send(self, cls, score, cx, cy, bbox, hfov, vfov):
        az = (cx - 0.5) * hfov
        el = (0.5 - cy) * vfov
        self.seq += 1
        # "fov" lets a calibration run know what produced these angles; see
        # the same field in observe.py.
        record = {"t": round(time.time(), 2), "seq": self.seq, "cls": cls,
                  "score": round(float(score), 3), "az_rel_deg": round(az, 2),
                  "el_rel_deg": round(el, 2),
                  "fov": [round(float(hfov), 2), round(float(vfov), 2)],
                  "bbox": [round(float(v), 4) for v in bbox]}
        data = json.dumps(record, allow_nan=False).encode()
        if len(data) <= 512:
            try:
                self.sock.sendto(data, self.addr)
            except OSError:
                pass


def clamp01(v):
    return 0.0 if v < 0 else 1.0 if v > 1 else float(v)


def detections(np_outputs, intr):
    try:
        boxes, scores, classes = np_outputs[0][0], np_outputs[1][0], np_outputs[2][0]
    except (IndexError, TypeError):
        return
    order = getattr(intr, "bbox_order", "yx") or "yx"
    for box, score, cls in zip(boxes, scores, classes):
        if len(box) != 4:
            continue
        x0, y0, x1, y1 = (box if order == "xy" else (box[1], box[0], box[3], box[2]))
        x0, y0, x1, y1 = clamp01(x0), clamp01(y0), clamp01(x1), clamp01(y1)
        if x1 < x0:
            x0, x1 = x1, x0
        if y1 < y0:
            y0, y1 = y1, y0
        yield int(cls), float(score), [x0, y0, x1 - x0, y1 - y0]


def gst_pipeline(clients):
    return ["gst-launch-1.0", "-q", "fdsrc", "!", "h264parse", "!", "rtph264pay",
            "pt=96", "config-interval=1", "mtu=1200", "!", "multiudpsink",
            f"clients={clients}", "sync=false", "async=false", "qos-dscp=8"]


def run(cfg):
    from picamera2 import Picamera2
    from picamera2.encoders import H264Encoder
    from picamera2.outputs import FileOutput
    from picamera2.devices import IMX500
    from picamera2.devices.imx500 import NetworkIntrinsics

    if not Path(cfg["model"]).exists():
        raise RuntimeError(f"IMX500 model not found: {cfg['model']}")
    imx500 = IMX500(cfg["model"])
    intr = imx500.network_intrinsics or NetworkIntrinsics()
    if not getattr(intr, "task", None):
        intr.task = "object detection"
    intr.update_with_defaults()
    labels = [l for l in (getattr(intr, "labels", None) or []) if l and l != "-"]

    picam2 = Picamera2(imx500.camera_num)
    w, h, fps, bitrate = PROFILES[cfg["profile"]]
    # Mirror the detector's working preview configuration (the IMX500 frontend
    # times out on a plain video configuration); YUV420 feeds the H264 encoder.
    config = picam2.create_preview_configuration(
        main={"size": (w, h), "format": "YUV420"},
        controls={"FrameRate": fps}, buffer_count=6)
    imx500.show_network_fw_progress_bar()

    clients = ",".join(f"{d}:{cfg['video_port']}" for d in cfg["dests"])
    if cfg["mirror"]:
        clients += f",127.0.0.1:{cfg['mirror']}"
    gst = subprocess.Popen(gst_pipeline(clients), stdin=subprocess.PIPE)

    encoder = H264Encoder(bitrate=bitrate)
    try:
        encoder.repeat = True          # repeat SPS/PPS so late viewers can decode
        encoder.iperiod = fps          # one keyframe per second
    except Exception:  # noqa: BLE001 - older encoders lack these knobs
        pass

    picam2.start_recording(encoder, FileOutput(gst.stdin), config)
    emit_log("stream_start", profile=cfg["profile"], bitrate=bitrate,
             dests=cfg["dests"], video_port=cfg["video_port"], port=cfg["port"],
             classes=sorted(cfg["classes"]) or "all")

    pub = Publisher(cfg["port"])
    running = {"on": True}
    signal.signal(signal.SIGTERM, lambda *_: running.update(on=False))
    signal.signal(signal.SIGINT, lambda *_: running.update(on=False))

    min_interval = 1.0 / cfg["max_rate"]
    last_emit = 0.0
    last_seen = {}
    try:
        while running["on"]:
            metadata = picam2.capture_metadata()
            if gst.poll() is not None:
                raise RuntimeError("gstreamer RTP pipeline exited")
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
                m = CLASS_RE.match(name) if name else None
                name = m.group(0) if m else None
                if not name:
                    continue
                if cfg["classes"] and name.lower() not in cfg["classes"]:
                    continue
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
            picam2.stop_recording()
        except Exception:  # noqa: BLE001
            pass
        try:
            gst.stdin.close()
            gst.terminate()
            gst.wait(timeout=5)
        except Exception:  # noqa: BLE001
            gst.kill()
        emit_log("stream_stop")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="/etc/cruza/config.json")
    args = parser.parse_args()
    run(load_config(args.config))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError) as error:
        emit_log("stream_error", detail=str(error))
        sys.exit(1)
