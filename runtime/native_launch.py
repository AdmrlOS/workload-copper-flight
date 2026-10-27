"""Fail-closed offline native launcher; installed paths never depend on cwd."""
import math
import os
from pathlib import Path
import sys

APP_ROOT = Path(__file__).resolve().parents[1]


def main():
    env = dict(os.environ)
    env.setdefault("FLIGHT_WORLD", "forest")
    env.setdefault("FLIGHT_INFERENCE", "cpu")
    env.setdefault("FLIGHT_EPISODE_SECONDS", "45")
    if env["FLIGHT_WORLD"] not in {"forest", "urban"} or env["FLIGHT_INFERENCE"] not in {"cpu", "cuda"}:
        raise ValueError("invalid native world/inference selection")
    seconds = float(env["FLIGHT_EPISODE_SECONDS"])
    if not math.isfinite(seconds) or not 4 < seconds <= 3600:
        raise ValueError("native episode seconds must be finite, >4 and <=3600")
    env.setdefault("COPPER_FLIGHT_ASSET_DIR", str(APP_ROOT / "assets"))
    env.setdefault("COPPER_FLIGHT_MODEL", str(APP_ROOT / "models/vitfly-vitlstm-f32.safetensors"))
    assets, model = Path(env["COPPER_FLIGHT_ASSET_DIR"]), Path(env["COPPER_FLIGHT_MODEL"])
    if not assets.is_absolute() or not assets.is_dir():
        raise ValueError("offline assets directory missing; downloads are not permitted")
    if not model.is_absolute() or not model.is_file() or model.stat().st_size == 0:
        raise ValueError("offline model missing; downloads are not permitted")
    for key in ("COPPER_FLIGHT_LOG_DIR", "COPPER_FLIGHT_TELEMETRY"):
        if not env.get(key) or not Path(env[key]).is_absolute():
            raise ValueError(f"{key} must be an absolute active-run path")
    mode = env.get("FLIGHT_DISPLAY_MODE", "drm")
    if mode not in {"drm", "headless", "software", "existing"}:
        raise ValueError("invalid FLIGHT_DISPLAY_MODE")
    if mode != "software" and env.get("LIBGL_ALWAYS_SOFTWARE", "0").lower() not in {"0", "false", ""}:
        raise ValueError("software rendering requires explicit software acceptance mode")
    if mode in {"headless", "software"}:
        for key in ("DISPLAY", "WAYLAND_DISPLAY", "WAYLAND_SOCKET", "WINIT_UNIX_BACKEND"):
            env.pop(key, None)
    else:
        if not env.get("WAYLAND_DISPLAY") and not (mode == "existing" and env.get("DISPLAY")):
            raise ValueError("native renderer requires supervised Wayland or explicitly configured existing display")
        env["WINIT_UNIX_BACKEND"] = "wayland" if env.get("WAYLAND_DISPLAY") else "x11"
    if mode == "software":
        from runtime.display import configure_software
        configure_software(env)
    env["WGPU_BACKEND"] = "vulkan"
    binary = env.get("COPPER_FLIGHT_NATIVE_BINARY", str(APP_ROOT / "bin/quad-sim"))
    if not Path(binary).is_absolute():
        raise ValueError("native executable must be absolute")
    os.chdir(APP_ROOT)
    os.execve(binary, [binary], env)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        print(f"native flight launch failed: {error}", file=sys.stderr, flush=True)
        sys.exit(1)
