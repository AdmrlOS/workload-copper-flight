import importlib.util
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class BootTests(unittest.TestCase):
    def load(self):
        path = ROOT / "boot.py"
        self.assertTrue(path.is_file(), "safe boot helper missing")
        spec = importlib.util.spec_from_file_location("flight_boot", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_only_confined_leaves_are_changed_without_following_symlinks(self):
        boot = self.load()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "runs").mkdir()
            (root / "runs" / "old-rover").write_text("untouched")
            for bad in ["/data", "/data/runs", "/etc", "/data/copper-flight/../runs",
                        "/data//copper-flight", "/data/copper-flight/."]:
                with self.assertRaises(ValueError):
                    boot.prepare_data(bad, root=root)
            owned = []
            with patch("os.geteuid", return_value=0), patch("os.fchown", side_effect=lambda fd, uid, gid:
                    owned.append((os.fstat(fd).st_ino, uid, gid))):
                boot.prepare_data("/data/copper-flight", root=root)
            self.assertEqual(owned, [(os.stat(root / "copper-flight").st_ino, 10001, 10001),
                                     (os.stat(root / "copper-flight/runs").st_ino, 10001, 10001)])
            self.assertEqual((root / "runs/old-rover").read_text(), "untouched")
            outside = root / "outside"
            outside.mkdir()
            (root / "copper-flight" / "nested").symlink_to(outside, target_is_directory=True)
            with patch("os.fchown") as chown, self.assertRaises(OSError):
                boot.prepare_data("/data/copper-flight/nested", root=root)
            chown.assert_not_called()

    def test_existing_data_modes_are_reclaimed_only_on_pinned_directory_leaves(self):
        boot = self.load()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "copper-flight"
            runs = data / "runs"
            runs.mkdir(parents=True)
            data.chmod(0o777)
            runs.chmod(0o777)
            old = runs / "unmanaged-user-tree"
            old.mkdir(mode=0o755)
            sentinel = old / "untouched"
            sentinel.write_text("do not modify descendants")
            before = (old.stat(), sentinel.stat())
            owned = []
            with patch("os.geteuid", return_value=0), patch("os.fchown", side_effect=lambda fd, uid, gid:
                    owned.append((os.fstat(fd).st_ino, uid, gid))):
                boot.prepare_data(root=root)
            self.assertEqual(data.stat().st_mode & 0o777, 0o750)
            self.assertEqual(runs.stat().st_mode & 0o777, 0o750)
            self.assertEqual(owned, [(data.stat().st_ino, 10001, 10001),
                                     (runs.stat().st_ino, 10001, 10001)])
            for path, prior in zip((old, sentinel), before):
                self.assertEqual((path.stat().st_uid, path.stat().st_gid, path.stat().st_mode),
                                 (prior.st_uid, prior.st_gid, prior.st_mode))

    def test_runtime_refuses_symlinked_directory_components(self):
        boot = self.load()
        for leaf in ("copper-flight", "copper-flight/xdg"):
            with self.subTest(leaf=leaf), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                outside = root / "outside"
                outside.mkdir(mode=0o755)
                before = outside.stat()
                target = root / leaf
                target.parent.mkdir(exist_ok=True)
                target.symlink_to(outside, target_is_directory=True)
                owned = []
                with self.assertRaises(OSError), patch("os.fchown", side_effect=lambda fd, uid, gid:
                        owned.append(os.fstat(fd).st_ino)):
                    boot.prepare_runtime(root, owner=10001)
                self.assertEqual(outside.stat().st_mode, before.st_mode)
                self.assertNotIn(outside.stat().st_ino, owned)

    def test_launch_entrypoint_calls_confined_boot_and_propagates_child_failure(self):
        boot = self.load()
        wrapper = ROOT / "scripts/start-flight"
        self.assertTrue(wrapper.is_file(), "root entrypoint missing")
        with tempfile.TemporaryDirectory() as tmp:
            xdg = Path(tmp) / "xdg"
            env = dict(FLIGHT_DATA_DIR="/data/copper-flight", FLIGHT_DISPLAY_MODE="existing", DISPLAY=":1")
            with patch.dict(os.environ, env, clear=True), patch("os.geteuid", return_value=0), \
                    patch.object(boot, "prepare_data") as data, \
                    patch.object(boot, "prepare_runtime", return_value=xdg), \
                    patch.object(boot, "supervise_children", return_value=9) as supervise:
                self.assertEqual(boot.main(), 9)
            data.assert_called_once_with("/data/copper-flight")
            self.assertEqual(supervise.call_args.kwargs["cwd"], ROOT)
            self.assertIsNone(supervise.call_args.args[0])
        self.assertIn("boot.py", wrapper.read_text())

    def test_secure_runtime_and_explicit_service_privilege_contract(self):
        boot = self.load()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("os.geteuid", return_value=0), patch("os.fchown"):
                boot.prepare_runtime(root)
            self.assertEqual((root / "copper-flight/xdg").stat().st_mode & 0o777, 0o700)
            self.assertEqual(boot.service_command(), ["setpriv", "--reuid=10001", "--regid=10001",
                "--groups=28", "--no-new-privs", sys.executable, str(ROOT / "service.py")])


class DisplayTests(unittest.TestCase):
    def test_display_log_rejects_ancestor_replaced_after_boot_validation(self):
        from runtime.display import supervise_children
        boot = BootTests().load()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            # Filesystem attack fixture, not native runtime or hardware evidence.
            boot.prepare_data("/data/copper-flight/a/b", root=root)
            ancestor = root / "copper-flight/a"
            outside = root / "outside"
            (outside / "b").mkdir(parents=True)
            sentinel = outside / "b/display.log"
            sentinel.write_text("TEST OUTSIDE SENTINEL: do not truncate")
            ancestor.rename(ancestor.with_name("a-before-swap"))
            ancestor.symlink_to(outside, target_is_directory=True)
            with patch("runtime.display.subprocess.Popen", side_effect=OSError("TEST child launch")) as launch:
                with self.assertRaises(OSError):
                    supervise_children(["TEST compositor"], ["TEST service"], {}, root, "wayland-test",
                                       ancestor / "b/display.log", threading.Event(), cwd=ROOT)
            self.assertEqual(sentinel.read_text(), "TEST OUTSIDE SENTINEL: do not truncate")
            launch.assert_not_called()

    def test_grant_runtime_never_uses_path_based_chmod_on_a_socket_leaf(self):
        from runtime.display import grant_runtime
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            server = socket.socket(socket.AF_UNIX)
            server.bind(str(path / "wayland-test"))
            try:
                with patch("os.chmod", side_effect=AssertionError("path-based chmod may follow a swapped symlink")):
                    grant_runtime(path, "wayland-test")
            finally:
                server.close()

    def test_surface_free_modes_have_no_compositor_or_inherited_display_backend(self):
        from runtime.display import display_plan
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            icd = root / "lvp.json"
            icd.write_text("{}")
            for mode in ("headless", "software"):
                for stale in (False, True):
                    with self.subTest(mode=mode, stale=stale):
                        inherited = dict(FLIGHT_DISPLAY_MODE=mode, VK_ICD_FILENAMES=str(icd),
                                         VK_DRIVER_FILES="/etc/vulkan/icd.d/nvidia_icd.json")
                        if stale:
                            inherited.update(DISPLAY=":stale", WAYLAND_DISPLAY="wayland-stale",
                                             WAYLAND_SOCKET="99", WINIT_UNIX_BACKEND="x11")
                        command, env = display_plan(inherited, root, "unused-no-socket")
                        self.assertIsNone(command)
                        self.assertEqual(env["XDG_RUNTIME_DIR"], str(root))
                        for key in ("DISPLAY", "WAYLAND_DISPLAY", "WAYLAND_SOCKET", "WINIT_UNIX_BACKEND"):
                            self.assertNotIn(key, env)
                        if mode == "software":
                            self.assertEqual(env["VK_ICD_FILENAMES"], str(icd))
                            self.assertEqual(env["VK_DRIVER_FILES"], str(icd))
                            self.assertEqual(env["LIBGL_ALWAYS_SOFTWARE"], "1")
                            self.assertEqual(env["WGPU_SETTINGS_PRIO"], "webgpu")
                        else:
                            self.assertEqual(env["VK_DRIVER_FILES"], inherited["VK_DRIVER_FILES"])
                            self.assertNotIn("LIBGL_ALWAYS_SOFTWARE", env)
                            self.assertNotIn("WGPU_SETTINGS_PRIO", env)

    def test_surface_free_runtime_leaf_matches_service_uid(self):
        boot = BootTests().load()
        with tempfile.TemporaryDirectory() as tmp:
            owned = []
            with patch("os.geteuid", return_value=0), patch("os.fchown", side_effect=lambda fd, uid, gid:
                    owned.append((uid, gid))):
                boot.prepare_runtime(Path(tmp), owner=10001)
            self.assertEqual(owned, [(0, 0), (10001, 10001)])
            self.assertEqual((Path(tmp) / "copper-flight/xdg").stat().st_mode & 0o777, 0o700)

    def test_default_drm_requires_a_connector_and_never_chooses_software(self):
        from runtime.display import display_plan
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(RuntimeError, "connected DRM connector"):
                display_plan({}, root, "wayland-test", drm_root=root / "drm")
            connector = root / "drm/card0-HDMI-A-1"
            connector.mkdir(parents=True)
            (connector / "status").write_text("connected\n")
            command, env = display_plan({}, root, "wayland-test", drm_root=root / "drm")
            self.assertIn("--backend=drm", command)
            self.assertIn("--renderer=gl", command)
            self.assertNotIn("--renderer=pixman", command)
            self.assertEqual(env["LIBSEAT_BACKEND"], "builtin")
            with self.assertRaises(ValueError):
                display_plan({"FLIGHT_DISPLAY_MODE": "software"}, root, "wayland-test")
            icd = root / "lvp.json"
            icd.write_text("{}")
            command, env = display_plan({"FLIGHT_DISPLAY_MODE": "software", "VK_ICD_FILENAMES": str(icd)},
                                        root, "wayland-test")
            self.assertIsNone(command)
            self.assertEqual(env["LIBGL_ALWAYS_SOFTWARE"], "1")
            self.assertEqual(env["WGPU_SETTINGS_PRIO"], "webgpu")
            _, override = display_plan({"FLIGHT_DISPLAY_MODE": "software", "VK_ICD_FILENAMES": str(icd),
                                        "WGPU_SETTINGS_PRIO": "functionality"}, root, "wayland-test")
            self.assertEqual(override["WGPU_SETTINGS_PRIO"], "functionality")
            self.assertIsNone(display_plan({"FLIGHT_DISPLAY_MODE": "existing", "DISPLAY": ":1"},
                                           root, "unused")[0])
            with self.assertRaises(ValueError):
                display_plan({"FLIGHT_DISPLAY_MODE": "existing"}, root, "unused")

    def test_real_display_failure_kills_service_and_retains_clear_stderr(self):
        from runtime.display import supervise_children
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            xdg = root / "xdg"
            xdg.mkdir(mode=0o700)
            sock = str(xdg / "wayland-test")
            display = [sys.executable, "-c", "import socket,time,sys; s=socket.socket(socket.AF_UNIX); "
                       f"s.bind({sock!r}); s.listen(); time.sleep(.3); "
                       "sys.stderr.write('TEST EGL unavailable\\n'); sys.stderr.flush(); sys.exit(7)"]
            pidfile = root / "service-pid"
            service = [sys.executable, "-c", "import os,pathlib,time; "
                       f"pathlib.Path({str(pidfile)!r}).write_text(str(os.getpid())); time.sleep(30)"]
            with self.assertRaisesRegex(RuntimeError, "display exited 7"):
                supervise_children(display, service, dict(os.environ), xdg, "wayland-test",
                                   root / "display.log", threading.Event(), cwd=ROOT,
                                   startup_timeout=1, terminate_grace=.1)
            self.assertIn("TEST EGL unavailable", (root / "display.log").read_text())
            with self.assertRaises(ProcessLookupError):
                os.kill(int(pidfile.read_text()), 0)

    def test_executable_native_wrapper_surface_free_modes_need_no_display(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assets, model = root / "assets", root / "model"
            assets.mkdir()
            model.write_bytes(b"TEST fixture; not policy evidence")
            engine, report = root / "inspect-engine", root / "report"
            engine.write_text(f"#!{sys.executable}\nimport os,json,pathlib\n" +
                f"pathlib.Path({str(report)!r}).write_text(json.dumps(dict(cwd=os.getcwd(),env=dict(os.environ))))\n")
            engine.chmod(0o755)
            icd = root / "lvp.json"
            icd.write_text("{}")
            for mode in ("headless", "software"):
                for stale in (False, True):
                    with self.subTest(mode=mode, stale=stale):
                        env = dict(PATH=os.environ.get("PATH", os.defpath),
                                   FLIGHT_DISPLAY_MODE=mode, FLIGHT_INFERENCE="cpu",
                                   COPPER_FLIGHT_NATIVE_BINARY=str(engine), COPPER_FLIGHT_ASSET_DIR=str(assets),
                                   COPPER_FLIGHT_MODEL=str(model), COPPER_FLIGHT_LOG_DIR=str(root),
                                   COPPER_FLIGHT_TELEMETRY=str(root / "telemetry.jsonl"),
                                   VK_ICD_FILENAMES=str(icd), VK_DRIVER_FILES="/etc/vulkan/icd.d/nvidia_icd.json")
                        for key in ("DISPLAY", "WAYLAND_DISPLAY", "WAYLAND_SOCKET", "WINIT_UNIX_BACKEND",
                                    "LIBGL_ALWAYS_SOFTWARE", "WGPU_SETTINGS_PRIO"):
                            env.pop(key, None)
                        if stale:
                            env.update(DISPLAY=":stale", WAYLAND_DISPLAY="wayland-stale",
                                       WAYLAND_SOCKET="99", WINIT_UNIX_BACKEND="x11")
                        result = subprocess.run([str(ROOT / "scripts/run-native-flight")], cwd=root, env=env,
                                                capture_output=True, text=True, timeout=5)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        observed = json.loads(report.read_text())
                        self.assertEqual(observed["cwd"], str(ROOT))
                        launched = observed["env"]
                        for key in ("DISPLAY", "WAYLAND_DISPLAY", "WAYLAND_SOCKET", "WINIT_UNIX_BACKEND"):
                            self.assertNotIn(key, launched)
                        self.assertEqual(launched["WGPU_BACKEND"], "vulkan")
                        if mode == "software":
                            self.assertEqual(launched["WGPU_SETTINGS_PRIO"], "webgpu")
                            self.assertEqual(launched["VK_DRIVER_FILES"], str(icd))
                            self.assertEqual(launched["LIBGL_ALWAYS_SOFTWARE"], "1")
                        else:
                            self.assertNotIn("WGPU_SETTINGS_PRIO", launched)
                            self.assertNotIn("LIBGL_ALWAYS_SOFTWARE", launched)
                            self.assertEqual(launched["VK_DRIVER_FILES"], env["VK_DRIVER_FILES"])

    def test_executable_native_wrapper_requires_offline_assets_and_fixed_cwd(self):
        wrapper = ROOT / "scripts/run-native-flight"
        self.assertTrue(wrapper.is_file(), "native executable wrapper missing")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assets, model = root / "assets", root / "model"
            assets.mkdir()
            model.write_bytes(b"TEST fixture; engine itself validates actual weights")
            engine = root / "inspect-engine"
            report = root / "report"
            engine.write_text(f"#!{sys.executable}\nimport os,json,pathlib\n" +
                f"pathlib.Path({str(report)!r}).write_text(json.dumps(dict(cwd=os.getcwd(),env=dict(os.environ))))\n")
            engine.chmod(0o755)
            shadow = root / "shadow/runtime"
            shadow.mkdir(parents=True)
            (shadow / "__init__.py").write_text("raise RuntimeError('TEST foreign runtime namespace must not win')\n")
            env = dict(os.environ, PYTHONPATH=str(shadow.parent), COPPER_FLIGHT_NATIVE_BINARY=str(engine),
                       COPPER_FLIGHT_ASSET_DIR=str(assets), COPPER_FLIGHT_MODEL=str(model),
                       FLIGHT_DISPLAY_MODE="existing", DISPLAY=":99", FLIGHT_INFERENCE="cpu",
                       COPPER_FLIGHT_LOG_DIR=str(root), COPPER_FLIGHT_TELEMETRY=str(root / "telemetry.jsonl"))
            result = subprocess.run([str(wrapper)], cwd=root, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            import json
            observed = json.loads(report.read_text())
            self.assertEqual(observed["cwd"], str(ROOT))
            self.assertEqual(observed["env"]["WGPU_BACKEND"], "vulkan")
            icd = root / "lvp.json"
            icd.write_text("{}")
            software = dict(env, FLIGHT_DISPLAY_MODE="software", VK_ICD_FILENAMES=str(icd))
            software.pop("WGPU_SETTINGS_PRIO", None)
            result = subprocess.run([str(wrapper)], cwd=root, env=software, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(report.read_text())["env"]["WGPU_SETTINGS_PRIO"], "webgpu")
            software["WGPU_SETTINGS_PRIO"] = "functionality"
            result = subprocess.run([str(wrapper)], cwd=root, env=software, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(report.read_text())["env"]["WGPU_SETTINGS_PRIO"], "functionality")
            for value in (None, "", "relative.json", str(root / "missing.json")):
                with self.subTest(invalid_software_icd=value):
                    invalid = dict(software)
                    if value is None:
                        invalid.pop("VK_ICD_FILENAMES", None)
                    else:
                        invalid["VK_ICD_FILENAMES"] = value
                    report.unlink(missing_ok=True)
                    result = subprocess.run([str(wrapper)], cwd=root, env=invalid, capture_output=True, text=True)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("explicit VK_ICD_FILENAMES", result.stderr)
                    self.assertNotIn("Traceback", result.stderr)
                    self.assertFalse(report.exists(), "unsafe software ICD reached the executable")
            model.unlink()
            result = subprocess.run([str(wrapper)], cwd=root, env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("offline model", result.stderr)


@unittest.skipUnless(sys.platform == "linux" and os.geteuid() == 0 and
                     os.environ.get("FLIGHT_TEST_EPHEMERAL_CONTAINER") == "1",
                     "requires explicitly opted-in ephemeral Linux root container")
class LinuxRootBootTests(unittest.TestCase):
    def test_actual_root_boot_execs_surface_free_service_without_root_supervisor(self):
        # The child is a labelled fault-injection fixture, not a fake flight engine.
        data = Path("/data")
        (data / "copper-flight/runs").mkdir(parents=True, exist_ok=True)
        (data / "runs").mkdir(exist_ok=True)
        sentinel = data / "runs/old-rover-sentinel"
        sentinel.write_text("do not touch old recordings")
        for mode in ["existing", "headless", "software"]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                root.chmod(0o755)
                launcher = root / "test-stalled-engine"
                launcher.write_text(f"#!{sys.executable}\nimport os,time,pathlib\n" +
                    "print('TEST stalled engine fixture; no simulation telemetry', flush=True)\n" +
                    "pathlib.Path(os.environ['COPPER_FLIGHT_TELEMETRY']).with_name('engine.pid').write_text(str(os.getpid()))\n" +
                    "time.sleep(30)\n")
                launcher.chmod(0o755)
                env = dict(os.environ, FLIGHT_DISPLAY_MODE=mode, DISPLAY=":TEST-not-used",
                           VK_ICD_FILENAMES="/usr/share/vulkan/icd.d/lvp_icd.json", PORT="0",
                           FLIGHT_DATA_DIR="/data/copper-flight", COPPER_FLIGHT_LAUNCHER=str(launcher),
                           FLIGHT_STARTUP_TIMEOUT_SECONDS="2", FLIGHT_INACTIVITY_TIMEOUT_SECONDS="1")
                old = set((data / "copper-flight/runs").glob("*/engine.pid"))
                process = subprocess.Popen([str(ROOT / "scripts/start-flight")], cwd="/", env=env,
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    deadline = time.monotonic() + 5
                    engine_pid = None
                    while time.monotonic() < deadline and process.poll() is None:
                        new = set((data / "copper-flight/runs").glob("*/engine.pid")) - old
                        if new:
                            engine_pid = int(next(iter(new)).read_text())
                            break
                        time.sleep(.02)
                    if engine_pid is None:
                        output, error = process.communicate(timeout=5)
                        self.fail(f"{mode} did not launch test engine: {output}\n{error}")
                    matching = []
                    for entry in Path("/proc").iterdir():
                        if entry.name.isdigit():
                            try:
                                command = (entry / "cmdline").read_bytes()
                                if str(ROOT / "service.py").encode() in command or int(entry.name) == engine_pid or \
                                        (mode != "existing" and int(entry.name) == process.pid):
                                    matching.append(entry)
                            except (OSError, ValueError):
                                pass
                    self.assertEqual(len(matching), 2, "surface-free boot must exec, not retain a root parent")
                    for entry in matching:
                        security = dict(line.split(":", 1) for line in (entry / "status").read_text().splitlines() if ":" in line)
                        self.assertEqual(set(security["Uid"].split()), {"10001"})
                        self.assertEqual(set(security["Gid"].split()), {"10001"})
                        self.assertIn("28", security["Groups"].split())
                        self.assertNotIn("0", security["Groups"].split())
                        self.assertEqual(security["NoNewPrivs"].strip(), "1")
                        cwd = subprocess.check_output(["setpriv", "--reuid=10001", "--regid=10001", "--groups=28",
                            "--no-new-privs", sys.executable, "-c", "import os,sys; print(os.readlink(sys.argv[1]))",
                            str(entry / "cwd")], text=True).strip()
                        self.assertEqual(cwd, str(ROOT))
                    if mode != "existing":
                        runtime = Path("/run/copper-flight/xdg")
                        for directory, mode_bits in ((runtime, 0o700), (data / "copper-flight", 0o750),
                                                     (data / "copper-flight/runs", 0o750)):
                            info = directory.stat()
                            self.assertEqual((info.st_uid, info.st_gid, info.st_mode & 0o777),
                                             (10001, 10001, mode_bits))
                        self.assertEqual(list(runtime.glob("wayland-*")), [])
                    output, error = process.communicate(timeout=7)
                    self.assertEqual(process.returncode, 1, output + error)
                    self.assertIn("startup deadline", error)
                    self.assertFalse(Path(f"/proc/{engine_pid}").exists(), "engine survived supervisor exit")
                    self.assertEqual(sentinel.read_text(), "do not touch old recordings")
                finally:
                    if process.poll() is None:
                        process.terminate()
                        process.communicate(timeout=8)


if __name__ == "__main__":
    unittest.main()
