#!/usr/bin/env python3
"""Read-only native flight telemetry, persistence and episode supervision."""
import copy
import io
import json
import math

MAX_JSON = 65536


def bounded_json(payload):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def check(value, depth=0):
        if depth > 8:
            raise ValueError("JSON nesting limit exceeded")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("nonfinite JSON value")
        if isinstance(value, dict):
            for child in value.values():
                check(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                check(child, depth + 1)

    if len(payload) > MAX_JSON:
        raise ValueError("JSON size limit exceeded")
    try:
        result = json.loads(payload, object_pairs_hook=pairs)
        check(result)
        return result
    except (RecursionError, UnicodeError, OverflowError) as error:
        raise ValueError("invalid bounded JSON") from error


def number(value):
    try:
        return type(value) in {int, float} and math.isfinite(value)
    except OverflowError:
        return False


DEPTH_CONSTANTS = dict(
    source="SimZedFrameStore.depth/Copper.ZedSource", source_width=320, source_height=240,
    width=32, height=24, encoding="u8-hex", sampling="nearest-cell-center",
    source_units="millimetres", invalid_u8=0,
    invalid_rule="source_mm == 0 or source_mm > 20000",
    decode_m="(1 + (q - 1) * 19999 / 254) / 1000; q=0 invalid")


def normalize_depth_preview(value, frame):
    """Allowlist the bounded CPU observation; never imply camera acquisition time."""
    if not isinstance(value, dict):
        return None
    if any(type(value.get(key)) is not type(expected) or value[key] != expected
           for key, expected in DEPTH_CONSTANTS.items()):
        return None
    seq = value.get("source_seq")
    if type(seq) is not int or not 0 <= seq <= 2**53 - 1:
        return None
    for sample, row in (("sample_wall_time_s", "wall_time_s"), ("sample_sim_time_s", "sim_time_s")):
        if (not number(value.get(sample)) or value[sample] < 0 or
                not number(frame.get(row)) or value[sample] > frame[row] + 1e-6):
            return None
    limits = value.get("range_m")
    if not isinstance(limits, list) or len(limits) != 2 or not all(number(v) for v in limits) or limits != [0.001, 20.0]:
        return None
    data = value.get("data")
    if (not isinstance(data, str) or len(data) != 1536 or
            any(c not in "0123456789abcdef" for c in data) or not any(c != "0" for c in data)):
        return None
    return dict(DEPTH_CONSTANTS, source_seq=seq, sample_wall_time_s=value["sample_wall_time_s"],
                sample_sim_time_s=value["sample_sim_time_s"], range_m=[0.001, 20.0], data=data)


def validate_frame(payload):
    frame = bounded_json(payload)
    if not isinstance(frame, dict):
        raise ValueError("native frame must be an object")
    if type(frame.get("schema_version")) is not int or frame["schema_version"] != 1:
        raise ValueError("unsupported native telemetry schema")
    if type(frame.get("seq")) is not int or frame["seq"] < 0:
        raise ValueError("invalid native sequence")
    if not number(frame.get("sim_time_s")) or frame["sim_time_s"] < 0:
        raise ValueError("invalid simulation time")
    for key in ("position_m", "velocity_m_s", "policy_prediction_m_s"):
        if key not in frame:
            raise ValueError(f"missing {key}")
        vector = frame[key]
        if vector is not None and (not isinstance(vector, dict) or set(vector) != {"x", "y", "z"}
                                   or not all(number(v) for v in vector.values())):
            raise ValueError(f"invalid native vector {key}")
    rotation = frame.get("rotation")
    if rotation is not None and (not isinstance(rotation, dict) or set(rotation) != {"x", "y", "z", "w"}
                                 or not all(number(v) for v in rotation.values())):
        raise ValueError("invalid native rotation quaternion")
    if rotation is not None and sum(v * v for v in rotation.values()) == 0:
        raise ValueError("zero native rotation quaternion")
    policy_seq = frame.get("policy_observation_seq")
    if policy_seq is not None and (type(policy_seq) is not int or policy_seq < 0):
        raise ValueError("invalid policy observation sequence")
    for key in ("armed", "auto_enabled"):
        if type(frame.get(key)) is not bool:
            raise ValueError(f"invalid native boolean {key}")
    if frame.get("world") not in ("forest", "urban"):
        raise ValueError("invalid native world")
    if not isinstance(frame.get("mode"), str) or not 1 <= len(frame["mode"]) <= 64:
        raise ValueError("invalid native mode")
    if "inference_backend" not in frame or frame["inference_backend"] not in (None, "cpu", "cuda"):
        raise ValueError("invalid inference backend")
    count = frame.get("inference_count")
    if "inference_count" not in frame or (count is not None and (type(count) is not int or count < 0)):
        raise ValueError("invalid inference count")
    if "graphics" in frame:
        graphics = frame["graphics"]
        if not isinstance(graphics, dict):
            raise ValueError("invalid graphics telemetry")
        for key in ("backend", "adapter_name"):
            if key not in graphics or (graphics[key] is not None and
                    (not isinstance(graphics[key], str) or len(graphics[key]) > 512)):
                raise ValueError("invalid graphics telemetry")
    for key in ("graphics_backend", "graphics_adapter"):
        if key in frame and frame[key] is not None and (not isinstance(frame[key], str) or len(frame[key]) > 512):
            raise ValueError("invalid graphics telemetry")
    for metadata, vendor_key, device_key in ((frame, "graphics_vendor_id", "graphics_device_type"),
                                            (frame.get("graphics", {}), "vendor_id", "device_type")):
        vendor = metadata.get(vendor_key)
        if vendor is not None and (type(vendor) is not int or not 0 <= vendor <= 0xffffffff):
            raise ValueError("invalid graphics vendor id")
        device = metadata.get(device_key)
        if device not in (None, "IntegratedGpu", "DiscreteGpu", "Cpu", "VirtualGpu", "Other"):
            raise ValueError("invalid graphics device type")
    if "depth_preview" in frame and normalize_depth_preview(frame["depth_preview"], frame) is None:
        raise ValueError("invalid native depth preview")
    return frame


def normalize_frame(frame):
    native_frame = copy.deepcopy(frame)
    if "depth_preview" in native_frame:
        preview = normalize_depth_preview(native_frame.pop("depth_preview"), native_frame)
        if preview is not None:
            native_frame["depth_preview"] = preview
    graphics = native_frame.setdefault("graphics", {})
    for key, raw_key in (("backend", "graphics_backend"), ("adapter_name", "graphics_adapter"),
                         ("vendor_id", "graphics_vendor_id"), ("device_type", "graphics_device_type")):
        graphics.setdefault(key, native_frame.get(raw_key))
    return native_frame


class TelemetryReader:
    def __init__(self, stream):
        self.stream = stream
        self.offset = 0
        self.buffer = b""
        self.last = None

    def poll(self):
        if self.stream.seek(0, 2) < self.offset:
            raise ValueError("native telemetry was truncated")
        self.stream.seek(self.offset)
        data = self.stream.read(MAX_JSON + 1)
        self.offset += len(data)
        self.buffer += data
        result = []
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            frame = validate_frame(line)
            if self.last is None:
                if frame["seq"] != 0:
                    raise ValueError("native sequence must start at zero")
            elif frame["seq"] != self.last["seq"] + 1 or frame["sim_time_s"] < self.last["sim_time_s"]:
                raise ValueError("native telemetry sequence/time regression")
            self.last = frame
            result.append(frame)
        if len(self.buffer) > MAX_JSON:
            raise ValueError("native telemetry line size limit exceeded")
        return result

import threading
import time
from collections import deque
from datetime import datetime, timezone


def utcnow():
    return datetime.now(timezone.utc).isoformat()


class StateStore:
    def __init__(self, revision="unknown", world="forest", inference="cpu", episode_seconds=45,
                 inactivity_timeout=30, history_limit=600):
        if type(history_limit) is not int or not 1 <= history_limit <= 4096:
            raise ValueError("invalid live telemetry history limit")
        self.lock = threading.RLock()
        self.history = deque(maxlen=history_limit)
        self.started = time.monotonic()
        self.updated = self.progress_at = None
        self.inactivity_timeout = inactivity_timeout
        self.advanced = False
        self.data = dict(status="starting", error=None,
                         engine=dict(native=True, copper_version="1.4.0-dev",
                                     source_revision="d46ef87a65c7ba93bcad3c236da99e52cd77f319",
                                     revision=revision),
                         configuration=dict(world=world, inference=inference, autonomy=True,
                                            episode_seconds=episode_seconds),
                         episode=None, frame=None, recordings=[])

    def begin(self, run_id):
        with self.lock:
            self.history.clear()
            self.data.update(status="starting", error=None, frame=None,
                             episode=dict(id=run_id, started_at=utcnow()))
            self.updated = self.progress_at = None
            self.advanced = False

    def publish(self, frame):
        with self.lock:
            previous = self.data["frame"]
            self.updated = time.monotonic()
            if previous is not None and frame["sim_time_s"] > previous["sim_time_s"]:
                self.progress_at = self.updated
                self.advanced = True
                self.data["status"] = "live"
            native_frame = normalize_frame(frame)
            self.data["frame"] = native_frame
            self.history.append((self.updated - self.started, native_frame))

    def telemetry_snapshot(self, after_seq=None, episode_id=None):
        if after_seq is not None and (type(after_seq) is not int or not 0 <= after_seq <= 2**53 - 1):
            raise ValueError("invalid telemetry cursor")
        with self.lock:
            now = time.monotonic()
            oldest = self.history[0][1]["seq"] if self.history else None
            latest = self.history[-1][1]["seq"] if self.history else None
            episode = self.data["episode"]
            current = episode.get("id") if isinstance(episode, dict) else None
            reset = (after_seq is None or episode_id != current or
                     (oldest is not None and after_seq < oldest - 1) or
                     (latest is not None and after_seq > latest))
            selected = [frame for _, frame in self.history if reset or frame["seq"] > after_seq]
            return dict(schema_version=1, status=self.data["status"],
                        engine=copy.deepcopy(self.data["engine"]),
                        episode=copy.deepcopy(self.data["episode"]),
                        frames=copy.deepcopy(selected), oldest_seq=oldest, latest_seq=latest,
                        reset=reset, server_uptime_s=now - self.started,
                        frame_age_s=None if self.updated is None else now - self.updated)

    def fail(self, error):
        with self.lock:
            self.data.update(status="failed", error=str(error))

    def ready(self, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            return (self.data["status"] in {"live", "between_episodes"} and self.advanced
                    and self.progress_at is not None
                    and now - self.progress_at < self.inactivity_timeout)

    def snapshot(self):
        with self.lock:
            return dict(copy.deepcopy(self.data), uptime_s=time.monotonic() - self.started,
                        frame_age_s=None if self.updated is None else time.monotonic() - self.updated)


import os
import re
import shutil
import stat
import uuid
from pathlib import Path
from contextlib import ExitStack, contextmanager

DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
RUN_ID = re.compile(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}")


def check_id(run_id):
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        raise ValueError("invalid recording id")


def open_regular(parent, name, flags=os.O_RDONLY):
    fd = os.open(name, flags | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, 0o640, dir_fd=parent)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        os.close(fd)
        raise ValueError("artifact must be a single-link regular file")
    return fd


@contextmanager
def absolute_directory(path):
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("directory path must be absolute and confined")
    fd = os.open("/", DIR_FLAGS)
    try:
        for part in path.parts[1:]:
            child = os.open(part, DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


class RecordingStore:
    """Own only valid run-id children. Never dereference recording symlinks."""
    def __init__(self, root, max_runs=2, max_bytes=4 * 1024**3):
        self.root = Path(root).absolute()
        # Parent is provisioned by boot. Do not recursively create/chown volume contents.
        with absolute_directory(self.root.parent) as parent:
            try:
                os.mkdir(self.root.name, mode=0o750, dir_fd=parent)
            except FileExistsError:
                pass
        with self.open_root():
            pass
        self.max_runs, self.max_bytes = max_runs, max_bytes
        self.lock = threading.RLock()
        self.download_slot = threading.BoundedSemaphore(1)
        self.playback_slot = threading.BoundedSemaphore(2)

    @contextmanager
    def open_root(self):
        with absolute_directory(self.root) as fd:
            yield fd

    @contextmanager
    def open_run(self, run_id):
        check_id(run_id)
        with self.open_root() as root:
            fd = os.open(run_id, DIR_FLAGS, dir_fd=root)
        try:
            yield fd
        finally:
            os.close(fd)

    def directory(self, run_id, create=False):
        check_id(run_id)
        if create:
            with self.open_root() as root:
                os.mkdir(run_id, mode=0o750, dir_fd=root)
        with self.open_run(run_id):
            pass
        return self.root / run_id

    @staticmethod
    def read_manifest(fd, run_id):
        with os.fdopen(open_regular(fd, "manifest.json"), "rb") as stream:
            item = bounded_json(stream.read(MAX_JSON + 1))
        expected = {"schema_version", "id", "completed", "started_at", "ended_at"}
        if not isinstance(item, dict) or set(item) != expected or item["id"] != run_id or \
                type(item["schema_version"]) is not int or item["schema_version"] != 1 or \
                type(item["completed"]) is not bool:
            raise ValueError("invalid run manifest")
        for key in ("started_at", "ended_at"):
            value = item[key]
            if value is None and key == "ended_at" and not item["completed"]:
                continue
            if not isinstance(value, str) or len(value) > 64:
                raise ValueError("invalid manifest timestamp")
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                raise ValueError("manifest timestamp must have timezone")
        if item["completed"] and datetime.fromisoformat(item["ended_at"]) < datetime.fromisoformat(item["started_at"]):
            raise ValueError("manifest ends before it starts")
        if not item["completed"] and item["ended_at"] is not None:
            raise ValueError("incomplete manifest has ended_at")
        return item

    @staticmethod
    def write_manifest(fd, item):
        temp = ".manifest-" + uuid.uuid4().hex
        try:
            raw = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                          0o640, dir_fd=fd)
            with os.fdopen(raw, "wb") as stream:
                stream.write(json.dumps(item, allow_nan=False).encode())
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, "manifest.json", src_dir_fd=fd, dst_dir_fd=fd)
            os.fsync(fd)
        finally:
            try:
                os.unlink(temp, dir_fd=fd)
            except FileNotFoundError:
                pass

    def begin(self, run_id):
        with self.lock:
            path = self.directory(run_id, create=True)
            with self.open_run(run_id) as fd:
                os.mkdir("logs", mode=0o750, dir_fd=fd)
                self.write_manifest(fd, dict(schema_version=1, id=run_id, completed=False,
                                             started_at=utcnow(), ended_at=None))
            return path

    def complete(self, run_id):
        with self.lock, self.open_run(run_id) as fd:
            item = self.read_manifest(fd, run_id)
            item.update(completed=True, ended_at=utcnow())
            self.write_manifest(fd, item)

    def ids(self):
        with self.open_root() as root:
            result = []
            for name in os.listdir(root):
                if RUN_ID.fullmatch(name):
                    info = os.stat(name, dir_fd=root, follow_symlinks=False)
                    if stat.S_ISDIR(info.st_mode):
                        result.append(name)
            return sorted(result)

    @staticmethod
    def size_fd(fd, depth=0):
        if depth > 16:
            raise ValueError("recording nesting limit exceeded")
        total = 0
        for name in os.listdir(fd):
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISREG(info.st_mode):
                total += info.st_size
            elif stat.S_ISDIR(info.st_mode):
                child = os.open(name, DIR_FLAGS, dir_fd=fd)
                try:
                    total += RecordingStore.size_fd(child, depth + 1)
                finally:
                    os.close(child)
        return total

    def summaries(self, active=None):
        with self.lock:
            rows = []
            for run_id in reversed(self.ids()):
                try:
                    with self.open_run(run_id) as fd:
                        item = self.read_manifest(fd, run_id)
                        if not item["completed"] and run_id != active:
                            continue
                        rows.append(dict(id=run_id, completed=item["completed"],
                                         size_bytes=self.size_fd(fd), started_at=item["started_at"],
                                         ended_at=item["ended_at"],
                                         download_url=f"/api/recordings/{run_id}/download"))
                except (OSError, ValueError, RecursionError):
                    continue
            return rows

    def prune(self, protect=None):
        with self.lock:
            sizes, managed = {}, set()
            for run_id in self.ids():
                with self.open_run(run_id) as fd:
                    sizes[run_id] = self.size_fd(fd)
                    try:
                        self.read_manifest(fd, run_id)
                        managed.add(run_id)
                    except (ValueError, OSError):
                        pass
            for run_id in sorted(sizes):
                if len(sizes) <= self.max_runs and sum(sizes.values()) <= self.max_bytes:
                    break
                if run_id != protect and run_id in managed:
                    with self.open_root() as root:
                        shutil.rmtree(run_id, dir_fd=root)
                    del sizes[run_id]
            if sum(sizes.values()) > self.max_bytes or len(sizes) > self.max_runs:
                raise RuntimeError("active/unmanaged recording exceeded retention budget")


import signal
import subprocess
import sys


def terminate_group(process, grace=2):
    """Kill descendants even when the group leader has already exited."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        process.wait()
        return
    try:
        process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        pass
    # A leader exiting on TERM does not prove its descendants exited.
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            break
        time.sleep(min(.02, grace))
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=max(1, grace))


class FlightSupervisor:
    def __init__(self, state, recordings, command, stop, cwd="/opt/copper-flight",
                 startup_timeout=300, inactivity_timeout=30, poll_interval=.1,
                 terminate_grace=2, pause_seconds=2):
        self.state, self.recordings, self.stop = state, recordings, stop
        self.command = list(command)
        self.cwd = str(cwd)
        self.startup_timeout, self.inactivity_timeout = startup_timeout, inactivity_timeout
        self.poll_interval, self.terminate_grace, self.pause_seconds = poll_interval, terminate_grace, pause_seconds
        self.state.inactivity_timeout = inactivity_timeout

    def retain(self, active=None):
        try:
            self.recordings.prune(protect=active)
        finally:
            rows = self.recordings.summaries(active)
            with self.state.lock:
                self.state.data["recordings"] = rows

    def episode(self, run_id):
        run = self.recordings.begin(run_id)
        self.state.begin(run_id)
        self.retain(run_id)
        snapshot = self.state.snapshot()
        config = snapshot["configuration"]
        environment = dict(os.environ, FLIGHT_WORLD=config["world"], FLIGHT_INFERENCE=config["inference"],
                           FLIGHT_EPISODE_SECONDS=str(config["episode_seconds"]),
                           COPPER_FLIGHT_TELEMETRY=str(run / "telemetry.jsonl"),
                           COPPER_FLIGHT_LOG_DIR=str(run / "logs"))
        with self.recordings.open_run(run_id) as fd:
            provenance = dict(schema_version=1, recording_id=run_id,
                              recorded_by="copper-flight-supervisor",
                              engine=snapshot["engine"], configuration=config,
                              native_replay_verified=False)
            meta_fd = open_regular(fd, "provenance.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL)
            with os.fdopen(meta_fd, "wb") as metadata:
                metadata.write(json.dumps(provenance, allow_nan=False).encode())
                metadata.flush()
                os.fsync(metadata.fileno())
            raw = open_regular(fd, "telemetry.jsonl", os.O_RDWR | os.O_CREAT | os.O_EXCL)
            log_fd = open_regular(fd, "native.log", os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        with os.fdopen(raw, "rb", buffering=0) as stream, os.fdopen(log_fd, "wb") as log:
            reader = TelemetryReader(stream)
            process = subprocess.Popen(self.command, cwd=self.cwd, env=environment, stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            started = time.monotonic()
            first_at = last_progress = None
            seen_backend = seen_autonomy = seen_policy = False
            try:
                while True:
                    if self.stop.is_set():
                        raise InterruptedError("flight workload stopping")
                    for frame in reader.poll():
                        now = time.monotonic()
                        if first_at is None:
                            first_at = last_progress = now
                        if frame["world"] != config["world"]:
                            raise RuntimeError("native world does not match requested world")
                        backend = frame["inference_backend"]
                        if backend is not None and backend != config["inference"]:
                            raise RuntimeError("native inference backend does not match requested backend")
                        adapter = frame.get("graphics_adapter")
                        if isinstance(frame.get("graphics"), dict):
                            adapter = frame["graphics"].get("adapter_name")
                        if os.environ.get("FLIGHT_DISPLAY_MODE", "drm") != "software" and adapter and any(
                                marker in adapter.lower() for marker in ("llvmpipe", "lavapipe", "softpipe", "swiftshader", "software")):
                            raise RuntimeError("software graphics adapter rejected outside explicit software acceptance mode")
                        self.state.publish(frame)
                        if self.state.progress_at is not None:
                            last_progress = self.state.progress_at
                        seen_backend |= backend == config["inference"]
                        seen_autonomy |= frame["armed"] and frame["auto_enabled"]
                        seen_policy |= frame["policy_prediction_m_s"] is not None
                    self.retain(run_id)
                    code = process.poll()
                    if code is not None:
                        if code:
                            raise RuntimeError(f"native flight exited {code}; see {run_id}/native.log")
                        if reader.offset < os.fstat(stream.fileno()).st_size:
                            continue  # Drain bounded chunks after a clean fast exit before judging its final sample.
                        # Native must flush its final deadline sample before exiting cleanly.
                        if reader.buffer or reader.last is None or not self.state.advanced or \
                                reader.last["sim_time_s"] < config["episode_seconds"] or \
                                not seen_backend or not seen_autonomy or not seen_policy:
                            raise RuntimeError("incomplete native episode (final progress/backend/autonomy/policy output required)")
                        break
                    now = time.monotonic()
                    if first_at is None and now - started > self.startup_timeout:
                        raise TimeoutError("native startup deadline exceeded")
                    if last_progress is not None and now - last_progress > self.inactivity_timeout:
                        raise TimeoutError("native simulation inactivity deadline exceeded")
                    self.stop.wait(self.poll_interval)
            except InterruptedError:
                raise
            except Exception as error:
                self.state.fail(error)
                raise
            finally:
                terminate_group(process, self.terminate_grace)
        self.recordings.complete(run_id)
        self.retain()
        with self.state.lock:
            self.state.data["status"] = "between_episodes"

    def run(self):
        try:
            self.retain()
            while not self.stop.is_set():
                run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
                self.episode(run_id)
                self.stop.wait(self.pause_seconds)
            with self.state.lock:
                self.state.data["status"] = "stopped"
        except InterruptedError:
            with self.state.lock:
                self.state.data["status"] = "stopped"
        except Exception as error:
            self.state.fail(error)
            print(f"flight supervisor failed: {error}", file=sys.stderr, flush=True)
            self.stop.set()


import mimetypes
import tarfile
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

ARTIFACT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,240}\.copper(?:\.[0-9]+)?")
MAX_PLAYBACK_BYTES = 32 * 1024**2
MAX_PLAYBACK_FRAMES = 20000


class PlaybackIncomplete(ValueError):
    pass


class PlaybackTooLarge(ValueError):
    pass


def completed_telemetry(recordings, run_id):
    """Read genuine completed frames; visualization is not native replay verification."""
    check_id(run_id)
    with ExitStack() as stack:
        with recordings.lock, recordings.open_run(run_id) as fd:
            manifest = recordings.read_manifest(fd, run_id)
            if not manifest["completed"]:
                raise PlaybackIncomplete("recording is not completed")
            stream = stack.enter_context(os.fdopen(open_regular(fd, "telemetry.jsonl"), "rb"))
            size = os.fstat(stream.fileno()).st_size
            if size > MAX_PLAYBACK_BYTES:
                raise PlaybackTooLarge("telemetry playback byte limit exceeded")
            try:
                metadata = stack.enter_context(os.fdopen(open_regular(fd, "provenance.json"), "rb"))
            except FileNotFoundError:
                metadata = None
        # Pinned descriptors survive retention; parsing/network never holds its lock.
        payload = stream.read(MAX_PLAYBACK_BYTES + 1)
        if len(payload) > MAX_PLAYBACK_BYTES:
            raise PlaybackTooLarge("telemetry playback byte limit exceeded")
        if len(payload) != size or not payload or not payload.endswith(b"\n"):
            raise ValueError("incomplete or changed telemetry artifact")
        provenance = None
        if metadata is not None:
            provenance = bounded_json(metadata.read(MAX_JSON + 1))
            if (not isinstance(provenance, dict) or provenance.get("schema_version") != 1 or
                    provenance.get("recording_id") != run_id or
                    provenance.get("native_replay_verified") is not False):
                raise ValueError("invalid recording provenance")
    reader = TelemetryReader(io.BytesIO(payload))
    frames = []
    while reader.offset < len(payload):
        frames.extend(normalize_frame(frame) for frame in reader.poll())
        if len(frames) > MAX_PLAYBACK_FRAMES:
            raise PlaybackTooLarge("telemetry playback frame limit exceeded")
    if reader.buffer or not frames:
        raise ValueError("incomplete telemetry artifact")
    return dict(schema_version=1, recording=manifest, provenance=provenance,
                frames=frames, native_replay_verified=False)


@contextmanager
def snapshot_files(recordings, run_id):
    """Pin completed regular files under lock, release before disk/network IO."""
    streams, aliases = {}, {}
    def collect(fd, prefix=""):
        for name in sorted(os.listdir(fd)):
            if not (ARTIFACT.fullmatch(name) or (not prefix and name in {"telemetry.jsonl", "native.log", "manifest.json", "provenance.json"})):
                continue
            member = prefix + name
            try:
                raw = open_regular(fd, name)
            except (ValueError, OSError):
                if ARTIFACT.fullmatch(name):
                    try:
                        target = os.readlink(name, dir_fd=fd)
                        if "/" not in target and ARTIFACT.fullmatch(target):
                            aliases[member] = prefix + target
                    except OSError:
                        pass
                continue
            stream = os.fdopen(raw, "rb", buffering=0)
            streams[member] = (stream, os.fstat(raw).st_size)

    try:
        with recordings.lock, recordings.open_run(run_id) as fd:
            if not recordings.read_manifest(fd, run_id)["completed"]:
                raise ValueError("recording is not completed")
            collect(fd)
            try:
                logs = os.open("logs", DIR_FLAGS, dir_fd=fd)
            except FileNotFoundError:
                pass
            else:
                try:
                    collect(logs, "logs/")
                finally:
                    os.close(logs)
        yield streams, {name: target for name, target in aliases.items() if target in streams}
    finally:
        for stream, _ in streams.values():
            stream.close()


def archive_into(recordings, run_id, output):
    with snapshot_files(recordings, run_id) as (streams, aliases):
        with tarfile.open(fileobj=output, mode="w:gz") as tar:
            for name, (stream, size) in streams.items():
                info = tarfile.TarInfo(f"{run_id}/{name}")
                info.size, info.mode = size, 0o640
                tar.addfile(info, stream)
            for name, target in aliases.items():
                info = tarfile.TarInfo(f"{run_id}/{name}")
                info.type, info.linkname = tarfile.SYMTYPE, Path(target).name
                tar.addfile(info)


def stream_file(source, destination, size):
    remaining = size
    while remaining:
        data = source.read(min(65536, remaining))
        if not data:
            raise OSError("immutable artifact was truncated during streaming")
        destination.write(data)
        remaining -= len(data)


STATIC_SUFFIXES = {".html", ".js", ".css", ".svg", ".png", ".jpg", ".jpeg", ".webp", ".ico", ".woff", ".woff2", ".ttf"}


def static_inventory(root):
    allowed = set()
    if Path(root).is_symlink():
        raise ValueError("web root cannot be a symlink")
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [name for name in dirs if not name.startswith(".") and not (Path(directory) / name).is_symlink()]
        for name in files:
            if not name.startswith(".") and Path(name).suffix in STATIC_SUFFIXES:
                allowed.add((Path(directory) / name).relative_to(root).as_posix())
    return frozenset(allowed)


@contextmanager
def open_static(root, relative):
    parts = relative.split("/")
    if any(part in {"", ".", ".."} or "\0" in part for part in parts):
        raise ValueError("unsafe static path")
    fd = os.open(root, DIR_FLAGS)
    try:
        for part in parts[:-1]:
            child = os.open(part, DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child
        with os.fdopen(open_regular(fd, parts[-1]), "rb", buffering=0) as source:
            yield source
    finally:
        os.close(fd)


def make_server(state, recordings, web_root, host="0.0.0.0", port=8080, socket_timeout=5, asset_root=None):
    packaged_static = static_inventory(web_root)
    asset_root = Path(asset_root or os.environ.get("COPPER_FLIGHT_ASSET_DIR", str(Path(__file__).resolve().parent / "assets")))
    class Server(ThreadingHTTPServer):
        daemon_threads = True
        block_on_close = False

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(socket_timeout)

        def log_message(self, *_):
            pass

        def response_headers(self, code, content_type, size):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; "
                             "style-src 'self'; img-src 'self' blob: data:; connect-src 'self' blob:; "
                             "object-src 'none'; base-uri 'none'; frame-ancestors 'none'")

        def json_response(self, code, item):
            payload = json.dumps(item, allow_nan=False).encode()
            self.response_headers(code, "application/json; charset=utf-8", len(payload))
            self.end_headers()
            self.wfile.write(payload)

        def read_only(self):
            self.json_response(405, dict(error="read-only API; GET only"))

        do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_HEAD = read_only

        def do_GET(self):
            try:
                path = unquote(urlsplit(self.path).path, errors="strict")
                if path == "/api/state":
                    return self.json_response(200, state.snapshot())
                if path == "/api/telemetry":
                    query = parse_qs(urlsplit(self.path).query, keep_blank_values=True, strict_parsing=True)
                    after_seq = episode_id = None
                    if query:
                        if set(query) != {"after_seq", "episode_id"} or any(len(v) != 1 for v in query.values()):
                            raise ValueError("invalid telemetry cursor parameters")
                        cursor = query["after_seq"][0]
                        if not re.fullmatch(r"0|[1-9][0-9]{0,15}", cursor):
                            raise ValueError("invalid telemetry cursor")
                        after_seq, episode_id = int(cursor), query["episode_id"][0]
                        check_id(episode_id)
                    return self.json_response(200, state.telemetry_snapshot(after_seq, episode_id))
                if path == "/healthz":
                    healthy = state.ready()
                    return self.json_response(200 if healthy else 503,
                                              dict(ok=healthy, status=state.snapshot()["status"]))
                if path.startswith("/api/scene/"):
                    allowed = {"/api/scene/forest.glb": "forest.glb",
                               "/api/scene/quadcopter.glb": "quadcopter.glb"}
                    if path not in allowed or path != urlsplit(self.path).path:
                        return self.json_response(404, dict(error="not found"))
                    root = os.open(asset_root, DIR_FLAGS)
                    try:
                        raw = open_regular(root, allowed[path])
                    finally:
                        os.close(root)
                    with os.fdopen(raw, "rb", buffering=0) as source:
                        size = os.fstat(source.fileno()).st_size
                        self.response_headers(200, "model/gltf-binary", size)
                        self.end_headers()
                        try:
                            stream_file(source, self.wfile, size)
                        except OSError:
                            self.close_connection = True
                    return
                if path.startswith("/api/recordings/") and path.endswith("/telemetry"):
                    run_id = path.removeprefix("/api/recordings/").removesuffix("/telemetry")
                    check_id(run_id)
                    if not recordings.playback_slot.acquire(blocking=False):
                        return self.json_response(429, dict(error="telemetry readers busy"))
                    try:
                        try:
                            bundle = completed_telemetry(recordings, run_id)
                        except PlaybackIncomplete as error:
                            return self.json_response(409, dict(error=str(error)))
                        except PlaybackTooLarge as error:
                            return self.json_response(413, dict(error=str(error)))
                        except FileNotFoundError:
                            raise
                        except (ValueError, OSError):
                            return self.json_response(400, dict(error="invalid telemetry artifact"))
                        return self.json_response(200, bundle)
                    finally:
                        recordings.playback_slot.release()
                if path.startswith("/api/recordings/") and path.endswith("/download"):
                    run_id = path.removeprefix("/api/recordings/").removesuffix("/download")
                    check_id(run_id)
                    if not recordings.download_slot.acquire(blocking=False):
                        return self.json_response(429, dict(error="another archive is in progress"))
                    try:
                        # Unlinked snapshot; no recording lock is held during compression/upload.
                        with tempfile.TemporaryFile(dir=recordings.root.parent) as output:
                            archive_into(recordings, run_id, output)
                            size = output.tell()
                            output.seek(0)
                            self.response_headers(200, "application/gzip", size)
                            self.send_header("Content-Disposition", f'attachment; filename="{run_id}.tar.gz"')
                            self.end_headers()
                            shutil.copyfileobj(output, self.wfile, length=65536)
                    finally:
                        recordings.download_slot.release()
                    return
                name = "index.html" if path == "/" else path.removeprefix("/")
                if name not in packaged_static:
                    return self.json_response(404, dict(error="not found"))
                try:
                    with open_static(web_root, name) as source:
                        size = os.fstat(source.fileno()).st_size
                        self.response_headers(200, mimetypes.guess_type(name)[0] or "application/octet-stream", size)
                        self.end_headers()
                        try:
                            stream_file(source, self.wfile, size)
                        except OSError:
                            self.close_connection = True
                except FileNotFoundError:
                    raise
                except (ValueError, OSError) as error:
                    raise ValueError("unsafe web artifact") from error
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                pass
            except FileNotFoundError:
                self.json_response(404, dict(error="not found"))
            except (ValueError, UnicodeError):
                self.json_response(400, dict(error="invalid or unsafe resource"))
            except OSError:
                self.json_response(400, dict(error="resource cannot be opened safely"))

    return Server((host, port), Handler)


APP_ROOT = Path(__file__).resolve().parent


def configuration(env):
    def bounded(key, default, minimum, maximum, integer=False):
        try:
            value = int(env.get(key, default)) if integer else float(env.get(key, default))
        except (ValueError, TypeError) as error:
            raise ValueError(f"invalid {key}") from error
        if not math.isfinite(value) or not minimum <= value <= maximum:
            raise ValueError(f"{key} must be {minimum}..{maximum}")
        return value
    world, inference = env.get("FLIGHT_WORLD", "forest"), env.get("FLIGHT_INFERENCE", "cpu")
    if world not in {"forest", "urban"} or inference not in {"cpu", "cuda"}:
        raise ValueError("invalid FLIGHT_WORLD or FLIGHT_INFERENCE")
    return dict(world=world, inference=inference,
                episode_seconds=bounded("FLIGHT_EPISODE_SECONDS", 45, 4.01, 3600),
                startup_timeout=bounded("FLIGHT_STARTUP_TIMEOUT_SECONDS", 300, .1, 300),
                inactivity_timeout=bounded("FLIGHT_INACTIVITY_TIMEOUT_SECONDS", 30, .1, 30),
                pause_seconds=bounded("FLIGHT_PAUSE_SECONDS", 2, .1, 30),
                max_runs=bounded("FLIGHT_KEEP_RUNS", 2, 1, 16, True),
                max_bytes=bounded("FLIGHT_MAX_BYTES", 4 * 1024**3, 1024**2, 64 * 1024**3, True),
                port=bounded("PORT", 8080, 0, 65535, True))


def main():
    config = configuration(os.environ)
    data = Path(os.environ.get("FLIGHT_DATA_DIR", "/data/copper-flight"))
    if not data.is_absolute():
        raise ValueError("FLIGHT_DATA_DIR must be absolute")
    recordings = RecordingStore(data / "runs", config["max_runs"], config["max_bytes"])
    state = StateStore(revision=os.environ.get("IMAGE_REVISION", "unknown"), world=config["world"],
                       inference=config["inference"], episode_seconds=config["episode_seconds"],
                       inactivity_timeout=config["inactivity_timeout"])
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    launcher = os.environ.get("COPPER_FLIGHT_LAUNCHER", str(APP_ROOT / "scripts/run-native-flight"))
    if not Path(launcher).is_absolute():
        raise ValueError("native launcher must be absolute")
    supervisor = FlightSupervisor(state, recordings, [launcher], stop, cwd=APP_ROOT,
                                  startup_timeout=config["startup_timeout"], inactivity_timeout=config["inactivity_timeout"],
                                  pause_seconds=config["pause_seconds"])
    server = make_server(state, recordings, APP_ROOT / "www", port=config["port"])
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    print(f"flight read-only API listening on {server.server_address}; recordings={recordings.root}", flush=True)
    try:
        supervisor.run()
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
    return 1 if state.snapshot()["status"] == "failed" else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(f"flight service failed: {error}", file=sys.stderr, flush=True)
        sys.exit(1)
