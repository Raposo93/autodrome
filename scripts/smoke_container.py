#!/usr/bin/env python3
"""Smoke a running Autodrome container from inside its network namespace."""

import json
import os
import subprocess
import urllib.request
from importlib.metadata import version

from websockets.sync.client import connect

from autodrome.config import Config
from autodrome.services.system_status import SystemStatusService


BASE_URL = "http://127.0.0.1:5000"
API_TOKEN = os.environ["API_TOKEN"]


def request(path: str, *, method: str = "GET") -> bytes:
    probe = urllib.request.Request(
        f"{BASE_URL}{path}",
        method=method,
        headers={"Authorization": f"Bearer {API_TOKEN}"},
    )
    with urllib.request.urlopen(probe, timeout=5) as response:
        if response.status not in {200, 201}:
            raise RuntimeError(f"Unexpected status for {path}: {response.status}")
        return response.read()


def main() -> None:
    if os.getuid() == 0:
        raise RuntimeError("Autodrome container is running as root")
    if b'<div id="app"></div>' not in request("/"):
        raise RuntimeError("Container did not serve the compiled frontend")
    if json.loads(request("/api/auth")) != {"authenticated": True}:
        raise RuntimeError("Container API did not authenticate")

    ticket = json.loads(request("/api/auth/ws-ticket", method="POST"))["ticket"]
    with connect(f"ws://127.0.0.1:5000/ws?ticket={ticket}", open_timeout=5) as socket:
        if not isinstance(json.loads(socket.recv(timeout=5)), list):
            raise RuntimeError("Container WebSocket did not return the queue snapshot")

    if version("yt-dlp-ejs") != "0.8.0":
        raise RuntimeError("Container has an unexpected yt-dlp-ejs version")
    subprocess.run(["deno", "--version"], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["ffmpeg", "-version"], check=True, stdout=subprocess.DEVNULL)

    settings = Config()
    if settings.version != f"autodrome/{version('autodrome')}":
        raise RuntimeError("Container is not using installed package version metadata")
    expected_commit = os.getenv("EXPECTED_AUTODROME_COMMIT")
    if expected_commit and SystemStatusService._build_commit() != expected_commit:
        raise RuntimeError("Container does not identify the expected build commit")


if __name__ == "__main__":
    main()
