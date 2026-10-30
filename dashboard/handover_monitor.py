"""Record a handover test from the running dashboard: what the Cruza saw, when
each card appeared and got its picture, what the operator decided, and what
each quad then did. Read-only: it only polls /status once a second and sends
nothing to any aircraft.

    python handover_monitor.py            # until Ctrl+C
    python handover_monitor.py --summary runtime/handover-monitor-<time>.jsonl

Writes runtime/handover-monitor-<time>.jsonl (one line per change) and prints
the same changes as they happen. The dashboard's own handover.log, handover/
pictures and the quad and TFW command logs stay the record of decisions and
commands; this adds the timing between them.
"""
import argparse
import json
import time
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
URL = 'http://127.0.0.1:8765/status'
NAMES = {'cruza': 'Cruza', 'quadpi': 'quadpi', 'rn03': 'TFW drone'}


def now():
    return datetime.now().astimezone()


def stamp(t):
    return t.strftime('%H:%M:%S')


def fetch():
    with urllib.request.urlopen(URL, timeout=3) as r:
        return json.load(r)


def aircraft(s):
    """Per aircraft: link state that matters for the test."""
    out = {}
    for f in s.get('fleet', []):
        out[f['name']] = dict(online=f.get('online'), armed=f.get('armed'), mode=f.get('mode'),
                              landed=f.get('landed_state'))
    for name, c in (s.get('controls') or {}).items():
        link = c.get('link') or {}
        out.setdefault(name, {}).update(control=link.get('online'))
    return out


def commands(s):
    """Last command result per controlled aircraft."""
    out = {}
    for name, c in (s.get('controls') or {}).items():
        h = c.get('history') or []
        if h:
            last = h[-1]
            out[name] = dict(at=last.get('time'), action=last.get('action'), ok=last.get('ok'),
                             result=last.get('result'))
    return out


def monitor(path):
    print(f'Recording to {path}  (Ctrl+C to stop)')
    seen, planes, cmds, down = {}, {}, {}, False
    with open(path, 'a', encoding='utf-8') as log:
        def write(kind, text, **data):
            t = now()
            log.write(json.dumps(dict(time=t.isoformat(timespec='milliseconds'), kind=kind, **data)) + '\n')
            log.flush()
            print(f'{stamp(t)}  {text}')
        while True:
            try:
                s = fetch()
            except OSError as e:
                if not down:
                    write('dashboard', f'Dashboard not answering ({e})', ok=False)
                down = True
                time.sleep(2)
                continue
            if down:
                write('dashboard', 'Dashboard answering again', ok=True)
                down = False
            try:
                seen, planes, cmds = record(s, write, seen, planes, cmds)
            except Exception as e:  # never stop recording mid-flight over one odd status
                write('error', f'Recorder error, still recording: {e!r}', error=repr(e))
            time.sleep(1)


def record(s, write, seen, planes, cmds):
    """Write every change since the last poll; return the new state."""
    for r in s.get('handover', []):
        old = seen.get(r['id'])
        if old is None:
            write('request', f"{r['id']} NEW {r['cls']} from {NAMES.get(r['src'], r['src'])} "
                  f"({round(r['score']*100)}%) at {r['lat']:.6f}, {r['lon']:.6f}"
                  + (', picture' if r.get('image_rev') else ', no picture yet'),
                  id=r['id'], cls=r['cls'], src=r['src'], score=r['score'],
                  lat=r['lat'], lon=r['lon'], range_m=r.get('range_m'), image=bool(r.get('image_rev')))
        else:
            if r.get('image_rev') and r['image_rev'] != old.get('image_rev'):
                write('image', f"{r['id']} picture {'received' if not old.get('image_rev') else 'updated'}"
                      f" (rev {r['image_rev']})", id=r['id'], rev=r['image_rev'])
            if r['status'] != old['status']:
                d = r.get('decision') or {}
                text = f"{r['id']} {r['status'].upper()}"
                if r['status'] == 'approved':
                    text += f" -> {NAMES.get(d.get('target'), d.get('target'))}, {d.get('action')}, {d.get('mode')}"
                elif r['status'] == 'denied' and d.get('reason'):
                    text += f", {d['reason']}"
                write('decision', text, id=r['id'], status=r['status'], decision=d,
                      open_s=r.get('open_s'))
        seen[r['id']] = r
    for name, state in aircraft(s).items():
        if state != planes.get(name):
            old = planes.get(name) or {}
            changed = {k: v for k, v in state.items() if old.get(k) != v}
            write('aircraft', f"{NAMES.get(name, name)}: " + ', '.join(f'{k} {v}' for k, v in changed.items()),
                  name=name, **state)
            planes[name] = state
    for name, c in commands(s).items():
        if c != cmds.get(name):
            write('command', f"{NAMES.get(name, name)} <- {c['action']}: "
                  f"{'OK' if c['ok'] else 'FAILED'}, {c['result']}", name=name, **c)
            cmds[name] = c
    return seen, planes, cmds


def summary(path):
    rows = [json.loads(line) for line in open(path, encoding='utf-8')]
    t = lambda r: datetime.fromisoformat(r['time'])
    first = {}
    for r in rows:
        if r['kind'] == 'request':
            first[r['id']] = dict(cls=r['cls'], new=t(r), image=t(r) if r['image'] else None)
        elif r['kind'] == 'image' and r['id'] in first and first[r['id']]['image'] is None:
            first[r['id']]['image'] = t(r)
        elif r['kind'] == 'decision' and r['id'] in first:
            first[r['id']].update(decided=t(r), status=r['status'], target=(r.get('decision') or {}).get('target'))
    launches = [r for r in rows if r['kind'] == 'command' and r.get('action') == 'arm_mission']
    print('Request  class    card->picture  card->decision  decision            launch')
    for rid, v in first.items():
        pic = f"{(v['image']-v['new']).total_seconds():5.0f} s" if v['image'] else '   none'
        dec = f"{(v['decided']-v['new']).total_seconds():5.0f} s" if v.get('decided') else '      -'
        go = next((r for r in launches if r['name'] == v.get('target') and v.get('decided') and t(r) >= v['decided']), None)
        launch = (f"{'OK' if go['ok'] else 'FAILED'} {(t(go)-v['decided']).total_seconds():.0f} s after approval"
                  if go else '-')
        print(f"{rid:8} {v['cls']:8} {pic:>12}  {dec:>13}  "
              f"{(v.get('status') or 'pending') + (' -> ' + NAMES.get(v.get('target'), '') if v.get('target') else ''):18}  {launch}")


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--summary', help='summarise a recording instead of recording')
    args = ap.parse_args()
    if args.summary:
        summary(args.summary)
    else:
        try:
            monitor(HERE/'runtime'/f"handover-monitor-{datetime.now().strftime('%Y%m%d-%H%M%S')}.jsonl")
        except KeyboardInterrupt:
            print('Stopped.')
