"""Explicit display plans and bounded supervision. No software fallback."""
import os
from pathlib import Path
import stat
import subprocess
import sys
import threading
import time

from service import DIR_FLAGS, absolute_directory, open_regular, terminate_group


def configure_software(env):
    paths = env.get("VK_ICD_FILENAMES", "").split(":")
    if not all(p and Path(p).is_absolute() and Path(p).is_file() for p in paths):
        raise ValueError("software acceptance requires explicit VK_ICD_FILENAMES pointing to installed software Vulkan ICD")
    env["LIBGL_ALWAYS_SOFTWARE"] = "1"
    env.setdefault("WGPU_SETTINGS_PRIO", "webgpu")
    # The new loader variable takes precedence over the legacy one. Override
    # the CUDA image default too, rather than accidentally selecting NVIDIA.
    env["VK_DRIVER_FILES"] = env["VK_ICD_FILENAMES"]


def display_plan(environment, runtime_dir, socket_name, drm_root=Path("/sys/class/drm")):
    env = dict(environment)
    mode = env.get("FLIGHT_DISPLAY_MODE", "drm")
    if mode == "existing":
        if env.get("WAYLAND_DISPLAY"):
            runtime = env.get("XDG_RUNTIME_DIR")
            if not runtime or not Path(runtime).is_absolute():
                raise ValueError("existing Wayland requires absolute XDG_RUNTIME_DIR")
            fd = os.open(runtime, DIR_FLAGS)
            try:
                name = env["WAYLAND_DISPLAY"]
                if "/" in name or name in {".", ".."}:
                    raise ValueError("existing Wayland requires a socket basename")
                if not stat.S_ISSOCK(os.stat(name, dir_fd=fd, follow_symlinks=False).st_mode):
                    raise ValueError("existing Wayland socket is unavailable")
            finally:
                os.close(fd)
        elif not env.get("DISPLAY"):
            raise ValueError("existing display requires explicit WAYLAND_DISPLAY or DISPLAY")
        return None, env
    if mode not in {"drm", "headless", "software"}:
        raise ValueError("FLIGHT_DISPLAY_MODE must be drm, headless, software, or existing")
    if mode != "software" and env.get("LIBGL_ALWAYS_SOFTWARE", "0").lower() not in {"0", "false", ""}:
        raise ValueError("software rendering requires explicit FLIGHT_DISPLAY_MODE=software")
    if mode == "drm":
        connected = [p for p in Path(drm_root).glob("card*-*/status")
                     if p.read_text().strip() == "connected"]
        if not connected:
            raise RuntimeError("no connected DRM connector; cannot start DRM display (CUDA/device presence is not display support)")
    if mode == "software":
        configure_software(env)
    if mode in {"headless", "software"}:
        env["XDG_RUNTIME_DIR"] = str(runtime_dir)
        for key in ("DISPLAY", "WAYLAND_DISPLAY", "WAYLAND_SOCKET", "WINIT_UNIX_BACKEND"):
            env.pop(key, None)
        return None, env
    env.update(XDG_RUNTIME_DIR=str(runtime_dir), WAYLAND_DISPLAY=socket_name)
    env.pop("DISPLAY", None)
    env.pop("WAYLAND_SOCKET", None)
    env.setdefault("LIBSEAT_BACKEND", "builtin")
    command = ["setpriv", "--no-new-privs", "weston", "--no-config",
               "--backend=drm", "--renderer=gl",
               "--shell=kiosk-shell.so", "--socket=" + socket_name, "--idle-time=0"]
    return command, env


def grant_runtime(runtime_dir, socket_name):
    fd = os.open(runtime_dir, DIR_FLAGS)
    try:
        info = os.stat(socket_name, dir_fd=fd, follow_symlinks=False)
        if not stat.S_ISSOCK(info.st_mode):
            raise RuntimeError("compositor did not create a real Wayland socket")
        if os.geteuid() == 0:
            owner = os.fstat(fd).st_uid
            if owner == 0:
                # Only DRM starts in a root-owned 0700 directory. Its child names
                # are not writable by the application before this transfer.
                os.chown(socket_name, 10001, 10001, dir_fd=fd, follow_symlinks=False)
                os.fchown(fd, 10001, 10001)
            elif owner != 10001 or info.st_uid != 10001:
                raise RuntimeError("unexpected ownership of compositor runtime/socket")
        os.fchmod(fd, 0o700)
    finally:
        os.close(fd)


def pump_display(source, destination, limit=8 * 1024**2):
    written = 0
    try:
        while True:
            chunk = source.read(8192)
            if not chunk:
                break
            if written + len(chunk) > limit:
                destination.seek(0)
                destination.truncate()
                written = 0
            destination.write(chunk)
            destination.flush()
            written += len(chunk)
            # Admiral captures stderr as well as the confined bounded file.
            try:
                sys.stderr.buffer.write(chunk)
                sys.stderr.buffer.flush()
            except (AttributeError, OSError):
                pass
    finally:
        source.close()


def supervise_children(display_command, service_command, environment, runtime_dir, socket_name,
                       log_path, stop, cwd, startup_timeout=30, terminate_grace=2):
    display = service = None
    pump = None
    log = None
    try:
        if display_command is not None:
            with absolute_directory(Path(log_path).parent) as parent:
                fd = open_regular(parent, Path(log_path).name, os.O_WRONLY | os.O_CREAT)
                os.ftruncate(fd, 0)
                log = os.fdopen(fd, "wb", buffering=0)
            display = subprocess.Popen(display_command, env=environment, cwd=cwd,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
            pump = threading.Thread(target=pump_display, args=(display.stdout, log), daemon=True)
            pump.start()
            deadline = time.monotonic() + startup_timeout
            while True:
                if stop.is_set():
                    return 0
                code = display.poll()
                if code is not None:
                    raise RuntimeError(f"display exited {code} during startup; see {log_path}")
                try:
                    info = os.stat(Path(runtime_dir) / socket_name, follow_symlinks=False)
                    if stat.S_ISSOCK(info.st_mode):
                        break
                    raise RuntimeError("unsafe compositor socket")
                except FileNotFoundError:
                    pass
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"display startup deadline exceeded; see {log_path}")
                stop.wait(.02)
            grant_runtime(runtime_dir, socket_name)
        service = subprocess.Popen(service_command, cwd=cwd, env=environment, stdin=subprocess.DEVNULL,
                                   start_new_session=True)
        while not stop.is_set():
            if display is not None and display.poll() is not None:
                raise RuntimeError(f"display exited {display.returncode}; see {log_path}")
            code = service.poll()
            if code is not None:
                return code
            stop.wait(.05)
        return 0
    finally:
        if service is not None:
            terminate_group(service, terminate_grace)
        if display is not None:
            terminate_group(display, terminate_grace)
        if pump is not None:
            pump.join(timeout=terminate_grace + 1)
        if log is not None:
            log.close()
