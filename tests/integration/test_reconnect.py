"""Reconnect integration tests for the online WebSocket transport."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from server.app import app, reset_room_manager


@pytest.fixture(autouse=True)
def _reset():
    reset_room_manager()
    yield
    reset_room_manager()


def _create_room(client: TestClient, nickname: str = "Alice") -> dict:
    response = client.post("/api/rooms", json={"nickname": nickname})
    assert response.status_code == 200
    return response.json()


def _ws_url(creds: dict) -> str:
    return (
        f"/ws/rooms/{creds['roomCode']}?"
        f"playerId={creds['playerId']}&token={creds['reconnectToken']}"
    )


def _receive_snapshot(ws) -> dict:
    while True:
        message = json.loads(ws.receive_text())
        if message.get("type") == "state_snapshot":
            return message


def test_refresh_reconnect_restores_same_player_seat():
    client = TestClient(app)
    creds = _create_room(client)

    with client.websocket_connect(_ws_url(creds)) as ws:
        first_snapshot = _receive_snapshot(ws)

    with client.websocket_connect(_ws_url(creds)) as ws:
        reconnect_snapshot = _receive_snapshot(ws)

    first_player = first_snapshot["state"]["players"][0]
    reconnected_player = reconnect_snapshot["state"]["players"][0]
    assert reconnected_player["id"] == first_player["id"] == creds["playerId"]
    assert reconnected_player["seat"] == first_player["seat"] == 0
    assert reconnected_player["connected"] is True
    assert reconnected_player["disconnectedAt"] is None
