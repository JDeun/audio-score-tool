from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import shutil
import stat
import tarfile
import tempfile
import threading
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from .config import component_dir
from .managed_payload_integrity import build_payload_inventory, verify_payload_inventory

_SCHEMA_VERSION = 1
_MAX_ARCHIVE_MEMBERS = 4096
_MAX_UNCOMPRESSED_BYTES = 4 * 1024 * 1024 * 1024
_MAX_DOWNLOAD_BYTES = 8 * 1024 * 1024 * 1024
_MAX_ZIP_COMPRESSION_RATIO = 500
_INSTALL_LOCK = threading.RLock()
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class ComponentError(RuntimeError):
    pass


class ComponentUnavailable(ComponentError):
    pass


class ComponentIntegrityError(ComponentError):
    pass


def _safe_identifier(value: str) -> bool:
    return bool(_SAFE_IDENTIFIER.fullmatch(value)) and value not in {".", ".."}


def _safe_relative_path(value: str) -> bool:
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or not path.parts:
        return False
    return all(part not in {"", ".", ".."} for part in path.parts)


def _validated_download_url(url: str) -> urllib.parse.SplitResult:
    parsed = urllib.parse.urlsplit(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ComponentIntegrityError("Managed component HTTPS URL has an invalid port.") from exc
    if (
        parsed.scheme.lower() != "https"
        or parsed.username
        or parsed.password
        or not parsed.hostname
        or parsed.fragment
        or port not in {None, 443}
    ):
        raise ComponentIntegrityError(
            "Managed component downloads must use credential-free HTTPS URLs without fragments."
        )
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ComponentIntegrityError("Managed component download host must not be local.")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise ComponentIntegrityError("Managed component download host must be public.")
    return parsed


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class ComponentArtifact:
    component: str
    version: str
    url: str
    sha256: str
    archive: str
    tools: dict[str, str]
    max_download_bytes: int = _MAX_DOWNLOAD_BYTES
    max_uncompressed_bytes: int = _MAX_UNCOMPRESSED_BYTES
    license: str | None = None
    provenance: str | None = None

    def __post_init__(self) -> None:
        if not _safe_identifier(self.component) or not _safe_identifier(self.version):
            raise ComponentIntegrityError("Managed component name/version is unsafe.")
        if (
            len(self.sha256) != 64
            or self.sha256 != self.sha256.lower()
            or any(ch not in "0123456789abcdef" for ch in self.sha256)
        ):
            raise ComponentIntegrityError("Managed component manifest has an invalid SHA-256 digest.")
        if self.archive not in {"zip", "tar", "raw"}:
            raise ComponentUnavailable(f"Unsupported managed component archive type: {self.archive}")
        if self.max_download_bytes <= 0 or self.max_uncompressed_bytes <= 0:
            raise ComponentIntegrityError("Managed component size limits must be positive.")
        if not self.tools:
            raise ComponentUnavailable("Managed component must expose at least one tool.")
        for name, relative in self.tools.items():
            if not _safe_identifier(str(name)) or not _safe_relative_path(str(relative)):
                raise ComponentIntegrityError("Managed component tool path is unsafe.")
        _validated_download_url(self.url)

    @classmethod
    def from_dict(cls, payload: dict) -> "ComponentArtifact":
        try:
            component = str(payload["component"]).strip()
            version = str(payload["version"]).strip()
            url = str(payload["url"]).strip()
            sha256 = str(payload["sha256"]).strip().lower()
            archive = str(payload.get("archive") or "zip").strip().lower()
            tools_raw = payload["tools"]
        except (KeyError, TypeError, ValueError) as exc:
            raise ComponentUnavailable("Managed component manifest entry is incomplete.") from exc
        if not component or not version or not url:
            raise ComponentUnavailable("Managed component manifest entry is incomplete.")
        if not isinstance(tools_raw, dict):
            raise ComponentUnavailable("Managed component must expose tool mappings.")
        tools = {str(key): str(value) for key, value in tools_raw.items()}
        try:
            max_download_bytes = int(payload.get("max_download_bytes") or _MAX_DOWNLOAD_BYTES)
            max_uncompressed_bytes = int(
                payload.get("max_uncompressed_bytes") or _MAX_UNCOMPRESSED_BYTES
            )
        except (TypeError, ValueError) as exc:
            raise ComponentIntegrityError("Managed component size limits are invalid.") from exc
        return cls(
            component=component,
            version=version,
            url=url,
            sha256=sha256,
            archive=archive,
            tools=tools,
            max_download_bytes=max_download_bytes,
            max_uncompressed_bytes=max_uncompressed_bytes,
            license=str(payload["license"]) if payload.get("license") else None,
            provenance=str(payload["provenance"]) if payload.get("provenance") else None,
        )


def _root() -> Path:
    root = component_dir().expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _state_path(root: Path | None = None) -> Path:
    return (root or _root()) / "state.json"


def _load_state(root: Path | None = None) -> dict:
    root = root or _root()
    path = _state_path(root)
    if not path.exists():
        return {"schema": _SCHEMA_VERSION, "components": {}}
    if path.is_symlink():
        raise ComponentIntegrityError("Managed component state may not be a symlink.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ComponentIntegrityError("Managed component state is corrupt.") from exc
    if not isinstance(payload, dict) or payload.get("schema") != _SCHEMA_VERSION:
        raise ComponentIntegrityError("Managed component state schema is unsupported.")
    components = payload.get("components")
    if not isinstance(components, dict):
        raise ComponentIntegrityError("Managed component state is invalid.")
    if any(not _safe_identifier(str(name)) for name in components):
        raise ComponentIntegrityError("Managed component state contains an unsafe component name.")
    return payload


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        temp.replace(path)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


def _removal_stage(root: Path, component: str, version: str) -> Path:
    digest = hashlib.sha256(f"{component}:{version}".encode()).hexdigest()[:16]
    return root / f".removing-{component}-{digest}"


def _install_backup(root: Path, component: str, version: str) -> Path:
    """Deterministic backup path for an interrupted same-version replacement."""
    token = hashlib.sha256(f"{component}:{version}".encode()).hexdigest()[:16]
    return root / "installed" / component / f".previous-{token}"


def _tree_matches_state(path: Path, entry: dict, root: Path) -> bool:
    """Verify an installation against committed tool identities, not directory names."""
    if path.is_symlink() or not path.is_dir():
        return False
    tools = entry.get("tools")
    digests = entry.get("tool_sha256")
    if not isinstance(tools, dict) or not tools or not isinstance(digests, dict):
        return False
    try:
        real = path.resolve()
        real.relative_to(root.resolve())
        for name, relative in tools.items():
            digest = digests.get(name)
            if (
                not _safe_identifier(str(name))
                or not isinstance(relative, str)
                or not _safe_relative_path(relative)
                or not isinstance(digest, str)
                or re.fullmatch(r"[a-f0-9]{64}", digest) is None
            ):
                return False
            tool = path.joinpath(*PurePosixPath(relative.replace("\\", "/")).parts)
            if tool.is_symlink() or not tool.is_file():
                return False
            tool.resolve().relative_to(real)
            if _file_sha256(tool) != digest:
                return False
    except (OSError, ValueError, RuntimeError):
        return False
    return verify_payload_inventory(path, entry.get("payload_files")) is None



_ROLLBACK_IDENTITY_FIELDS = (
    "version", "root", "tools", "tool_sha256",
    "archive_sha256", "license", "provenance", "payload_files",
)


def _verified_install_snapshot(root: Path, component: str, entry: object) -> dict | None:
    """Only a previously committed, owned version may be offered for rollback.

    The snapshot deliberately excludes nested rollback history. Old state.json
    entries remain readable; they simply have no rollback until a verified
    cross-version upgrade has occurred.
    """
    if not _safe_identifier(component) or not isinstance(entry, dict):
        return None
    version = entry.get("version")
    if not isinstance(version, str) or not _safe_identifier(version):
        return None
    expected = (PurePosixPath("installed") / component / version).as_posix()
    archive_digest = entry.get("archive_sha256")
    if (
        entry.get("root") != expected
        or not isinstance(archive_digest, str)
        or re.fullmatch(r"[a-f0-9]{64}", archive_digest) is None
    ):
        return None
    installed_root = root / "installed"
    component_root = installed_root / component
    if installed_root.is_symlink() or component_root.is_symlink():
        return None
    version_root = component_root / version
    if not _tree_matches_state(version_root, entry, root):
        return None
    return {field: entry.get(field) for field in _ROLLBACK_IDENTITY_FIELDS}


def component_rollback_status(component: str, *, root: Path | None = None) -> dict:
    """Expose prior-version availability without trusting a directory name."""
    root = (root or _root()).resolve()
    if not _safe_identifier(component):
        return {"available": False, "reason": "invalid-name"}
    try:
        state = _load_state(root)
    except ComponentIntegrityError:
        return {"available": False, "reason": "state-corrupt"}
    active = state["components"].get(component)
    if not isinstance(active, dict):
        return {"available": False, "reason": "not-installed"}
    previous = active.get("rollback")
    if previous is None:
        return {"available": False, "reason": "no-previous-version"}
    snapshot = _verified_install_snapshot(root, component, previous)
    if snapshot is None or snapshot["version"] == active.get("version"):
        return {"available": False, "reason": "previous-version-unverified"}
    return {
        "available": True,
        "version": snapshot["version"],
        "integrity": "verified",
    }


def rollback_component_artifact(component: str, *, root: Path | None = None) -> dict:
    """Atomically reactivate the SHA-verified previous version, without a download.

    The current version stays on disk until a separately reviewed cleanup; it
    stops being executable through the managed registry as soon as state.json
    switches. Never delete the only verified rollback copy during this action.
    """
    if not _safe_identifier(component):
        raise ComponentIntegrityError("Managed component name is unsafe.")
    root = (root or _root()).resolve()
    with _INSTALL_LOCK:
        state = _load_state(root)
        current = state["components"].get(component)
        if not isinstance(current, dict):
            raise ComponentUnavailable("No installed managed component to roll back.")
        previous = _verified_install_snapshot(root, component, current.get("rollback"))
        if previous is None or previous["version"] == current.get("version"):
            raise ComponentIntegrityError(
                "Previous managed runtime is missing, damaged or not verified; "
                "rollback was not performed."
            )
        components = dict(state["components"])
        components[component] = previous
        _atomic_write_json(
            _state_path(root),
            {"schema": _SCHEMA_VERSION, "components": components},
        )
        return component_status(component, root=root)


def _recover_install_backups(root: Path, state: dict | None) -> dict[str, int]:
    """Reconcile crashed replacements with the last *committed* state.

    A backup is never trusted on its name alone. If the committed active
    executable bytes still match, the backup is obsolete. Otherwise restore
    only if the backup matches every committed tool checksum. Ambiguous,
    symlinked or corrupt data stays untouched for explicit manual recovery.
    """
    report = {
        "restored_previous_install": 0,
        "removed_previous_install_backup": 0,
        "pending_previous_install_backup": 0,
    }
    installed = root / "installed"
    if installed.is_symlink() or not installed.is_dir():
        return report
    for component_root in installed.iterdir():
        if component_root.is_symlink() or not component_root.is_dir():
            continue
        component = component_root.name
        for backup in component_root.glob(".previous-*"):
            entry = (
                state.get("components", {}).get(component)
                if state is not None and _safe_identifier(component)
                else None
            )
            version = entry.get("version") if isinstance(entry, dict) else None
            expected_root = (
                (PurePosixPath("installed") / component / version).as_posix()
                if isinstance(version, str) and _safe_identifier(version)
                else None
            )
            if (
                backup.is_symlink()
                or not backup.is_dir()
                or expected_root is None
                or entry.get("root") != expected_root
                or backup != _install_backup(root, component, version)
            ):
                report["pending_previous_install_backup"] += 1
                continue
            current = component_root / version
            if _tree_matches_state(current, entry, root):
                try:
                    shutil.rmtree(backup)
                    report["removed_previous_install_backup"] += 1
                except OSError:
                    report["pending_previous_install_backup"] += 1
                continue
            if not _tree_matches_state(backup, entry, root):
                report["pending_previous_install_backup"] += 1
                continue
            # The old committed binary is recoverable. Never follow a
            # non-regular or symlinked replacement at the active path.
            if current.is_symlink() or (current.exists() and not current.is_dir()):
                report["pending_previous_install_backup"] += 1
                continue
            try:
                if current.exists():
                    shutil.rmtree(current)
                # A crash between these two operations leaves the verified
                # backup intact for the next recovery pass.
                backup.replace(current)
                report["restored_previous_install"] += 1
            except OSError:
                report["pending_previous_install_backup"] += 1
    return report


def recover_component_staging(root: Path | None = None) -> dict[str, int]:
    """Restore interrupted installs/removals and clear abandoned staging files."""
    root = (root or _root()).resolve()
    removed = 0
    restored = 0
    with _INSTALL_LOCK:
        # Never erase a pending removal when the active state is corrupt:
        # the only copy of a verified install may be in .removing-*.
        try:
            state = _load_state(root)
        except ComponentIntegrityError:
            state = None
        backup_recovery = _recover_install_backups(root, state)
        for path in root.glob(".removing-*"):
            if state is None:
                continue
            if not path.is_symlink() and not path.is_dir():
                continue
            owner = None
            for component, item in state["components"].items():
                version = item.get("version") if isinstance(item, dict) else None
                if isinstance(version, str) and _safe_identifier(version):
                    if path.name == _removal_stage(root, component, version).name:
                        owner = component
                        break
            if owner is not None:
                target_parent = root / "installed"
                target = target_parent / owner
                if target_parent.is_symlink() or target.is_symlink():
                    continue
                if not target.exists():
                    target_parent.mkdir(parents=True, exist_ok=True)
                    try:
                        path.replace(target)
                        restored += 1
                    except OSError:
                        continue
                    continue
            try:
                if path.is_symlink():
                    path.unlink()
                else:
                    shutil.rmtree(path)
                removed += 1
            except OSError:
                continue
        for pattern in (".staging-*", ".download-*"):
            for path in root.glob(pattern):
                try:
                    if path.is_dir() and not path.is_symlink():
                        shutil.rmtree(path)
                    else:
                        path.unlink(missing_ok=True)
                    removed += 1
                except OSError:
                    continue
    return {
        "removed_component_staging": removed,
        "restored_component_removal": restored,
        **backup_recovery,
    }


def _copy_stream(source: BinaryIO, target: Path, *, max_bytes: int) -> str:
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    digest = hashlib.sha256()
    total = 0
    with target.open("wb") as handle:
        while True:
            chunk = source.read(min(1024 * 1024, max_bytes - total + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ComponentIntegrityError("Managed component download exceeds its size limit.")
            digest.update(chunk)
            handle.write(chunk)
        handle.flush()
        os.fsync(handle.fileno())
    return digest.hexdigest()


class _VerifiedHTTPSRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Validate each redirect destination *before* urllib opens its connection."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validated_download_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_trusted_download(request: urllib.request.Request):
    # urlopen() follows redirects before returning a final response, which is
    # too late to reject a downgrade to HTTP/loopback. A per-request opener
    # rejects each hop while keeping normal GitHub release HTTPS redirects.
    opener = urllib.request.build_opener(_VerifiedHTTPSRedirectHandler)
    return opener.open(request, timeout=60)


def _download(artifact: ComponentArtifact, target: Path) -> str:
    _validated_download_url(artifact.url)
    request = urllib.request.Request(
        artifact.url,
        headers={"User-Agent": "AudioScoreTool-managed-component/1"},
        method="GET",
    )
    try:
        with _open_trusted_download(request) as response:
            _validated_download_url(str(response.geturl()))
            return _copy_stream(response, target, max_bytes=artifact.max_download_bytes)
    except ComponentError:
        raise
    except Exception as exc:
        raise ComponentUnavailable("Managed component download failed.") from exc


def _validate_member_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name.replace("\\", "/"))
    if not path.parts or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ComponentIntegrityError("Managed component archive contains an unsafe path.")
    return path


def _extract_zip(archive_path: Path, destination: Path, *, max_uncompressed_bytes: int) -> None:
    total = 0
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        if len(infos) > _MAX_ARCHIVE_MEMBERS:
            raise ComponentIntegrityError("Managed component archive contains too many entries.")
        for info in infos:
            rel = _validate_member_path(info.filename)
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ComponentIntegrityError("Managed component archives may not contain symlinks.")
            if info.flag_bits & 0x1:
                raise ComponentIntegrityError("Encrypted managed component archive members are rejected.")
            if (
                info.compress_size > 0
                and info.file_size / info.compress_size > _MAX_ZIP_COMPRESSION_RATIO
            ):
                raise ComponentIntegrityError(
                    "Managed component archive has an abnormal compression ratio."
                )
            total += max(0, info.file_size)
            if total > max_uncompressed_bytes:
                raise ComponentIntegrityError("Managed component archive expands beyond its size limit.")
            target = destination.joinpath(*rel.parts)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info, "r") as source, target.open("wb") as output:
                copied = 0
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    copied += len(chunk)
                    if copied > info.file_size:
                        raise ComponentIntegrityError(
                            "Managed component archive member size is inconsistent."
                        )
                    output.write(chunk)
                if copied != info.file_size:
                    raise ComponentIntegrityError(
                        "Managed component archive member ended before its declared size."
                    )
            # Nested bundled runtimes (e.g. Audiveris' jlink Java binary)
            # also need their executable bit after a ZIP install. Preserve
            # only the author's owner-execute bit on POSIX, never arbitrary
            # setuid/setgid, group/world write or other archive permissions.
            # Tool entries are independently verified and chmod'd by
            # _verify_tools; this restores safe permissions for non-tool
            # executables without weakening symlink/path rejection.
            if (
                os.name != "nt"
                and info.create_system == 3
                and stat.S_ISREG(mode)
                and mode & stat.S_IXUSR
            ):
                target.chmod(target.stat().st_mode | stat.S_IXUSR)


def _extract_tar(archive_path: Path, destination: Path, *, max_uncompressed_bytes: int) -> None:
    total = 0
    with tarfile.open(archive_path, mode="r:*") as archive:
        members = archive.getmembers()
        if len(members) > _MAX_ARCHIVE_MEMBERS:
            raise ComponentIntegrityError("Managed component archive contains too many entries.")
        for member in members:
            rel = _validate_member_path(member.name)
            if member.issym() or member.islnk() or member.isdev():
                raise ComponentIntegrityError("Managed component archives may not contain links or devices.")
            total += max(0, member.size)
            if total > max_uncompressed_bytes:
                raise ComponentIntegrityError("Managed component archive expands beyond its size limit.")
            target = destination.joinpath(*rel.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                continue
            source = archive.extractfile(member)
            if source is None:
                raise ComponentIntegrityError("Managed component archive member cannot be read.")
            target.parent.mkdir(parents=True, exist_ok=True)
            copied = 0
            with source, target.open("wb") as output:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    copied += len(chunk)
                    if copied > member.size:
                        raise ComponentIntegrityError(
                            "Managed component archive member size is inconsistent."
                        )
                    output.write(chunk)
            if copied != member.size:
                raise ComponentIntegrityError(
                    "Managed component archive member ended before its declared size."
                )


def _extract(artifact: ComponentArtifact, archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    try:
        if artifact.archive == "zip":
            _extract_zip(
                archive_path,
                destination,
                max_uncompressed_bytes=artifact.max_uncompressed_bytes,
            )
        elif artifact.archive == "tar":
            _extract_tar(
                archive_path,
                destination,
                max_uncompressed_bytes=artifact.max_uncompressed_bytes,
            )
        else:
            if len(artifact.tools) != 1:
                raise ComponentIntegrityError("Raw components must expose exactly one tool.")
            relative = next(iter(artifact.tools.values()))
            target = destination.joinpath(*PurePosixPath(relative).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(archive_path, target)
    except ComponentError:
        raise
    except (zipfile.BadZipFile, tarfile.TarError, EOFError, OSError) as exc:
        raise ComponentIntegrityError("Managed component archive is malformed or unreadable.") from exc


def _verify_tools(artifact: ComponentArtifact, staged: Path) -> tuple[dict[str, str], dict[str, str]]:
    resolved: dict[str, str] = {}
    digests: dict[str, str] = {}
    stage_root = staged.resolve()
    for name, relative in artifact.tools.items():
        candidate = staged.joinpath(*PurePosixPath(relative).parts)
        if candidate.is_symlink() or not candidate.is_file():
            raise ComponentIntegrityError(f"Managed component tool is missing: {name}")
        real = candidate.resolve()
        try:
            real.relative_to(stage_root)
        except ValueError as exc:
            raise ComponentIntegrityError("Managed component tool escapes its installation root.") from exc
        if os.name != "nt":
            candidate.chmod(candidate.stat().st_mode | stat.S_IXUSR)
        resolved[name] = relative
        digests[name] = _file_sha256(candidate)
    return resolved, digests


def install_component_artifact(
    artifact: ComponentArtifact,
    *,
    root: Path | None = None,
    local_archive: Path | None = None,
) -> dict:
    if not _safe_identifier(artifact.component) or not _safe_identifier(artifact.version):
        raise ComponentIntegrityError("Managed component name/version is unsafe.")
    root = (root or _root()).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with _INSTALL_LOCK:
        recover_component_staging(root)
        token = hashlib.sha256(f"{artifact.component}:{artifact.version}".encode()).hexdigest()[:16]
        download = root / f".download-{artifact.component}-{token}"
        staged = root / f".staging-{artifact.component}-{token}"
        install_root = root / "installed" / artifact.component
        final = install_root / artifact.version
        backup = _install_backup(root, artifact.component, artifact.version)
        # A previous failed recovery may have left the sole verified copy
        # behind. Never delete it just to start another installation.
        if backup.exists() or backup.is_symlink():
            raise ComponentIntegrityError(
                "Managed component has an unresolved previous installation; "
                "repair it before reinstalling."
            )
        state_committed = False
        final_activated = False
        try:
            if local_archive is not None:
                with local_archive.open("rb") as source:
                    actual = _copy_stream(
                        source,
                        download,
                        max_bytes=artifact.max_download_bytes,
                    )
            else:
                actual = _download(artifact, download)
            if actual != artifact.sha256:
                raise ComponentIntegrityError("Managed component checksum mismatch.")
            _extract(artifact, download, staged)
            tools, tool_sha256 = _verify_tools(artifact, staged)
            try:
                payload_files = build_payload_inventory(staged)
            except (OSError, ValueError) as exc:
                raise ComponentIntegrityError(
                    "Managed component contains an unsafe or unstable payload."
                ) from exc

            # For cross-version upgrades, save the identity of the *currently
            # verified* runtime before the state pointer changes. Keep the
            # previous verified generation on disk for explicit rollback.
            # Unverified/tampered old bytes must never become a rollback target.
            state = _load_state(root)
            previous = state["components"].get(artifact.component)
            rollback_entry = None
            if isinstance(previous, dict):
                if previous.get("version") != artifact.version:
                    rollback_entry = _verified_install_snapshot(
                        root, artifact.component, previous,
                    )
                else:
                    prior = previous.get("rollback")
                    if isinstance(prior, dict) and prior.get("version") != artifact.version:
                        rollback_entry = _verified_install_snapshot(
                            root, artifact.component, prior,
                        )

            install_root.mkdir(parents=True, exist_ok=True)
            if final.exists():
                if final.is_symlink() or not final.is_dir():
                    raise ComponentIntegrityError(
                        "Existing managed component installation root is unsafe."
                    )
                final.replace(backup)
            try:
                staged.replace(final)
                final_activated = True
            except BaseException:
                if backup.exists() and not final.exists():
                    backup.replace(final)
                raise

            components = dict(state["components"])
            updated = {
                "version": artifact.version,
                "root": str(final.relative_to(root).as_posix()),
                "tools": tools,
                "tool_sha256": tool_sha256,
                "payload_files": payload_files,
                "archive_sha256": artifact.sha256,
                "license": artifact.license,
                "provenance": artifact.provenance,
            }
            if rollback_entry is not None:
                updated["rollback"] = rollback_entry
            components[artifact.component] = updated
            _atomic_write_json(
                _state_path(root),
                {"schema": _SCHEMA_VERSION, "components": components},
            )
            state_committed = True
            if backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
            return component_status(artifact.component, root=root)
        except BaseException:
            if final_activated and not state_committed:
                if final.exists():
                    shutil.rmtree(final, ignore_errors=True)
                if backup.exists():
                    backup.replace(final)
            elif not final.exists() and backup.exists():
                backup.replace(final)
            raise
        finally:
            download.unlink(missing_ok=True)
            if staged.exists():
                shutil.rmtree(staged, ignore_errors=True)


def remove_component_artifact(component: str, *, root: Path | None = None) -> dict:
    """Atomically deactivate a catalog-owned component; never remove arbitrary paths.

    A crash before state commit restores the staged directory on recovery.
    A crash after state commit only leaves a detached stage, cleaned on recovery.
    """
    if not _safe_identifier(component):
        raise ComponentIntegrityError("Managed component name is unsafe.")
    root = (root or _root()).resolve()
    with _INSTALL_LOCK:
        state = _load_state(root)
        entry = state["components"].get(component)
        if entry is None:
            return {"component": component, "removed": False, "cleanup_pending": False}
        if not isinstance(entry, dict):
            raise ComponentIntegrityError("Managed component state entry is invalid.")
        version = entry.get("version")
        relative_root = entry.get("root")
        if not isinstance(version, str) or not _safe_identifier(version):
            raise ComponentIntegrityError("Managed component version is unsafe.")
        expected = (PurePosixPath("installed") / component / version).as_posix()
        if relative_root != expected:
            raise ComponentIntegrityError("Managed component removal path is not owned by the app.")
        installed_parent = root / "installed"
        component_root = installed_parent / component
        current = component_root / version
        if (
            installed_parent.is_symlink()
            or component_root.is_symlink()
            or not component_root.is_dir()
            or current.is_symlink()
            or not current.is_dir()
        ):
            raise ComponentIntegrityError("Managed component installation root is unsafe.")
        stage = _removal_stage(root, component, version)
        if stage.exists() or stage.is_symlink():
            raise ComponentIntegrityError("Managed component removal staging already exists.")
        component_root.replace(stage)
        try:
            components = dict(state["components"])
            del components[component]
            _atomic_write_json(
                _state_path(root),
                {"schema": _SCHEMA_VERSION, "components": components},
            )
        except BaseException:
            stage.replace(component_root)
            raise
        try:
            shutil.rmtree(stage)
            pending = False
        except OSError:
            # The component is already deactivated in state.json; recovery
            # may remove this detached directory after any lingering file lock.
            pending = True
        return {
            "component": component,
            "removed": True,
            "removed_version": version,
            "cleanup_pending": pending,
        }


def component_status(component: str, *, root: Path | None = None) -> dict:
    root = (root or _root()).resolve()
    if not _safe_identifier(component):
        return {"component": component, "ready": False, "integrity": "invalid-name"}
    try:
        state = _load_state(root)
    except ComponentIntegrityError as exc:
        return {
            "component": component,
            "ready": False,
            "integrity": "state-corrupt",
            "error": str(exc),
        }
    entry = state["components"].get(component)
    if not isinstance(entry, dict):
        return {"component": component, "ready": False, "integrity": "not-installed"}
    relative_root = entry.get("root")
    version = entry.get("version")
    tools = entry.get("tools")
    tool_sha256 = entry.get("tool_sha256")
    expected_root = (
        (PurePosixPath("installed") / component / version).as_posix()
        if isinstance(version, str) and _safe_identifier(version)
        else None
    )
    if (
        not isinstance(relative_root, str)
        or not _safe_relative_path(relative_root)
        or relative_root != expected_root
        or not isinstance(tools, dict)
        or not isinstance(tool_sha256, dict)
    ):
        return {"component": component, "ready": False, "integrity": "state-invalid"}
    installed = root.joinpath(*PurePosixPath(relative_root).parts)
    if (
        (root / "installed").is_symlink()
        or (root / "installed" / component).is_symlink()
        or installed.is_symlink()
        or not installed.is_dir()
    ):
        return {"component": component, "ready": False, "integrity": "root-invalid"}
    try:
        installed_real = installed.resolve()
        installed_real.relative_to(root)
    except (OSError, ValueError):
        return {"component": component, "ready": False, "integrity": "root-escape"}
    resolved_tools: dict[str, str] = {}
    for name, relative in tools.items():
        if (
            not _safe_identifier(str(name))
            or not isinstance(relative, str)
            or not _safe_relative_path(relative)
        ):
            return {
                "component": component,
                "ready": False,
                "integrity": "tool-path-invalid",
            }
        expected_digest = tool_sha256.get(name)
        if (
            not isinstance(expected_digest, str)
            or len(expected_digest) != 64
            or any(ch not in "0123456789abcdef" for ch in expected_digest)
        ):
            return {
                "component": component,
                "ready": False,
                "integrity": "tool-digest-missing",
            }
        tool = installed.joinpath(*PurePosixPath(relative).parts)
        if tool.is_symlink() or not tool.is_file():
            return {"component": component, "ready": False, "integrity": "tool-missing"}
        try:
            tool.resolve().relative_to(installed_real)
        except (OSError, ValueError):
            return {"component": component, "ready": False, "integrity": "tool-escape"}
        try:
            actual_digest = _file_sha256(tool)
        except OSError:
            return {"component": component, "ready": False, "integrity": "tool-unreadable"}
        if actual_digest != expected_digest:
            return {
                "component": component,
                "ready": False,
                "integrity": "tool-digest-mismatch",
            }
        resolved_tools[str(name)] = str(tool)

    payload_problem = verify_payload_inventory(installed, entry.get("payload_files"))
    if payload_problem is not None:
        return {
            "component": component,
            "ready": False,
            "integrity": payload_problem,
        }

    return {
        "component": component,
        "ready": True,
        "integrity": "verified",
        "payload_file_count": len(entry["payload_files"]),
        "version": entry.get("version"),
        "tools": resolved_tools,
        "license": entry.get("license"),
        "provenance": entry.get("provenance"),
    }


def resolve_managed_tool(
    name: str, *, root: Path | None = None, component: str | None = None,
) -> Path | None:
    """Expose the same provider priority as packaged executable resolution."""
    root = (root or _root()).resolve()
    if not _safe_identifier(name):
        return None
    try:
        state = _load_state(root)
    except ComponentIntegrityError:
        return None
    from .managed_tool_resolver import _component_order

    owners = _component_order(state["components"], name, owner=component)
    for owner in owners:
        status = component_status(owner, root=root)
        if status.get("ready") and name in status.get("tools", {}):
            return Path(status["tools"][name])
    return None
