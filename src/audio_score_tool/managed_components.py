from __future__ import annotations

import hashlib
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
    if (
        parsed.scheme.lower() != "https"
        or parsed.username
        or parsed.password
        or not parsed.hostname
        or parsed.fragment
    ):
        raise ComponentIntegrityError(
            "Managed component downloads must use credential-free HTTPS URLs without fragments."
        )
    return parsed


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
        if len(self.sha256) != 64 or any(ch not in "0123456789abcdef" for ch in self.sha256.lower()):
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


def recover_component_staging(root: Path | None = None) -> dict[str, int]:
    root = (root or _root()).resolve()
    removed = 0
    for path in root.glob(".staging-*"):
        try:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
            removed += 1
        except OSError:
            continue
    for path in root.glob(".download-*"):
        try:
            path.unlink(missing_ok=True)
            removed += 1
        except OSError:
            continue
    return {"removed_component_staging": removed}


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


def _download(artifact: ComponentArtifact, target: Path) -> str:
    _validated_download_url(artifact.url)
    request = urllib.request.Request(
        artifact.url,
        headers={"User-Agent": "AudioScoreTool-managed-component/1"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            # urllib follows redirects. Re-validate the final URL so a trusted HTTPS
            # catalog endpoint cannot redirect installation to file/http/credential URLs.
            _validated_download_url(str(response.geturl()))
            return _copy_stream(response, target, max_bytes=artifact.max_download_bytes)
    except ComponentError:
        raise
    except Exception as exc:  # urllib raises several transport-specific exception types
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


def _verify_tools(artifact: ComponentArtifact, staged: Path) -> dict[str, str]:
    resolved: dict[str, str] = {}
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
    return resolved


def install_component_artifact(
    artifact: ComponentArtifact,
    *,
    root: Path | None = None,
    local_archive: Path | None = None,
) -> dict:
    # __post_init__ protects direct dataclass callers in addition to catalog callers.
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
        backup = install_root / f".previous-{token}"
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
            tools = _verify_tools(artifact, staged)
            install_root.mkdir(parents=True, exist_ok=True)
            if final.exists():
                if final.is_symlink() or not final.is_dir():
                    raise ComponentIntegrityError(
                        "Existing managed component installation root is unsafe."
                    )
                if backup.exists():
                    shutil.rmtree(backup, ignore_errors=True)
                final.replace(backup)
            try:
                staged.replace(final)
                final_activated = True
            except BaseException:
                if backup.exists() and not final.exists():
                    backup.replace(final)
                raise

            state = _load_state(root)
            components = dict(state["components"])
            components[artifact.component] = {
                "version": artifact.version,
                "root": str(final.relative_to(root).as_posix()),
                "tools": tools,
                "sha256": artifact.sha256,
                "license": artifact.license,
                "provenance": artifact.provenance,
            }
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
    tools = entry.get("tools")
    if (
        not isinstance(relative_root, str)
        or not _safe_relative_path(relative_root)
        or not isinstance(tools, dict)
    ):
        return {"component": component, "ready": False, "integrity": "state-invalid"}
    installed = root.joinpath(*PurePosixPath(relative_root).parts)
    if installed.is_symlink() or not installed.is_dir():
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
        tool = installed.joinpath(*PurePosixPath(relative).parts)
        if tool.is_symlink() or not tool.is_file():
            return {"component": component, "ready": False, "integrity": "tool-missing"}
        try:
            tool.resolve().relative_to(installed_real)
        except (OSError, ValueError):
            return {"component": component, "ready": False, "integrity": "tool-escape"}
        resolved_tools[str(name)] = str(tool)
    return {
        "component": component,
        "ready": True,
        "integrity": "verified",
        "version": entry.get("version"),
        "tools": resolved_tools,
        "license": entry.get("license"),
        "provenance": entry.get("provenance"),
    }


def resolve_managed_tool(name: str, *, root: Path | None = None) -> Path | None:
    root = (root or _root()).resolve()
    if not _safe_identifier(name):
        return None
    try:
        state = _load_state(root)
    except ComponentIntegrityError:
        return None
    for component in state["components"]:
        status = component_status(component, root=root)
        if status.get("ready") and name in status.get("tools", {}):
            return Path(status["tools"][name])
    return None
