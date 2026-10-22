"""Validate received MAVLink frame checksums in an offline Pi UART capture."""
from collections import Counter
import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / '.flightlog-deps'))
from pymavlink.dialects.v20 import ardupilotmega

p = ardupilotmega.MAVLink(None)
p.robust_parsing = True
messages = p.parse_buffer(Path(sys.argv[1]).read_bytes()) or []
valid = [m for m in messages if m.get_type() != 'BAD_DATA']
print(json.dumps({'valid_frames': len(valid), 'message_types': dict(Counter(m.get_type() for m in valid)),
                  'sources': sorted(set((m.get_srcSystem(), m.get_srcComponent()) for m in valid)),
                  'heartbeats': [m.to_dict() for m in valid if m.get_type() == 'HEARTBEAT'],
                  'parameter_values': [m.to_dict() for m in valid if m.get_type() == 'PARAM_VALUE']}, indent=2))
if not valid:
    raise SystemExit(1)
