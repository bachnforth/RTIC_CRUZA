"""One-time guarded local mirror patch; does not change command policy."""
import ast
import datetime
import hashlib
from pathlib import Path
import shutil
import subprocess

path = Path('/home/ebach/safety-arbiter/safety_mavlink_filter.py')
old = path.read_text()
if hashlib.sha256(path.read_bytes()).hexdigest() != '09f002b348391803eae81bfdb10db0bc36c3b7238c52764d00d888153c56c79c':
    raise SystemExit('Bridge changed since audit; no modifications made')
needle = '    udp.setblocking(False)'
addition = '''
    # Optional observer copy: fixed loopback, nonblocking, never receives commands.
    mirror = None
    if os.environ.get("CRUZA_FLEET_MIRROR", "0") == "1":
        mirror = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        mirror.setblocking(False)
'''
new = old.replace(needle,needle+'\n'+addition)
needle = '                udp.sendto(payload, args.udp_target)'
addition = '''                if mirror is not None:
                    try:
                        mirror.sendto(payload, ("127.0.0.1", 15612))
                    except OSError:
                        pass  # Optional observer cannot hold up the pilot path.
'''
new = new.replace(needle,addition+needle)
if new == old or new.count('mirror.sendto') != 1:
    raise SystemExit('Unexpected source layout')
before, after = ast.parse(old), ast.parse(new)
for node in before.body:
    if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name != 'main':
        updated = next(n for n in after.body if isinstance(n,ast.FunctionDef) and n.name==node.name)
        if ast.dump(node) != ast.dump(updated):
            raise SystemExit('Command policy function changed; refusing')
stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
backup = Path('/var/backups/cruza-fleet-observer')/('bridge-'+stamp)
backup.mkdir(parents=True,mode=0o700)
shutil.copy2(path,backup/path.name)
override = Path('/etc/systemd/system/safety-mavlink-filter.service.d/50-fleet-observer.conf')
if override.exists():
    raise SystemExit('Observer override already exists; refusing')
path.write_text(new)
override.parent.mkdir(exist_ok=True)
override.write_text('[Service]\nEnvironment=CRUZA_FLEET_MIRROR=1\n')
subprocess.run(['systemctl','daemon-reload'],check=True)
subprocess.run(['systemctl','restart','safety-mavlink-filter'],check=True)
print('quadpi telemetry copy enabled; backup:',backup)
