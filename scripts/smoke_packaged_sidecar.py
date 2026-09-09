from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
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
        with urllib.request.urlopen(request, timeout=3) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read()


def _json_object(payload: bytes, *, label: str) -> dict:
    value = json.loads(payload.decode("utf-8"))
    if not isinstance(value, dict) or not value:
        raise RuntimeError(f"{label} response was not a JSON object")
    return value


def _verify_embedded_runtime(base_url: str, token: str) -> None:
    status, payload = _request(f"{base_url}/api/setup/center", token)
    if status != 200:
        raise RuntimeError(f"Packaged setup-center request returned {status}")
    state = _json_object(payload, label="setup-center")
    components = state.get("components")
    if not isinstance(components, list):
        raise RuntimeError("Packaged setup-center response did not contain components")
    by_key = {
        item.get("key"): item
        for item in components
        if isinstance(item, dict) and isinstance(item.get("key"), str)
    }
    desktop_runtime = by_key.get("desktop_runtime")
    if not desktop_runtime or desktop_runtime.get("ready") is not True:
        raise RuntimeError(
            "Packaged embedded notation runtime is not ready; "
            "music21/verovio/fpdf2 may be missing from the sidecar"
        )
    for key in ("transcription_engine", "youtube_runtime", "audiveris", "audio_validation"):
        component = by_key.get(key)
        if not component:
            raise RuntimeError(f"Packaged setup-center is missing managed component {key}")
        catalog = component.get("catalog")
        managed_status = component.get("managed_status")
        if not isinstance(catalog, dict) or not catalog.get("target"):
            raise RuntimeError(f"Packaged managed catalog metadata is missing for {key}")
        if not isinstance(managed_status, dict) or not managed_status.get("integrity"):
            raise RuntimeError(f"Packaged managed runtime integrity state is missing for {key}")

    policy = state.get("policy")
    if not isinstance(policy, dict) or policy.get("pdf_renderer") != "embedded-verovio-fpdf2":
        raise RuntimeError("Packaged runtime does not report the embedded PDF renderer policy")
    if policy.get("system_package_manager_required") is not False:
        raise RuntimeError("Packaged runtime unexpectedly requires a system package manager")
    if policy.get("managed_component_system_path_fallback") is not False:
        raise RuntimeError("Packaged managed runtime unexpectedly allows system PATH fallback")
    if policy.get("managed_component_integrity") != "sha256+atomic-state+root-containment":
        raise RuntimeError("Packaged managed runtime integrity policy is incomplete")


def main() -> None:
    binary = _sidecar()
    port = _free_port()
    token = "ci-sidecar-smoke-token"
    with tempfile.TemporaryDirectory(prefix="ast-component-smoke-") as component_root:
        env = os.environ.copy()
        env["AST_API_PORT"] = str(port)
        env["AST_API_TOKEN"] = token
        env["AST_PACKAGED"] = "1"
        env["AST_COMPONENT_DIR"] = component_root
        process = subprocess.Popen(
            [str(binary)],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            base_url = f"http://127.0.0.1:{port}"
            health_url = f"{base_url}/api/health"
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

            _json_object(authenticated[1], label="authenticated health")
            _verify_embedded_runtime(base_url, token)
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
