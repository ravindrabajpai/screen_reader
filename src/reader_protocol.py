"""Small, bounded, length-prefixed JSON protocol for the local reader."""

from __future__ import annotations

import json
import math
import socket
import struct

MAX_MESSAGE = 1024 * 1024
VERSION = 1


def send_message(connection: socket.socket, message: dict) -> None:
    payload = json.dumps(message, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(payload) > MAX_MESSAGE:
        raise ValueError("Reading request exceeds the 1 MiB limit. Select less text.")
    connection.sendall(struct.pack("!I", len(payload)) + payload)


def _read(connection: socket.socket, size: int) -> bytes:
    parts = bytearray()
    while len(parts) < size:
        data = connection.recv(size - len(parts))
        if not data:
            raise ValueError("Reader connection closed before a complete message arrived.")
        parts.extend(data)
    return bytes(parts)


def receive_message(connection: socket.socket) -> dict:
    size = struct.unpack("!I", _read(connection, 4))[0]
    if not 0 < size <= MAX_MESSAGE:
        raise ValueError("Invalid message size (maximum 1 MiB).")
    message = json.loads(_read(connection, size))
    if not isinstance(message, dict):
        raise ValueError("Expected a JSON object.")
    return message


def validate_request(message: dict) -> dict:
    if message.get("version") != VERSION:
        raise ValueError("Reader protocol mismatch. Shut down the existing reader and retry.")
    if message.get("type") not in {"speak", "stop", "status", "shutdown"}:
        raise ValueError("Unknown reader command.")
    if message["type"] == "speak":
        for key in ("request_id", "text", "voice", "speech_language", "model_dir"):
            if not isinstance(message.get(key), str) or not message[key].strip():
                raise ValueError(f"Missing or invalid {key}.")
        if len(message["request_id"]) > 128:
            raise ValueError("Request ID is too long.")
        speed = message.get("speed")
        if isinstance(speed, bool) or not isinstance(speed, (int, float)) or not math.isfinite(speed) or not 0.5 <= speed <= 2.0:
            raise ValueError("--speed must be between 0.5 and 2.0")
    return message
