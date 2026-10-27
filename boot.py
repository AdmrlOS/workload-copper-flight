#!/usr/bin/env python3
"""Confined root init and display/service process supervision; no root HTTP."""
import os
from pathlib import Path
import sys

APP_ROOT = Path(__file__).resolve().parent
UID = GID = 10001
VIDEO_GID = 28
DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def data_components(request):
    parts = request.split("/")
    if parts[:3] != ["", "data", "copper-flight"] or any(
            p in {"", ".", ".."} or "\0" in p for p in parts[2:]):
        raise ValueError("FLIGHT_DATA_DIR must be /data/copper-flight or its confined child")
    return parts[2:]


def open_child(parent, name, mode=0o750):
    created = False
    try:
        os.mkdir(name, mode=mode, dir_fd=parent)
        created = True
    except FileExistsError:
        pass
    child = os.open(name, DIRECTORY_FLAGS, dir_fd=parent)
    if created:
        os.fchmod(child, mode)
    return child


def prepare_data(request="/data/copper-flight", root="/data"):
    parts = data_components(request)
    current = os.open(root, DIRECTORY_FLAGS)
    try:
        for index, name in enumerate(parts):
            child = open_child(current, name, 0o755 if index < len(parts) - 1 else 0o750)
            os.close(current)
            current = child
        runs = open_child(current, "runs")
        try:
            if os.geteuid() == 0:
                os.fchown(current, UID, GID)
                os.fchown(runs, UID, GID)
            os.fchmod(current, 0o750)
            os.fchmod(runs, 0o750)
        finally:
            os.close(runs)
    finally:
        os.close(current)


def prepare_runtime(root="/run", owner=0):
    parent = os.open(root, DIRECTORY_FLAGS)
    try:
        app = open_child(parent, "copper-flight", 0o711)
        try:
            # Reclaim only these directory inodes, never existing child trees.
            if os.geteuid() == 0:
                os.fchown(app, 0, 0)
            os.fchmod(app, 0o711)
            xdg = open_child(app, "xdg", 0o700)
            try:
                os.fchmod(xdg, 0o700)
                if os.geteuid() == 0:
                    os.fchown(xdg, owner, owner)
            finally:
                os.close(xdg)
        finally:
            os.close(app)
    finally:
        os.close(parent)
    return Path(root) / "copper-flight/xdg"


def service_command():
    return ["setpriv", "--reuid=10001", "--regid=10001", "--groups=28", "--no-new-privs",
            sys.executable, str(APP_ROOT / "service.py")]


import signal
import threading
from runtime.display import display_plan, supervise_children


def main():
    if os.geteuid() != 0:
        raise RuntimeError("start-flight requires root only for confined init/display; service is dropped to UID 10001")
    os.umask(0o027)
    data_dir = os.environ.get("FLIGHT_DATA_DIR", "/data/copper-flight")
    prepare_data(data_dir)
    mode = os.environ.get("FLIGHT_DISPLAY_MODE", "drm")
    surface_free = mode in {"headless", "software"}
    runtime = prepare_runtime(owner=UID if surface_free else 0)
    socket_name = None if surface_free else "wayland-flight-" + str(os.getpid())
    command, environment = display_plan(os.environ, runtime, socket_name)
    if surface_free:
        # No display process needs a privileged parent. Replace root init with
        # the service under setpriv; its existing watchdog owns native children.
        os.chdir(APP_ROOT)
        service = service_command()
        return os.execvpe(service[0], service, environment)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    return supervise_children(command, service_command(), environment, runtime, socket_name,
                              Path(data_dir) / "display.log", stop, cwd=APP_ROOT)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(f"flight boot/display failed: {error}", file=sys.stderr, flush=True)
        sys.exit(1)
