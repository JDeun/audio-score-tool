from __future__ import annotations

import errno
import os
from pathlib import Path
from typing import BinaryIO


class UploadStorageError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 500):
        super().__init__(message)
        self.status_code = status_code


def persist_stream_atomic(
    source: BinaryIO,
    target: Path,
    *,
    chunk_bytes: int = 1024 * 1024,
    max_bytes: int | None = None,
) -> int:
    """Persist an uploaded stream atomically so partial files are never treated as inputs.

    ``max_bytes`` is enforced while reading rather than after persistence. This prevents a
    route-specific upload limit from being bypassed long enough to consume the user's disk.
    The temporary file is removed on every rejected or failed write.
    """
    if chunk_bytes <= 0:
        raise ValueError("chunk_bytes must be positive")
    if max_bytes is not None and max_bytes <= 0:
        raise ValueError("max_bytes must be positive")

    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".uploading")
    total = 0
    try:
        with temp.open("wb") as handle:
            while True:
                read_size = chunk_bytes
                if max_bytes is not None:
                    remaining = max_bytes - total
                    # Read one byte beyond the remaining allowance so oversized streams are
                    # rejected without writing any bytes past the configured route limit.
                    read_size = min(chunk_bytes, remaining + 1)
                chunk = source.read(read_size)
                if not chunk:
                    break
                if max_bytes is not None and total + len(chunk) > max_bytes:
                    raise UploadStorageError(
                        f"입력 파일은 {max_bytes} bytes를 초과할 수 없습니다.",
                        status_code=413,
                    )
                handle.write(chunk)
                total += len(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        temp.replace(target)
        return total
    except UploadStorageError:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    except OSError as exc:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        if exc.errno == errno.ENOSPC:
            raise UploadStorageError(
                "저장 공간이 부족해 입력 파일을 저장하지 못했습니다.",
                status_code=507,
            ) from exc
        if exc.errno in {errno.EACCES, errno.EPERM, errno.EROFS}:
            raise UploadStorageError(
                "입력 파일을 저장할 권한이 없습니다. 데이터 폴더 권한을 확인하세요.",
                status_code=500,
            ) from exc
        raise UploadStorageError(f"입력 파일을 저장하지 못했습니다: {exc}") from exc
