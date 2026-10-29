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
import base64
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
    # Optional image chips for the dashboard's handover review (off by default).
    chips = o.get("chips", False)
    if not isinstance(chips, bool):
        raise ValueError("observe.chips must be true or false")
    chip_seconds = o.get("chip_seconds", 10.0)
    if isinstance(chip_seconds, bool) or not isinstance(chip_seconds, (int, float)) \
            or not 2 <= chip_seconds <= 600:
        raise ValueError("observe.chip_seconds must be 2..600")
    return dict(profile=c["video_profile"], video_port=c["video_port"], mirror=mirror,
                dests=dests, model=model, port=port, min_score=min_score,
                max_rate=max_rate, repeat=repeat, hfov=hfov, vfov=vfov, classes=classes,
                chips=chips, chip_seconds=float(chip_seconds))


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
        return self.seq

    def send_chip(self, seq, jpeg):
        """Send one JPEG as numbered parts naming detection `seq`, each its own
        datagram under the tap's 512-byte cap:
        {"t": .., "chip": seq, "part": i, "parts": n, "jpg": "<base64>"}"""
        text = base64.b64encode(jpeg).decode()
        chunks = [text[i:i + CHIP_PART_CHARS] for i in range(0, len(text), CHIP_PART_CHARS)]
        if len(chunks) > CHIP_MAX_PARTS:
            return False
        t = round(time.time(), 2)
        for i, chunk in enumerate(chunks):
            data = json.dumps({"t": t, "chip": seq, "part": i, "parts": len(chunks),
                               "jpg": chunk}).encode()
            try:
                self.sock.sendto(data, self.addr)
            except OSError:
                return False
            time.sleep(0.003)  # stay well inside the tap's 32 KB receive buffer
        return True


# Image chip limits; the laptop discards anything outside them.
CHIP_PART_CHARS = 400      # base64 characters per part (multiple of 4)
CHIP_MAX_PARTS = 64        # so at most 19200 bytes of JPEG
CHIP_TARGET = 240          # longest side of the chip, pixels
CHIP_QUALITY = 70


def clamp01(v):
    return 0.0 if v < 0 else 1.0 if v > 1 else float(v)


def chip_jpeg(frame, size, bbox, margin=0.5):
    """JPEG of the box (normalised x, y, w, h) plus a margin, cut from a main
    stream frame: 4-channel XBGR8888 ([R, G, B, X] per pixel), 3-channel, or
    YUV420 of `size` (w, h). Returns bytes or None. A picture for the operator,
    not a measurement; the box is in the network's input space, and the margin
    covers the small offset from the main stream's framing."""
    import numpy as np
    import simplejpeg  # picamera2 dependency
    x, y, bw, bh = bbox
    cx, cy = x + bw / 2, y + bh / 2
    half_w = max(bw * (1 + margin), 0.15) / 2
    half_h = max(bh * (1 + margin), 0.15) / 2
    if frame.ndim == 3:
        h, w, channels = frame.shape
        x0, x1 = int(clamp01(cx - half_w) * w), int(clamp01(cx + half_w) * w)
        y0, y1 = int(clamp01(cy - half_h) * h), int(clamp01(cy + half_h) * h)
        if x1 - x0 < 8 or y1 - y0 < 8:
            return None
        step = max(1, -(-max(x1 - x0, y1 - y0) // CHIP_TARGET))
        crop = np.ascontiguousarray(frame[y0:y1:step, x0:x1:step])
        colorspace = {4: "RGBX", 3: "RGB"}.get(channels)
        if colorspace is None:
            return None
        for quality in (CHIP_QUALITY, 50, 35):
            jpeg = simplejpeg.encode_jpeg(crop, quality=quality, colorspace=colorspace)
            if len(base64.b64encode(jpeg)) <= CHIP_PART_CHARS * CHIP_MAX_PARTS:
                return jpeg
        return None
    w, h = size
    stride = frame.shape[1]
    y_plane = frame[:h, :w]
    uv = frame[h:h + h // 2].reshape(-1)
    u_plane = uv[:(h // 2) * (stride // 2)].reshape(h // 2, stride // 2)[:, :w // 2]
    v_plane = uv[(h // 2) * (stride // 2):].reshape(h // 2, stride // 2)[:, :w // 2]
    x0, x1 = int(clamp01(cx - half_w) * w) // 2, int(clamp01(cx + half_w) * w) // 2
    y0, y1 = int(clamp01(cy - half_h) * h) // 2, int(clamp01(cy + half_h) * h) // 2
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    # Work in chroma (half-resolution) units so the planes stay 2:1.
    step = max(1, -(-max(x1 - x0, y1 - y0) * 2 // CHIP_TARGET))
    for quality in (CHIP_QUALITY, 50, 35):
        u = np.ascontiguousarray(u_plane[y0:y1:step, x0:x1:step])
        v = np.ascontiguousarray(v_plane[y0:y1:step, x0:x1:step])
        ys = y_plane[2 * y0:2 * y1, 2 * x0:2 * x1][::step, ::step]
        ys = np.ascontiguousarray(ys[:2 * u.shape[0], :2 * u.shape[1]])
        jpeg = simplejpeg.encode_jpeg_yuv_planes(ys, u, v, quality=quality)
        if len(base64.b64encode(jpeg)) <= CHIP_PART_CHARS * CHIP_MAX_PARTS:
            return jpeg
    return None


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

    # The third positional argument of start_recording is pts, not the camera
    # configuration, so this config is ignored and the camera runs its own
    # default (1280x720 XBGR8888 on the Cruza, seen in chip_error logs).
    # config=config would honour the profile size and give the encoder much less
    # to do, but the measured hfov_deg/vfov_deg describe the stream as it runs
    # today: re-measure the field of view before changing this.
    picam2.start_recording(encoder, FileOutput(gst.stdin), config)
    emit_log("stream_start", profile=cfg["profile"], bitrate=bitrate,
             dests=cfg["dests"], video_port=cfg["video_port"], port=cfg["port"],
             classes=sorted(cfg["classes"]) or "all", chips=cfg["chips"])

    pub = Publisher(cfg["port"])
    running = {"on": True}
    signal.signal(signal.SIGTERM, lambda *_: running.update(on=False))
    signal.signal(signal.SIGINT, lambda *_: running.update(on=False))

    min_interval = 1.0 / cfg["max_rate"]
    last_emit = 0.0
    last_seen = {}
    last_chip = {}  # class name -> monotonic time of its last image chip
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
            seq = pub.send(name, score, cx, cy, bbox, cfg["hfov"], cfg["vfov"])
            if cfg["chips"] and now - last_chip.get(name, -1e9) >= cfg["chip_seconds"]:
                # The next frame, not the one inference ran on (~1 frame later);
                # fine for a picture for the operator.
                frame = None
                try:
                    # The box is in the network's (whole-sensor) space; map it
                    # into the main stream, which is a 16:9 cut of the sensor.
                    main_size = picam2.camera_configuration()["main"]["size"]
                    try:
                        bx, by, bw_, bh_ = bbox
                        px, py, pw, ph = imx500.convert_inference_coords(
                            (by, bx, by + bh_, bx + bw_), metadata, picam2)
                        mw, mh = main_size
                        chip_box = [px / mw, py / mh, pw / mw, ph / mh]
                    except Exception:  # noqa: BLE001 - fall back to the raw box
                        chip_box = bbox
                    frame = picam2.capture_array("main")
                    # The configured size is not always what the camera gives
                    # (see stream.py's start_recording note), so ask the camera.
                    jpeg = chip_jpeg(frame, main_size, chip_box)
                except Exception as error:  # noqa: BLE001 - a picture must never stop video or detection
                    emit_log("chip_error", detail=str(error)[:200],
                             shape=list(getattr(frame, "shape", [])),
                             main=str(picam2.camera_configuration().get("main"))[:300])
                    jpeg = None
                if jpeg and pub.send_chip(seq, jpeg):
                    last_chip[name] = now
                    emit_log("chip_sent", cls=name, seq=seq, bytes=len(jpeg))
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
