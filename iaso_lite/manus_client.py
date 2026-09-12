"""
Manus API v2 client + event helpers.

Ported from manus-chat-test/app.py. The polling loop (including the grace loop
that waits for the assistant message / structured output to finalize a beat
after agent_status flips to "stopped") is the same, refactored to yield
("event" | "status" | "done", data) tuples instead of SSE strings.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

import httpx

from .config import Settings, get_settings

TERMINAL_STATUSES = {"stopped", "error"}


class ManusError(RuntimeError):
    pass


def _client(cfg: Settings) -> httpx.AsyncClient:
    if not cfg.manus_api_key:
        raise ManusError("MANUS_API_KEY is not set")
    return httpx.AsyncClient(
        base_url=cfg.manus_base_url,
        headers={"Content-Type": "application/json", "x-manus-api-key": cfg.manus_api_key},
        timeout=httpx.Timeout(30.0),
    )


def _unwrap(resp: httpx.Response) -> dict:
    try:
        data = resp.json()
    except ValueError:
        raise ManusError(resp.text or f"non-JSON response from Manus ({resp.status_code})")
    if not data.get("ok", False):
        raise ManusError(json.dumps(data))
    return data


async def create_task(
    content: "str | list",
    schema: dict | None = None,
    agent_profile: str | None = None,
    cfg: Settings | None = None,
) -> dict:
    cfg = cfg or get_settings()
    payload: dict[str, Any] = {"message": {"content": content}}
    if schema is not None:
        payload["structured_output_schema"] = schema
    if agent_profile:
        payload["agent_profile"] = agent_profile
    async with _client(cfg) as c:
        resp = await c.post("/task.create", json=payload)
    return _unwrap(resp)


class TaskNotReady(ManusError):
    """task.create returned, but the task is not queryable yet (propagation lag)."""


async def _fetch_all(c: httpx.AsyncClient, task_id: str) -> list[dict]:
    events: list[dict] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {
            "task_id": task_id,
            "order": "asc",
            "limit": 200,
            "verbose": "true",
        }
        if cursor:
            params["cursor"] = cursor
        resp = await c.get("/task.listMessages", params=params)
        try:
            data = _unwrap(resp)
        except ManusError as exc:
            if "not_found" in str(exc):
                raise TaskNotReady(str(exc)) from None
            raise
        events.extend(data.get("messages", []))
        if data.get("has_more") and data.get("next_cursor"):
            cursor = data["next_cursor"]
        else:
            return events


async def fetch_all_events(task_id: str, cfg: Settings | None = None) -> list[dict]:
    cfg = cfg or get_settings()
    async with _client(cfg) as c:
        return await _fetch_all(c, task_id)


def latest_status(events: list[dict]) -> str:
    status = "running"
    for e in events:
        if e.get("type") == "status_update":
            payload = e.get("status_update") or e
            status = payload.get("agent_status") or status
    return status


def final_text(events: list[dict]) -> str:
    for e in reversed(events):
        if e.get("type") == "assistant_message":
            payload = e.get("assistant_message") or e
            return payload.get("content") or ""
    return ""


def structured_result(events: list[dict]) -> dict | None:
    """The value from the first successful structured_output_result event."""
    for e in events:
        if e.get("type") == "structured_output_result":
            payload = e.get("structured_output_result") or e
            if payload.get("success") is not False and isinstance(payload.get("value"), dict):
                return payload["value"]
    return None


async def stream_task_events(
    task_id: str, request: Any, cfg: Settings | None = None
) -> AsyncIterator[tuple[str, Any]]:
    """
    Poll task.listMessages and yield:
      ("event", <raw TaskEvent>)   - once per new/changed event
      ("status", <agent_status>)   - once per poll
      ("done", <agent_status>)     - terminal; iterator then stops
    `request` needs an async `is_disconnected()` (FastAPI Request). Pass any
    object whose is_disconnected() returns False to disable the check.
    """
    cfg = cfg or get_settings()
    sent: dict[str, int] = {}
    elapsed = 0.0

    def _eid(e: dict) -> str:
        return str(e.get("id") or f"{e.get('type')}:{e.get('timestamp')}")

    def _changed(e: dict) -> bool:
        h = hash(json.dumps(e, sort_keys=True))
        if sent.get(_eid(e)) == h:
            return False
        sent[_eid(e)] = h
        return True

    async with _client(cfg) as c:
        # task.create can return before the task is queryable
        for attempt in range(15):
            try:
                await _fetch_all(c, task_id)
                break
            except TaskNotReady:
                if await request.is_disconnected():
                    return
                await asyncio.sleep(1.5)
        else:
            yield "done", "error"
            return

        while True:
            if await request.is_disconnected():
                return
            events = await _fetch_all(c, task_id)

            for e in events:
                if _changed(e):
                    yield "event", e

            status = latest_status(events)
            yield "status", status

            if status in TERMINAL_STATUSES:
                prev = final_text(events)
                stable = 0
                for _ in range(10):
                    await asyncio.sleep(1.2)
                    if await request.is_disconnected():
                        return
                    events = await _fetch_all(c, task_id)
                    for e in events:
                        if _changed(e):
                            yield "event", e
                    if latest_status(events) not in TERMINAL_STATUSES:
                        break  # resumed
                    cur = final_text(events)
                    stable = stable + 1 if cur and cur == prev else 0
                    prev = cur
                    # stop early once we also have a structured result
                    if stable >= 2 or (stable >= 1 and structured_result(events) is not None):
                        break
                yield "done", latest_status(events)
                return

            await asyncio.sleep(cfg.manus_poll_interval_s)
            elapsed += cfg.manus_poll_interval_s
            if elapsed > cfg.manus_stream_max_s:
                yield "done", "timeout"
                return
