#!/usr/bin/env python3
"""Cruza companion operations. No flight commands or parameter writes."""
import argparse
import datetime as dt
import ipaddress
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

PROFILES = {"economy": (640, 480, 15, 300000), "standard": (640, 480, 15, 400000),
            "detail": (960, 540, 15, 500000)}


def run(args, timeout=15):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return {"code": p.returncode, "stdout": p.stdout.strip(), "stderr": p.stderr.strip()}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"code": -1, "stdout": "", "stderr": str(e)}


def emit(event, **fields):
    print(json.dumps({"time": dt.datetime.now(dt.timezone.utc).isoformat(),
                      "event": event, **fields}), flush=True)


def config(path):
    c = json.loads(Path(path).read_text())
    if c["video_profile"] not in PROFILES:
        raise ValueError("Unknown video profile")
    if not re.fullmatch(r"/dev/(serial[0-9]+|tty(?:AMA|S|USB|ACM)[0-9]+)", c["serial_device"]):
        raise ValueError("Invalid serial device")
    if c["baud"] not in (57600, 115200, 230400, 460800, 921600):
        raise ValueError("Invalid serial baud")
    for key in ("mavlink_port", "video_port"):
        if not isinstance(c[key], int) or not 1024 <= c[key] <= 65535:
            raise ValueError("Invalid UDP port")
    if not 1 <= c["video_max_seconds"] <= 7200:
        raise ValueError("Video session limit must be 1..7200 seconds")
    if c["android_ip"]:
        tail_ip(c["android_ip"])
    if not re.fullmatch(r"[\w.-]+", c["lte_connection"]):
        raise ValueError("Invalid LTE profile name")
    return c


def tail_ip(value):
    addr = ipaddress.ip_address(value)
    if addr not in ipaddress.ip_network("100.64.0.0/10"):
        raise ValueError("Endpoint must be an explicit Tailscale IPv4 address")
    return str(addr)


def router_text(c, local_ip):
    tail_ip(c["android_ip"])
    local_ip = tail_ip(local_ip)
    return ("[General]\nTcpServerPort = 0\nReportStats = true\n"
            "[UartEndpoint aio]\nDevice = " + c["serial_device"] +
            f"\nBaud = {c['baud']}\nFlowControl = false\n"
            f"[UdpEndpoint android]\nMode = Server\nAddress = {local_ip}\nPort = {c['mavlink_port']}\n")


def router(c):
    if not Path(c["serial_device"]).exists():
        raise RuntimeError("UART missing: configure GPIO UART and reboot first")
    result = run(["tailscale", "ip", "-4"])
    text = router_text(c, result["stdout"])
    dest = Path("/run/cruza/router.conf")
    dest.write_text(text)
    os.execvp("mavlink-routerd", ["mavlink-routerd", "-c", str(dest)])


def video(c):
    dest = tail_ip(c["android_ip"])
    if run(["tailscale", "ip", "-4"])["code"]:
        raise RuntimeError("Tailscale is not ready")
    w, h, fps, bitrate = PROFILES[c["video_profile"]]
    capture = ["rpicam-vid", "--nopreview", "--timeout", "0", "--width", str(w),
               "--height", str(h), "--framerate", str(fps), "--codec", "h264",
               "--bitrate", str(bitrate), "--inline", "--intra", str(fps), "--output", "-"]
    pipeline = ["gst-launch-1.0", "-q", "fdsrc", "!", "h264parse", "!", "rtph264pay",
                "pt=96", "config-interval=1", "mtu=1200", "!", "udpsink",
                f"host={dest}", f"port={c['video_port']}", "sync=false", "async=false",
                "qos-dscp=8"]
    emit("video_start", profile=c["video_profile"], bitrate=bitrate,
         max_seconds=c["video_max_seconds"])
    processes = []
    stopping = False
    def stop(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    failed = False
    try:
        camera = subprocess.Popen(capture, stdout=subprocess.PIPE)
        processes.append(camera)
        stream = subprocess.Popen(pipeline, stdin=camera.stdout)
        processes.append(stream)
        camera.stdout.close()
        deadline = time.monotonic() + c["video_max_seconds"]
        while not stopping and time.monotonic() < deadline:
            if any(p.poll() is not None for p in processes):
                failed = True
                break
            time.sleep(1)
    finally:
        for p in processes:
            if p.poll() is None:
                p.terminate()
        for p in processes:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
    emit("video_stop", failed=failed)
    if failed:
        raise RuntimeError("Camera or RTP pipeline exited unexpectedly")


def usage_update(state, interface, rx, tx, boot, day):
    old = state.get("last", {})
    # First sample is a baseline; reset/boot change begins a new counter epoch.
    same = old.get("boot") == boot and old.get("interface") == interface
    drx = rx - old["rx"] if same and rx >= old["rx"] else 0
    dtx = tx - old["tx"] if same and tx >= old["tx"] else 0
    state["last"] = dict(interface=interface, rx=rx, tx=tx, boot=boot)
    days = state.setdefault("days", {})
    bucket = days.setdefault(day, {"rx": 0, "tx": 0})
    bucket["rx"] += drx
    bucket["tx"] += dtx
    return state


def usage(c):
    interface = c["lte_interface"]
    if not re.fullmatch(r"[\w.-]+", interface):
        emit("usage_unconfigured", detail="Set lte_interface after modem detection")
        return
    counters = Path("/sys/class/net") / interface / "statistics"
    if not counters.exists():
        emit("usage_interface_missing", interface=interface)
        return
    path = Path("/var/lib/cruza/usage.json")
    state = json.loads(path.read_text()) if path.exists() else {}
    now = dt.datetime.now(dt.timezone.utc)
    state = usage_update(state, interface, int((counters / "rx_bytes").read_text()),
                         int((counters / "tx_bytes").read_text()),
                         Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                         now.date().isoformat())
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state))
    temporary.replace(path)
    total = sum(v["rx"] + v["tx"] for v in state["days"].values())
    month = sum(v["rx"] + v["tx"] for k, v in state["days"].items() if k.startswith(now.strftime("%Y-%m")))
    today = state["days"][now.date().isoformat()]
    emit("usage", utc_day=now.date().isoformat(), today=today["rx"] + today["tx"],
         month=month, cumulative=total, warning=month >= c["usage_warning_bytes"],
         note="Interface estimate since first sample, not carrier billing")


def lte_health(c):
    # NetworkManager owns sessions. Retry only this profile, never reset hardware.
    result = run(["nmcli", "-t", "-f", "NAME", "connection", "show", "--active"])
    if result["code"]:
        emit("networkmanager_error", detail=result["stderr"])
        return
    if c["lte_connection"] not in result["stdout"].splitlines():
        exists = run(["nmcli", "-t", "-f", "NAME", "connection", "show"])
        if c["lte_connection"] not in exists["stdout"].splitlines():
            emit("lte_unconfigured")
            return
        emit("lte_activate", result=run(["nmcli", "--wait", "40", "connection", "up", c["lte_connection"]], 45))
    else:
        interface = c["lte_interface"]
        if interface:
            probe = run(["ping", "-I", interface, "-c", "1", "-W", "3", "1.1.1.1"], 5)
            emit("lte_probe", success=probe["code"] == 0,
                 note="ICMP may be blocked; an active session is not proof of internet access")
        # No teardown on one failed probe. NM handles bearer failure/recovery.


def diagnose(c):
    checks = {
        "model": ["cat", "/proc/device-tree/model"], "os": ["cat", "/etc/os-release"],
        "kernel": ["uname", "-a"], "uptime": ["uptime"], "memory": ["free", "-m"],
        "temperature": ["vcgencmd", "measure_temp"], "power": ["vcgencmd", "get_throttled"],
        "usb": ["lsusb"], "interfaces": ["ip", "-br", "addr"], "routes": ["ip", "route"],
        "camera": ["rpicam-hello", "--list-cameras"], "modems": ["mmcli", "-L"],
        "vpn": ["tailscale", "status", "--json"],
        "services": ["systemctl", "is-active", "cruza-router", "cruza-video", "ModemManager", "tailscaled"]}
    emit("diagnostics", checks={k: run(v, 20) for k, v in checks.items()},
         serial_exists=Path(c["serial_device"]).exists(),
         limitations="Heartbeat, mission, command acknowledgments and video delivery require bench validation")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["router", "video", "usage", "lte-health", "diagnose", "validate"])
    parser.add_argument("--config", default="/etc/cruza/config.json")
    args = parser.parse_args()
    c = config(args.config)
    actions = {"router": router, "video": video, "usage": usage,
               "lte-health": lte_health, "diagnose": diagnose,
               "validate": lambda _: emit("config_valid", endpoint_ready=bool(c["android_ip"]))}
    actions[args.action](c)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError) as error:
        emit("error", detail=str(error))
        sys.exit(1)
