from __future__ import annotations

import errno
import os
from pathlib import Path
from typing import BinaryIO


class UploadStorageError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 500):
        super().__init__(message)
        self.status_code = status_code


def persist_stream_atomic(source: BinaryIO, target: Path, *, chunk_bytes: int = 1024 * 1024) -> int:
    """Persist an uploaded stream atomically so partial files are never treated as inputs."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".uploading")
    total = 0
    try:
        with temp.open("wb") as handle:
            while True:
                chunk = source.read(chunk_bytes)
                if not chunk:
                    break
                handle.write(chunk)
                total += len(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        temp.replace(target)
        return total
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
