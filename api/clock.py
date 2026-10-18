"""The field server's clock, set from the devices that use it.

A Raspberry Pi has no battery-backed clock (a Pi 5 has one only with a cell
fitted), and a field server is usually off any network that could tell it the
time. It boots believing it is whenever it was last shut down, so report
times, audit entries and field-sync times come out days wrong.

Every phone and laptop that opens the console does know the time. So a signed-
in browser sends its clock here once per page load; on the appliance this
writes a hint file that a root service (humint-clock) applies — and only when
the box has no network time and is more than a minute out. Elsewhere (the
Docker deployment, whose host keeps time itself) it does nothing.

Only signed-in users can send one, and every hint the box acts on is audited
with who sent it, so nobody on the field Wi-Fi can move the clock anonymously.
"""
import json
import os
import time

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

import audit
import auth

router = APIRouter(prefix="/api/system", tags=["system"])

# Set by the appliance's unit; unset means "this host keeps its own time".
HINT_FILE = os.environ.get("CLOCK_HINT_FILE", "")
STATE_FILE = os.environ.get("CLOCK_STATE_FILE", "/run/humint/clock.json")
# Below this the box is close enough; above it a hint is worth writing.
THRESHOLD_SECONDS = 60


class TimeHint(BaseModel):
    # The browser's Date.now(), in milliseconds since the epoch.
    client_epoch_ms: int = Field(gt=0)


def _clock_state() -> dict:
    try:
        with open(STATE_FILE) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


@router.post("/time-hint")
def time_hint(payload: TimeHint, user: dict = Depends(auth.require_user)):
    server = time.time()
    client = payload.client_epoch_ms / 1000.0
    offset = client - server
    state = _clock_state()
    if not HINT_FILE:
        return {"managed": False, "offset_seconds": round(offset, 1)}
    if state.get("source") == "ntp" or abs(offset) < THRESHOLD_SECONDS:
        return {"managed": True, "offset_seconds": round(offset, 1), "hint": "not needed",
                "clock": state}
    hint = {"client_epoch": client, "server_epoch": server, "monotonic": time.monotonic(),
            "username": user["username"], "offset_seconds": offset}
    tmp = HINT_FILE + ".tmp"
    os.makedirs(os.path.dirname(HINT_FILE), exist_ok=True)
    with open(tmp, "w") as fh:
        json.dump(hint, fh)
    os.replace(tmp, HINT_FILE)
    audit.record("system.clock_hint", user=user, object_type="system", object_label="clock",
                 detail={"offset_seconds": round(offset, 1)})
    return {"managed": True, "offset_seconds": round(offset, 1), "hint": "sent", "clock": state}


@router.get("/clock")
def clock(user: dict = Depends(auth.require_user)):
    """What the box believes, and where that came from."""
    return {"managed": bool(HINT_FILE), "server_epoch": time.time(), "clock": _clock_state()}
