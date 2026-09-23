"""Run current pymobiledevice3 beside GeoPort's bundled legacy dependency."""

import json
import queue
import subprocess
import threading
from pathlib import Path


class ModernLocationController:
    def __init__(self, python_executable=None, bridge_executable=None):
        self.python_executable = python_executable
        self.bridge_executable = bridge_executable
        self.bridge = Path(__file__).with_name("modern_location_bridge.py")
        self._process = None
        self._udid = None
        self._lock = threading.RLock()

    @property
    def enabled(self):
        return bool(self.python_executable or self.bridge_executable)

    def _command(self, action, udid, *coordinates):
        if self.bridge_executable:
            command = [self.bridge_executable]
        elif self.python_executable:
            command = [self.python_executable, str(self.bridge)]
        else:
            raise RuntimeError("No modern pymobiledevice3 location bridge configured")
        return [*command, action, "--udid", udid,
                *(str(value) for value in coordinates)]

    def _clear(self, udid):
        result = subprocess.run(self._command("clear", udid), capture_output=True,
                                text=True, timeout=45)
        if result.returncode:
            raise RuntimeError(result.stdout.strip() or result.stderr.strip() or
                               "DVT clear failed")

    def set(self, udid, latitude, longitude):
        with self._lock:
            self.stop()
            process = subprocess.Popen(
                self._command("set", udid, latitude, longitude),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1,
            )
            response_line = queue.Queue(maxsize=1)
            threading.Thread(
                target=lambda: response_line.put(process.stdout.readline()),
                daemon=True,
            ).start()
            try:
                try:
                    line = response_line.get(timeout=90)
                except queue.Empty as exc:
                    raise TimeoutError("DVT set did not respond within 90 seconds") from exc
                response = json.loads(line) if line else {}
                if not response.get("ready"):
                    raise RuntimeError(response.get("error") or
                                       process.stderr.read().strip() or "DVT set failed")
            except Exception:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                raise
            self._process = process
            self._udid = udid

    def stop(self):
        with self._lock:
            process, udid = self._process, self._udid
            self._process = self._udid = None
            if process is None:
                return
            if process.poll() is None:
                try:
                    process.stdin.write("\n")
                    process.stdin.flush()
                    process.wait(timeout=20)
                except (BrokenPipeError, subprocess.TimeoutExpired):
                    process.kill()
                    process.wait()
            if process.returncode != 0:
                self._clear(udid)

    def clear(self, udid):
        with self._lock:
            if self._process is not None and self._udid == udid:
                self.stop()
            else:
                self._clear(udid)
