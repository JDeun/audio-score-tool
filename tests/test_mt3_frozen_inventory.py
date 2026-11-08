"""Synthetic metadata-only tests for frozen MT3 archive dependency inventory.

No actual native executable, model weight or third-party source is embedded.
"""
from __future__ import annotations

import copy
import hashlib
from email.message import Message
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import collect_mt3_frozen_inventory as inv


class FakeReader:
    def __init__(self, _filename: str):
        self.toc = {
            "PYZ.pyz": (0, 100, 100, 0, "z"),
            "libtorch_cpu.dll": (100, 20, 20, 0, "b"),
            "mt3_infer/config/checkpoints.yaml": (120, 11, 11, 0, "x"),
        }
        self.modules = {
            "mt3_infer.adapters.mr_mt3": (0, 0, 10),
            "torch._C": (0, 10, 10),
            "transformers.models.t5.modeling_t5": (0, 20, 10),
        }

    def open_embedded_archive(self, name: str):
        assert name == "PYZ.pyz"
        return SimpleNamespace(toc=self.modules)


class FakeDistribution:
    def __init__(
        self, root: Path, name: str, version: str, *,
        spdx: str | None = None, notice: str | None = None,
    ):
        self.root = root
        self.metadata = Message()
        self.metadata["Name"] = name
        self.metadata["Version"] = version
        if spdx:
            self.metadata["License-Expression"] = spdx
        self.files = []
        if notice is not None:
            relative = Path(f"{name}-{version}.dist-info/licenses/LICENSE")
            file = root / relative
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(notice, encoding="utf-8")
            self.files.append(relative)

    def locate_file(self, relative: Path):
        return self.root / relative


def _distributions(root: Path):
    names = {
        "mt3-infer": "0.2.0",
        "torch": "2.7.1",
        "torchaudio": "2.7.1",
        "transformers": "4.57.6",
        "PyInstaller": "6.17.0",
        "unreviewed-build-only": "0.9.0",
    }
    return [
        FakeDistribution(
            root, name, version,
            spdx="MIT" if name == "mt3-infer" else None,
            notice="A synthetic license fixture" if name == "torch" else None,
        )
        for name, version in names.items()
    ]


def test_embedded_archive_inventory_records_actual_toc_and_pyz_modules(tmp_path: Path):
    exe = tmp_path / "fake-native.exe"
    exe.write_bytes(b"MZ-not-a-real-binary")
    data = inv.inspect_frozen_archive(exe, reader_factory=FakeReader)
    assert data["archive_entry_count"] == 3
    assert data["native_binary_entry_count"] == 1
    assert data["pyz_module_count"] == 3
    assert data["native_binary_entries"] == ["libtorch_cpu.dll"]
    assert "mt3_infer.adapters.mr_mt3" in data["pyz_modules"]
    assert all("src_path" not in entry for entry in data["archive_entries"])
    assert all("absolute" not in str(entry) for entry in data["archive_entries"])


def test_builder_metadata_separate_from_bundle_and_license_digests(tmp_path: Path):
    builder = inv.inspect_builder_distributions(
        distributions_fn=lambda: _distributions(tmp_path),
    )
    assert builder["distribution_count"] == 6
    assert builder["coverage_scope"] == "builder_environment_not_bundled_runtime_dependency_closure"
    assert "unreviewed-build-only" in builder["missing_license_metadata_names"]
    torch = next(x for x in builder["distributions"] if x["name"] == "torch")
    assert torch["local_notice_digests"][0]["sha256"] == hashlib.sha256(
        b"A synthetic license fixture"
    ).hexdigest()
    assert torch["license_independently_reviewed"] is False


def test_native_inventory_is_hash_bound_and_never_claims_approval(tmp_path: Path):
    exe = tmp_path / "frozen-review.bin"
    exe.write_bytes(b"MZ-fake")
    report = inv.collect_frozen_inventory(
        exe, target="macos-aarch64", reader_factory=FakeReader,
        distributions_fn=lambda: _distributions(tmp_path),
    )
    snapshot = report["snapshot"]
    assert report["inventory_sha256"] == inv._canonical_sha(snapshot)
    assert snapshot["frozen_executable_sha256"] == inv._sha256_file(exe)
    assert snapshot["frozen_archive"]["native_binary_entry_count"] == 1
    assert snapshot["builder"]["distribution_count"] == 6
    mapping = snapshot["native_file_record_hints"]
    assert mapping["mapping_basis"] == "wheel-RECORD-exact-relative-path-only"
    assert mapping["native_filename_candidate_count"] == 1
    assert mapping["unmatched_candidate_count"] == 1
    assert mapping["source_owner_independently_verified"] is False
    assert mapping["binary_payload_equals_record_hash_verified"] is False
    assert snapshot["inventory_is_complete_distributable_sbom"] is False
    assert snapshot["native_library_dependency_closure_independently_verified"] is False
    assert snapshot["third_party_license_approval"] is False
    assert report["legal_reviewer_signoff"] is False
    assert report["redistribution_status"] == "pending"
    assert not any(str(tmp_path) in str(x) for x in snapshot["frozen_archive"]["archive_entries"])
    changed = copy.deepcopy(snapshot)
    changed["frozen_archive"]["archive_entries"][1]["stored_bytes"] += 1
    assert inv._canonical_sha(changed) != report["inventory_sha256"]


@pytest.mark.parametrize("tamper", [
    "absolute_path", "path_traversal", "backslash", "invalid_module",
    "missing_pyz", "missing_native", "duplicated_pyz", "invalid_type",
    "invalid_size", "missing_toc",
])
def test_malformed_frozen_archive_is_rejected(
    tmp_path: Path, tamper: str,
):
    exe = tmp_path / "fake-frozen.bin"
    exe.write_bytes(b"fake")
    class BrokenReader(FakeReader):
        def __init__(self, path):
            super().__init__(path)
            if tamper == "absolute_path":
                self.toc["/etc/passwd"] = self.toc.pop("libtorch_cpu.dll")
            elif tamper == "path_traversal":
                self.toc["../outside"] = self.toc.pop("libtorch_cpu.dll")
            elif tamper == "backslash":
                self.toc["C:\\Windows\\binary.dll"] = self.toc.pop("libtorch_cpu.dll")
            elif tamper == "invalid_module":
                self.modules["../untrusted"] = (0, 1, 1)
            elif tamper == "missing_pyz":
                self.toc.pop("PYZ.pyz")
            elif tamper == "missing_native":
                self.toc.pop("libtorch_cpu.dll")
            elif tamper == "duplicated_pyz":
                self.toc["ANOTHER.pyz"] = (101, 10, 10, 0, "z")
            elif tamper == "invalid_type":
                self.toc["libtorch_cpu.dll"] = (100, 20, 20, 0, "q")
            elif tamper == "invalid_size":
                self.toc["libtorch_cpu.dll"] = (100, -1, 20, 0, "b")
            elif tamper == "missing_toc":
                self.toc = {}

    with pytest.raises(inv.FrozenInventoryError):
        inv.inspect_frozen_archive(exe, reader_factory=BrokenReader)


def test_duplicate_builder_distribution_names_rejected(tmp_path: Path):
    items = _distributions(tmp_path)
    items.append(FakeDistribution(tmp_path, "torch", "2.7.1"))
    with pytest.raises(inv.FrozenInventoryError, match="Duplicate"):
        inv.inspect_builder_distributions(distributions_fn=lambda: items)


def test_unpinned_torch_builder_environment_cannot_enter_receipt(tmp_path: Path):
    exe = tmp_path / "fake-native.exe"
    exe.write_bytes(b"MZ")
    items = _distributions(tmp_path)
    next(x for x in items if x.metadata["Name"] == "torch").metadata.replace_header(
        "Version", "1.0.0",
    )
    with pytest.raises(inv.FrozenInventoryError, match="torch"):
        inv.collect_frozen_inventory(
            exe, target="windows-x86_64",
            reader_factory=FakeReader, distributions_fn=lambda: items,
        )


def test_symlink_executable_is_rejected(tmp_path: Path):
    source = tmp_path / "fake-native.bin"
    source.write_bytes(b"MZ")
    linked = tmp_path / "other.bin"
    linked.symlink_to(source)
    with pytest.raises(inv.FrozenInventoryError, match="regular"):
        inv.inspect_frozen_archive(linked, reader_factory=FakeReader)


def test_windows_relative_archive_separators_normalize_without_hiding_traversal(
    tmp_path: Path,
):
    exe = tmp_path / "fake-windows-frozen.exe"
    exe.write_bytes(b"MZ-test")
    class NativeWindowsReader(FakeReader):
        def __init__(self, path):
            super().__init__(path)
            self.toc["torch\\lib\\libtorch_cpu.dll"] = self.toc.pop("libtorch_cpu.dll")
            self.toc["mt3_infer\\config\\checkpoints.yaml"] = self.toc.pop(
                "mt3_infer/config/checkpoints.yaml"
            )

    result = inv.inspect_frozen_archive(exe, reader_factory=NativeWindowsReader)
    assert "torch/lib/libtorch_cpu.dll" in result["native_binary_entries"]
    assert "mt3_infer/config/checkpoints.yaml" in {
        entry["name"] for entry in result["archive_entries"]
    }
    assert all("\\" not in entry["name"] for entry in result["archive_entries"])


@pytest.mark.parametrize("name", (
    "..\\escape.dll", "\\\\server\\share\\escape.dll",
    "\\rooted.dll", "C:\\windows\\system32\\escape.dll", "lib\\..\\escape.dll",
    "lib\\\\escape.dll",
))
def test_windows_archive_traversal_and_absolute_paths_are_rejected(
    tmp_path: Path, name: str,
):
    exe = tmp_path / "fake-windows-frozen.exe"
    exe.write_bytes(b"MZ-test")
    class BrokenWindowsReader(FakeReader):
        def __init__(self, path):
            super().__init__(path)
            self.toc[name] = self.toc.pop("libtorch_cpu.dll")

    with pytest.raises(inv.FrozenInventoryError, match="escape"):
        inv.inspect_frozen_archive(exe, reader_factory=BrokenWindowsReader)


def test_windows_archive_duplicate_normalized_paths_are_rejected(tmp_path: Path):
    exe = tmp_path / "fake-windows-frozen.exe"
    exe.write_bytes(b"MZ-test")
    class DuplicateWindowsReader(FakeReader):
        def __init__(self, path):
            super().__init__(path)
            self.toc["torch\\lib.dll"] = (120, 9, 9, 0, "b")
            self.toc["torch/lib.dll"] = (140, 11, 11, 0, "b")
    with pytest.raises(inv.FrozenInventoryError, match="duplicated"):
        inv.inspect_frozen_archive(exe, reader_factory=DuplicateWindowsReader)

