from __future__ import annotations

from fastapi import APIRouter

from . import song_routes as implementation
from .job_ingestion import reconcile_completed_jobs


def _sync() -> None:
    reconcile_completed_jobs(
        job_store=implementation._job_store,
        song_store=implementation._song_store,
        tombstones=implementation._tombstones,
        batch_size=200,
        max_batches=1,
    )
    # Preserve publication-default initialization from the original implementation.
    for song in implementation._song_store.list():
        if implementation._publication_store.exists(song["song_id"]):
            continue
        settings = implementation._publication_store.write(
            song["song_id"], implementation.merged_publication_settings(None)
        )
        path = implementation._song_store.checkout_current(song["song_id"])
        try:
            implementation.apply_publication_layout(
                path,
                title=song["title"],
                settings=settings,
            )
            implementation._song_store.replace_current_from_path(song["song_id"], path)
        except Exception:
            implementation._song_store.checkout_current(song["song_id"])


# The implementation's route handlers resolve `_sync` from their module globals at
# execution time, so replacing that hook upgrades all song reads without duplicating
# the large editing implementation.
implementation._sync = _sync

# Dedicated hardened routers own these mutations. Build a canonical song router that
# contains only the remaining song read/edit endpoints from the implementation.
_REPLACED = {
    ("POST", "/api/songs/{song_id}/export"),
    ("DELETE", "/api/songs/{song_id}"),
    ("PATCH", "/api/songs/{song_id}"),
    ("POST", "/api/songs/{song_id}/undo"),
    ("PATCH", "/api/songs/{song_id}/publication"),
}

router = APIRouter(tags=["songs"])
for route in implementation.router.routes:
    methods = getattr(route, "methods", None) or set()
    path = getattr(route, "path", "")
    if any((method, path) in _REPLACED for method in methods):
        continue
    router.routes.append(route)
