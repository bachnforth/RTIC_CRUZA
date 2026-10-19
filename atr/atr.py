#!/usr/bin/env python3
"""Ground-station recognition of people and vehicles in the fleet video.

Reads the dashboard's local video copies only. No SSH, aircraft, MAVLink,
camera, route or flight-controller access; stopping it changes nothing aboard.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import signal
import threading
import time
import urllib.request

# FFmpeg reads this before OpenCV opens a stream. TCP needs no extra UDP ports.
os.environ.setdefault('OPENCV_FFMPEG_CAPTURE_OPTIONS',
                      'rtsp_transport;tcp|fflags;nobuffer|flags;low_delay')
# A missing feed is reported in our status line; silence repeated library warnings.
os.environ.setdefault('OPENCV_LOG_LEVEL', 'ERROR')
os.environ.setdefault('OPENCV_FFMPEG_LOGLEVEL', '-8')
import cv2
import numpy as np
import onnxruntime as ort

HERE = Path(__file__).resolve().parent
STOP = threading.Event()
RELEASE = 'https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/'
# Apache-2.0 YOLOX COCO models: input size and SHA256 of the official release file.
MODELS = {'yolox_nano': (416, 'c789161ed43c8269fcd4e67c67eeeb4e80c622da2eb296a20bc6007bd18a0b7d'),
          'yolox_tiny': (416, '427cc366d34e27ff7a03e2899b5e3671425c262ea2291f88bb942bc1cc70b0f7'),
          'yolox_s': (640, 'c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063')}
# COCO class index -> (category, label). Every other COCO class is ignored.
CLASSES = {0: ('person', 'person'), 1: ('vehicle', 'bicycle'), 2: ('vehicle', 'car'),
           3: ('vehicle', 'motorcycle'), 5: ('vehicle', 'bus'), 6: ('vehicle', 'train'),
           7: ('vehicle', 'truck'), 8: ('vehicle', 'boat')}
CATEGORIES = ('person', 'vehicle')
COLORS = {'person': (0, 200, 255), 'vehicle': (255, 160, 0)}
DEFAULT_SOURCES = ['cruza=rtsp://127.0.0.1:8554/cruza', 'quadpi=rtsp://127.0.0.1:8554/quadpi']


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def fetch_model(name, directory=HERE/'models'):
    size, expected = MODELS[name]
    path = directory/(name+'.onnx')
    if not path.is_file():
        directory.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix('.part')
        print(f'Downloading {name} model once from the official YOLOX release...', flush=True)
        urllib.request.urlretrieve(RELEASE+name+'.onnx', partial)
        if sha256(partial) != expected:
            partial.unlink()
            raise RuntimeError('Model checksum mismatch; download discarded')
        partial.replace(path)
    elif sha256(path) != expected:
        raise RuntimeError(f'{path} does not match the expected checksum; delete it to re-download')
    return path, size


class Detector:
    """YOLOX on ONNX Runtime, reduced to people and vehicles."""
    def __init__(self, path, size, threshold=.35, overlap=.45):
        self.session = ort.InferenceSession(str(path), providers=['CPUExecutionProvider'])
        self.input = self.session.get_inputs()[0].name
        self.size, self.threshold, self.overlap = size, threshold, overlap
        grids, strides = [], []
        for stride in (8, 16, 32):
            n = size//stride
            y, x = np.mgrid[:n, :n]
            grids.append(np.stack((x, y), -1).reshape(-1, 2))
            strides.append(np.full((n*n, 1), stride))
        self.grid = np.concatenate(grids).astype(np.float32)
        self.stride = np.concatenate(strides).astype(np.float32)
        self.wanted = np.array(sorted(CLASSES))

    def letterbox(self, frame):
        h, w = frame.shape[:2]
        scale = min(self.size/h, self.size/w)
        resized = cv2.resize(frame, (max(1, round(w*scale)), max(1, round(h*scale))))
        canvas = np.full((self.size, self.size, 3), 114, np.uint8)
        canvas[:resized.shape[0], :resized.shape[1]] = resized
        # YOLOX release models take unnormalized BGR, which is what OpenCV decodes.
        return canvas.transpose(2, 0, 1)[None].astype(np.float32), scale

    def decode(self, output, scale, shape):
        out = output[0]
        centre = (out[:, :2]+self.grid)*self.stride
        half = np.exp(np.minimum(out[:, 2:4], 10))*self.stride/2
        scores = out[:, 4:5]*out[:, 5:][:, self.wanted]
        best = scores.argmax(1)
        score = scores[np.arange(len(best)), best]
        keep = score >= self.threshold
        if not keep.any():
            return []
        h, w = shape[:2]
        boxes = np.concatenate((centre-half, centre+half), 1)[keep]/scale
        boxes = boxes.clip(0, [w, h, w, h])
        classes, score = self.wanted[best[keep]], score[keep]
        # Overlap removal per category, so one vehicle is not both "car" and "truck".
        category = [CATEGORIES.index(CLASSES[c][0]) for c in classes]
        xywh = [[float(x1), float(y1), float(x2-x1), float(y2-y1)] for x1, y1, x2, y2 in boxes]
        chosen = cv2.dnn.NMSBoxesBatched(xywh, score.tolist(), category, self.threshold, self.overlap)
        return [dict(category=CLASSES[classes[i]][0], label=CLASSES[classes[i]][1],
                     score=float(score[i]), box=tuple(int(round(v)) for v in boxes[i]))
                for i in np.array(chosen).reshape(-1)]

    def detect(self, frame):
        blob, scale = self.letterbox(frame)
        return self.decode(self.session.run(None, {self.input: blob})[0], scale, frame.shape)


def iou(a, b):
    w = min(a[2], b[2])-max(a[0], b[0])
    h = min(a[3], b[3])-max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.
    inter = w*h
    return inter/((a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-inter)


class Tracker:
    """Greedy box-overlap tracker. Gives steady IDs and reports a target only
    after min_hits consecutive sightings, which suppresses one-frame false alarms."""
    def __init__(self, min_hits=3, max_age=1.5, match=.3):
        self.min_hits, self.max_age, self.match = min_hits, max_age, match
        self.tracks, self.next_id = [], 1

    def update(self, detections, now):
        pairs = sorted(((iou(t['box'], d['box']), ti, di)
                        for ti, t in enumerate(self.tracks) for di, d in enumerate(detections)
                        if t['category'] == d['category']), reverse=True)
        used_t, used_d, started, ended = set(), set(), [], []
        for overlap, ti, di in pairs:
            if overlap < self.match:
                break
            if ti in used_t or di in used_d:
                continue
            used_t.add(ti)
            used_d.add(di)
            t, d = self.tracks[ti], detections[di]
            t.update(box=d['box'], score=d['score'], last=now, hits=t['hits']+1)
            if d['score'] >= t['best_score']:
                t.update(best_score=d['score'], label=d['label'])
            if not t['confirmed'] and t['hits'] >= self.min_hits:
                t['confirmed'] = True
                started.append(t)
        alive = []
        for ti, t in enumerate(self.tracks):
            if ti not in used_t and not t['confirmed']:
                t['hits'] = 0  # Unconfirmed tracks need consecutive sightings.
            if now-t['last'] <= self.max_age:
                alive.append(t)
            elif t['confirmed']:
                ended.append(t)
        for di, d in enumerate(detections):
            if di not in used_d:
                alive.append(dict(d, id=self.next_id, hits=1, first=now, last=now,
                                  best_score=d['score'], confirmed=self.min_hits <= 1, reported=now))
                self.next_id += 1
                if self.min_hits <= 1:
                    started.append(alive[-1])
        self.tracks = alive
        return started, ended

    def visible(self, now):
        return [t for t in self.tracks if t['confirmed'] and t['last'] == now]


class Source:
    """Background reader that keeps only the newest frame, so recognition
    stays on live video instead of falling behind."""
    def __init__(self, name, url):
        self.name, self.url = name, url
        self.file = Path(url).is_file()
        self.frame, self.seq, self.status, self.finished = None, 0, 'connecting', False
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def latest(self):
        with self.lock:
            return self.frame, self.seq

    def run(self):
        target = int(self.url) if self.url.isdigit() else self.url
        while not STOP.is_set():
            capture = cv2.VideoCapture(target, cv2.CAP_ANY if isinstance(target, int) else cv2.CAP_FFMPEG,
                                       [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000])
            if capture.isOpened():
                self.status = 'live'
                period = 1/(capture.get(cv2.CAP_PROP_FPS) or 15) if self.file else 0
                while not STOP.is_set():
                    ok, frame = capture.read()
                    if not ok:
                        break
                    with self.lock:
                        self.frame, self.seq = frame, self.seq+1
                    if period:
                        STOP.wait(period)  # Play recordings at their real speed.
            capture.release()
            if self.file:
                self.status, self.finished = 'finished', True
                return
            self.status = 'waiting for video (is the dashboard open and not paused?)'
            STOP.wait(3)


class EventLog:
    def __init__(self, directory, snapshots):
        stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory/f'detections-{stamp}.jsonl'
        self.file = open(self.path, 'a', encoding='utf-8')
        self.snapshots = directory/f'snapshots-{stamp}' if snapshots else None

    def write(self, event, source, track, now, frame=None):
        record = dict(time=dt.datetime.now(dt.timezone.utc).isoformat(), event=event, source=source,
                      id=track['id'], category=track['category'], label=track['label'],
                      score=round(track['score'], 3), best_score=round(track['best_score'], 3),
                      box=list(track['box']), seconds_tracked=round(now-track['first'], 1))
        self.file.write(json.dumps(record)+'\n')
        self.file.flush()
        if event != 'target_update':
            print(f"{record['time'][11:19]} {source:7} {event:12} #{track['id']} {track['label']} "
                  f"({record['best_score']:.2f})", flush=True)
        if event == 'target_start' and self.snapshots is not None and frame is not None:
            self.snapshots.mkdir(exist_ok=True)
            x1, y1, x2, y2 = track['box']
            pad = max(x2-x1, y2-y1)//2+8
            h, w = frame.shape[:2]
            crop = frame[max(0, y1-pad):min(h, y2+pad), max(0, x1-pad):min(w, x2+pad)]
            cv2.imwrite(str(self.snapshots/f"{source}-{track['id']:05d}-{track['label']}.jpg"), crop)

    def close(self):
        self.file.close()


def draw(frame, name, tracks, status, rate):
    for t in tracks:
        x1, y1, x2, y2 = t['box']
        color = COLORS[t['category']]
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        text = f"{t['label']} #{t['id']} {t['score']:.2f}"
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, .5, 1)
        cv2.rectangle(frame, (x1, max(0, y1-th-6)), (x1+tw+4, max(th+6, y1)), color, -1)
        cv2.putText(frame, text, (x1+2, max(th+2, y1-4)), cv2.FONT_HERSHEY_SIMPLEX, .5, (0, 0, 0), 1)
    people = sum(t['category'] == 'person' for t in tracks)
    summary = f'{name}  people {people}  vehicles {len(tracks)-people}  {rate:.1f} fps  {status}'
    cv2.putText(frame, summary, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, .55, (0, 0, 0), 3)
    cv2.putText(frame, summary, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, .55, (255, 255, 255), 1)
    return frame


def parse_source(text):
    name, sep, url = text.partition('=')
    if not sep or not name.isidentifier() or not url:
        raise argparse.ArgumentTypeError('Use NAME=URL, e.g. cruza=rtsp://127.0.0.1:8554/cruza')
    return name, url


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', action='append', type=parse_source,
                        help='NAME=URL; repeatable. URL may be RTSP, a video file or a camera number. '
                             'Default: both dashboard feeds')
    parser.add_argument('--model', choices=MODELS, default='yolox_s',
                        help='yolox_s is most accurate; yolox_tiny/nano are faster on slow laptops')
    parser.add_argument('--threshold', type=float, default=.35, help='Minimum confidence, 0..1')
    parser.add_argument('--min-hits', type=int, default=3, help='Sightings before a target is reported')
    parser.add_argument('--no-window', action='store_true', help='Log only; do not show annotated video')
    parser.add_argument('--snapshots', action='store_true', help='Save a picture of each new target')
    parser.add_argument('--log-dir', type=Path, default=HERE/'runtime')
    args = parser.parse_args(argv)
    if not 0 < args.threshold < 1 or args.min_hits < 1:
        parser.error('threshold must be between 0 and 1 and min-hits at least 1')

    detector = Detector(*fetch_model(args.model), threshold=args.threshold)
    sources = [Source(*s) for s in args.source or map(parse_source, DEFAULT_SOURCES)]
    trackers = {s.name: Tracker(min_hits=args.min_hits) for s in sources}
    seen = {s.name: 0 for s in sources}
    rates = {s.name: 0. for s in sources}
    log = EventLog(args.log_dir, args.snapshots)
    signal.signal(signal.SIGINT, lambda *_: STOP.set())
    signal.signal(signal.SIGTERM, lambda *_: STOP.set())
    for s in sources:
        s.thread.start()
    print(f'Recognizing people and vehicles with {args.model}. Log: {log.path}', flush=True)
    print('Press Ctrl+C (or q in a video window) to stop.', flush=True)
    last_status = 0
    try:
        while not STOP.is_set():
            worked = False
            for s in sources:
                frame, seq = s.latest()
                if seq == seen[s.name]:
                    continue
                seen[s.name], worked = seq, True
                start = time.monotonic()
                detections = detector.detect(frame)
                now = time.monotonic()
                rates[s.name] = .9*rates[s.name]+.1/max(now-start, 1e-3)
                tracker = trackers[s.name]
                started, ended = tracker.update(detections, now)
                for t in started:
                    log.write('target_start', s.name, t, now, frame)
                for t in tracker.visible(now):
                    if now-t['reported'] >= 1:
                        t['reported'] = now
                        log.write('target_update', s.name, t, now)
                for t in ended:
                    log.write('target_end', s.name, t, now)
                if not args.no_window:
                    cv2.imshow(s.name, draw(frame.copy(), s.name, tracker.visible(now), s.status, rates[s.name]))
            if not args.no_window and cv2.waitKey(1) & 0xFF == ord('q'):
                break
            if all(s.finished for s in sources) and not worked:
                break
            if time.monotonic()-last_status > 10:
                last_status = time.monotonic()
                print('  '.join(f'{s.name}: {s.status}' for s in sources), flush=True)
            if not worked:
                STOP.wait(.005)
    finally:
        STOP.set()
        for s in sources:
            s.thread.join(6)
        log.close()
        if not args.no_window:
            cv2.destroyAllWindows()
    print(f'Stopped. Detections saved to {log.path}', flush=True)


if __name__ == '__main__':
    main()
