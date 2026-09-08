from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = ROOT / "desktop" / "src-tauri" / "binaries"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _sidecar() -> Path:
    candidates = [
        path
        for path in BIN_DIR.glob("audio-score-backend-*")
        if path.is_file() and not path.name.endswith((".sig", ".sha256"))
    ]
    if len(candidates) != 1:
        names = ", ".join(path.name for path in candidates) or "none"
        raise RuntimeError(f"Expected one packaged sidecar, found: {names}")
    return candidates[0]


def _request(url: str, token: str | None = None) -> tuple[int, bytes]:
    headers = {"X-AudioScore-Token": token} if token else {}
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read()


def main() -> None:
    binary = _sidecar()
    port = _free_port()
    token = "ci-sidecar-smoke-token"
    env = os.environ.copy()
    env["AST_API_PORT"] = str(port)
    env["AST_API_TOKEN"] = token
    process = subprocess.Popen(
        [str(binary)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        health_url = f"http://127.0.0.1:{port}/api/health"
        deadline = time.monotonic() + 30
        authenticated: tuple[int, bytes] | None = None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"Packaged sidecar exited early with code {process.returncode}")
            try:
                authenticated = _request(health_url, token)
                if authenticated[0] == 200:
                    break
            except (OSError, urllib.error.URLError):
                pass
            time.sleep(0.25)
        if authenticated is None or authenticated[0] != 200:
            raise RuntimeError(f"Packaged sidecar did not become healthy: {authenticated}")

        status, _ = _request(health_url)
        if status != 401:
            raise RuntimeError(f"Unauthenticated packaged API request returned {status}, expected 401")

        payload = json.loads(authenticated[1].decode("utf-8"))
        if not isinstance(payload, dict) or not payload:
            raise RuntimeError("Authenticated health response was not a JSON object")
        print(f"Packaged sidecar smoke passed on 127.0.0.1:{port}")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
