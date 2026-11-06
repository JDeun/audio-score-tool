from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from audio_score_tool.managed_publication_readiness import CORE_COMPONENTS, _REQUIRED_TOOLS

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


def _post_json(url: str, token: str, payload: dict) -> tuple[int, bytes]:
    """Perform a catalog-owned install request; no archive URLs enter this call."""
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "X-AudioScore-Token": token,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=900) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read()


def _component_index(base_url: str, token: str) -> dict[str, dict]:
    status, payload = _request(f"{base_url}/api/setup/center", token)
    if status != 200:
        raise RuntimeError(f"Managed component status request returned {status}")
    response = _json_object(payload, label="managed component status")
    values = response.get("components")
    if not isinstance(values, list):
        raise RuntimeError("Setup Center component inventory is missing.")
    return {
        item["key"]: item
        for item in values
        if isinstance(item, dict) and isinstance(item.get("key"), str)
    }


def _verify_managed_delivery(base_url: str, token: str, component_root: Path) -> None:
    """Deep sidecar smoke: actual approved archive download/install on this OS.

    Deliberately opt-in on manual QA, and mandatory for v1 tag builds. This does
    not exercise model inference, music quality or Audiveris JRE execution.
    Those still require explicit release acceptance beyond component integrity.
    """
    initial = _component_index(base_url, token)
    # Check every required catalog entry *before* starting large downloads.
    for component in CORE_COMPONENTS:
        item = initial.get(component)
        catalog = item.get("catalog") if isinstance(item, dict) else None
        if not isinstance(catalog, dict) or catalog.get("published") is not True:
            reason = catalog.get("publication_reason") if isinstance(catalog, dict) else None
            raise RuntimeError(
                f"{component}: no approved platform artifact: {reason or 'catalog-unavailable'}"
            )
        if item.get("auto_install") is not True:
            raise RuntimeError(f"{component}: Setup Center did not authorize managed installation.")

    trusted_root = component_root.resolve()
    for component in CORE_COMPONENTS:
        status, payload = _post_json(
            f"{base_url}/api/setup/install", token, {"component": component}
        )
        if status != 200:
            detail = payload.decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"{component}: managed installation failed ({status}): {detail}")
        response = _json_object(payload, label=f"{component} install")
        installed = response.get("installed")
        if not isinstance(installed, dict):
            raise RuntimeError(f"{component}: missing verified installer result.")
        if installed.get("ready") is not True or installed.get("integrity") != "verified":
            raise RuntimeError(f"{component}: installed component integrity was not verified.")
        tools = installed.get("tools")
        if not isinstance(tools, dict):
            raise RuntimeError(f"{component}: verified tool map is missing.")
        missing = sorted(_REQUIRED_TOOLS.get(component, frozenset()) - set(tools))
        if missing:
            raise RuntimeError(f"{component}: required installed tools missing: {','.join(missing)}")
        for name, executable in tools.items():
            if not isinstance(executable, str):
                raise RuntimeError(f"{component}: non-string executable path: {name}")
            tool = Path(executable)
            if tool.is_symlink() or not tool.is_file():
                raise RuntimeError(f"{component}: non-regular installed tool: {name}")
            try:
                tool.resolve().relative_to(trusted_root)
            except ValueError as exc:
                raise RuntimeError(
                    f"{component}: installed tool escapes the managed root: {name}"
                ) from exc

    # The API is re-queried so this is not merely a trust in POST responses.
    latest = _component_index(base_url, token)
    for component in CORE_COMPONENTS:
        item = latest.get(component)
        managed = item.get("managed_status") if isinstance(item, dict) else None
        if (
            not isinstance(managed, dict)
            or managed.get("ready") is not True
            or managed.get("integrity") != "verified"
        ):
            raise RuntimeError(
                f"{component}: Setup Center did not persist verified installed status."
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke packaged AudioScoreTool sidecar.")
    parser.add_argument(
        "--require-managed-delivery",
        action="store_true",
        help="Download and verify all approved managed core archives through the packaged API.",
    )
    args = parser.parse_args()
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
            if args.require_managed_delivery:
                _verify_managed_delivery(base_url, token, Path(component_root))
            print(
                f"Packaged sidecar smoke passed on 127.0.0.1:{port}"
                + (" (managed delivery verified)" if args.require_managed_delivery else "")
            )
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
