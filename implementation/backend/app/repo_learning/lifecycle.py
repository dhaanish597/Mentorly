"""Process-local import cancellation; SQLite publication remains the final fence."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from threading import Lock


@dataclass(frozen=True)
class ImportTask:
    workspace: str
    loop: asyncio.AbstractEventLoop
    task: asyncio.Task


_TASKS: dict[tuple[str, str], ImportTask] = {}
_LOCK = Lock()


def register(db_path: str, snapshot_id: str, workspace: str) -> None:
    task = asyncio.current_task()
    if task is None:
        raise RuntimeError('repository import requires an async task')
    with _LOCK:
        _TASKS[(str(db_path), snapshot_id)] = ImportTask(workspace, asyncio.get_running_loop(), task)


def unregister(db_path: str, snapshot_id: str) -> None:
    with _LOCK:
        _TASKS.pop((str(db_path), snapshot_id), None)


def cancel_import(db_path: str, snapshot_id: str) -> None:
    with _LOCK:
        entry = _TASKS.pop((str(db_path), snapshot_id), None)
    if entry is not None and not entry.loop.is_closed():
        try:
            entry.loop.call_soon_threadsafe(entry.task.cancel)
        except RuntimeError:
            logging.getLogger(__name__).warning('Repository import loop closed during cancellation')


def cancel_workspace(db_path: str, workspace: str) -> None:
    with _LOCK:
        snapshots = [snapshot for (db, snapshot), entry in _TASKS.items() if db == str(db_path) and entry.workspace == workspace]
    for snapshot in snapshots:
        cancel_import(db_path, snapshot)


def active_imports(db_path: str) -> list[str]:
    with _LOCK:
        return [snapshot for db, snapshot in _TASKS if db == str(db_path)]
