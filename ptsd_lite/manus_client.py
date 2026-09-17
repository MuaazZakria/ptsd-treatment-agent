"""
Manus API v2 client + event helpers.

Ported from manus-chat-test/app.py. The polling loop (including the grace loop
that waits for the assistant message / structured output to finalize a beat
after agent_status flips to "stopped") is the same, refactored to yield
("event" | "status" | "timing" | "final" | "done", data) tuples instead of SSE
strings.

Latency notes (see HANDOVER-timing-and-audit-reliability.md, open issue 2):
- One `httpx.AsyncClient` is shared across task.create + the whole poll loop
  via `session()`, so we pay the TLS handshake once per run instead of once
  per call.
- The poll loop yields its final event list as ("final", events); the caller
  reuses it instead of re-paginating the whole task with a second
  `fetch_all_events` call.
- The grace loop exits as soon as the structured output is present, because
  that value IS the payload the caller consumes - waiting for the assistant
  *text* to also stabilise afterwards is dead time.
- Polling accelerates only once the structured output is already present,
  since "stopped" follows it within ~0.1s. It is NOT keyed on the assistant
  message: Manus emits those from ~3s into the run, so that signal would
  fast-poll the whole run and eat the 100/min listMessages budget.
- Every message fetch is a FULL re-pagination on purpose: Manus mutates events
  in place (a tool_used goes running -> success), so a cursor-based incremental
  fetch would silently miss those updates and break the live telemetry.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from time import perf_counter
from typing import Any, AsyncIterator

import httpx

from .config import Settings, get_settings

TERMINAL_STATUSES = {"stopped", "error"}

# Poll interval used once the structured output has landed: the flip to
# "stopped" follows it within ~0.1s, so the default 2.5s interval would cost
# ~1.25s of average detection lag for nothing.
_FAST_POLL_S = 0.8
# Grace-loop sleep between checks after the status flips terminal.
_GRACE_SLEEP_S = 0.6
_GRACE_TRIES = 20


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


@asynccontextmanager
async def session(cfg: Settings | None = None) -> AsyncIterator[httpx.AsyncClient]:
    """One keep-alive connection for a whole run (create + poll loop)."""
    cfg = cfg or get_settings()
    async with _client(cfg) as c:
        yield c


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
    client: httpx.AsyncClient | None = None,
) -> dict:
    cfg = cfg or get_settings()
    payload: dict[str, Any] = {"message": {"content": content}}
    if schema is not None:
        payload["structured_output_schema"] = schema
    if agent_profile:
        payload["agent_profile"] = agent_profile
    if client is not None:
        return _unwrap(await client.post("/task.create", json=payload))
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
    task_id: str,
    request: Any,
    cfg: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> AsyncIterator[tuple[str, Any]]:
    """
    Poll task.listMessages and yield:
      ("event", <raw TaskEvent>)   - once per new/changed event
      ("status", <agent_status>)   - once per poll
      ("timing", <dict>)           - phase timings, once, just before "final"
      ("final", <list[dict]>)      - the complete event list; reuse it, do NOT
                                     call fetch_all_events again
      ("done", <agent_status>)     - terminal; iterator then stops
    `request` needs an async `is_disconnected()` (FastAPI Request). Pass any
    object whose is_disconnected() returns False to disable the check.
    """
    cfg = cfg or get_settings()
    sent: dict[str, int] = {}
    elapsed = 0.0
    t_start = perf_counter()
    timing: dict[str, float | int] = {"polls": 0}

    def _eid(e: dict) -> str:
        return str(e.get("id") or f"{e.get('type')}:{e.get('timestamp')}")

    def _changed(e: dict) -> bool:
        h = hash(json.dumps(e, sort_keys=True))
        if sent.get(_eid(e)) == h:
            return False
        sent[_eid(e)] = h
        return True

    owns_client = client is None
    c = client if client is not None else _client(cfg)
    try:
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
        timing["ready_s"] = round(perf_counter() - t_start, 3)

        while True:
            if await request.is_disconnected():
                return
            events = await _fetch_all(c, task_id)
            timing["polls"] = int(timing["polls"]) + 1

            for e in events:
                if _changed(e):
                    yield "event", e
            if "first_event_s" not in timing and events:
                timing["first_event_s"] = round(perf_counter() - t_start, 3)

            status = latest_status(events)
            yield "status", status

            if status in TERMINAL_STATUSES:
                timing["stopped_s"] = round(perf_counter() - t_start, 3)
                t_tail = perf_counter()
                prev = final_text(events)
                stable = 0
                for _ in range(_GRACE_TRIES):
                    # The structured output is the payload the caller actually
                    # consumes, so if it is already here we are done - no need
                    # to keep watching the assistant text settle.
                    if structured_result(events) is not None:
                        break
                    await asyncio.sleep(_GRACE_SLEEP_S)
                    if await request.is_disconnected():
                        return
                    events = await _fetch_all(c, task_id)
                    timing["polls"] = int(timing["polls"]) + 1
                    for e in events:
                        if _changed(e):
                            yield "event", e
                    if latest_status(events) not in TERMINAL_STATUSES:
                        break  # resumed
                    if structured_result(events) is not None:
                        break
                    # No schema configured (or the extractor failed): fall back
                    # to waiting for the assistant text to stop changing.
                    cur = final_text(events)
                    stable = stable + 1 if cur and cur == prev else 0
                    prev = cur
                    if stable >= 2:
                        break
                timing["tail_s"] = round(perf_counter() - t_tail, 3)
                timing["total_s"] = round(perf_counter() - t_start, 3)
                yield "timing", timing
                yield "final", events
                yield "done", latest_status(events)
                return

            # Measured on live runs: structured_output_result lands ~0.1s BEFORE
            # the status flips to "stopped". So the moment we see it, the run is
            # effectively over and a fast poll converts ~1.2s of average
            # detection lag into ~0.4s for the cost of one extra request.
            # Deliberately NOT keyed on assistant_message: Manus emits those
            # from ~3s in, which would fast-poll the entire run and burn the
            # 100/min task.listMessages budget for no gain.
            nearly_done = structured_result(events) is not None
            interval = min(_FAST_POLL_S, cfg.manus_poll_interval_s) if nearly_done else cfg.manus_poll_interval_s
            await asyncio.sleep(interval)
            elapsed += interval
            if elapsed > cfg.manus_stream_max_s:
                timing["total_s"] = round(perf_counter() - t_start, 3)
                yield "timing", timing
                yield "final", events
                yield "done", "timeout"
                return
    finally:
        if owns_client:
            await c.aclose()
