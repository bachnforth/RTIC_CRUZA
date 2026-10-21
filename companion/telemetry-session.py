"""SSH session wrapper: terminate optional reader when viewer lease expires."""
import os
import select
import subprocess
import sys

port = sys.argv[1]
if port not in ('15610', '15611'):
    raise SystemExit('Invalid telemetry port')
child = subprocess.Popen([sys.executable, '/opt/cruza-telemetry-relay.py', '--port', port], stdin=subprocess.DEVNULL)
try:
    while child.poll() is None:
        ready, _, _ = select.select([0], [], [], 15)
        if not ready or not os.read(0, 128):
            break
finally:
    if child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
