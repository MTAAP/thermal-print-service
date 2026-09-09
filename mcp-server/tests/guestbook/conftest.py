from __future__ import annotations

import httpx
import pytest

from printer_mcp.guestbook.config import GuestbookConfig
from printer_mcp.hub_client import HubClient


class RecordingHub:
    """Stands in for the Printer Pals hub and records what was sent."""

    def __init__(self, *, status: str = "queued") -> None:
        self.sends: list[dict] = []
        self._status = status

    def client(self) -> HubClient:
        def handler(request: httpx.Request) -> httpx.Response:
            import json
            body = json.loads(request.content)
            self.sends.append(body)
            return httpx.Response(202, json={"results": [
                {"to": h, "status": self._status, "job_id": f"job_{len(self.sends)}"}
                for h in body["to"]
            ]})

        transport = httpx.MockTransport(handler)
        return HubClient("https://hub.test", "tok",
                         http=httpx.AsyncClient(base_url="https://hub.test",
                                                transport=transport))


@pytest.fixture
def cfg(tmp_path) -> GuestbookConfig:
    return GuestbookConfig(
        hub_url="https://hub.test",
        hub_api_token="tok",
        recipient_handle="owner",
        owner_name="Tim",
        tool_name="message_tim",
        state_dir=tmp_path,
        per_guest_per_hour=2,
        global_per_hour=3,
        global_per_day=5,
        max_message_chars=100,
        max_message_lines=5,
        max_art_lines=12,
        max_art_chars=400,
        max_art_cols=52,
    )


@pytest.fixture
def hub() -> RecordingHub:
    return RecordingHub()
