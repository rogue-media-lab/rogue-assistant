"""VideoAgent — Minimax image-to-video and text-to-video generation."""

from __future__ import annotations

import base64
import time
from pathlib import Path

import requests

from .. import config as cfg
from .. import cost as cost_tracker
from ..ui import console, print_error, print_ok, print_warn

API_BASE = "https://api.minimax.io/v1"
DEFAULT_MODEL = "MiniMax-Hailuo-2.3"
POLL_INTERVAL = 5  # seconds between status checks


def _headers() -> dict:
    api_key = cfg.get_minimax_key()
    if not api_key:
        raise RuntimeError("No MiniMax API key — run `wayland config` to add one.")
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _output_dir() -> Path:
    d = Path.home() / "Videos" / cfg.get_name()
    d.mkdir(parents=True, exist_ok=True)
    return d


def generate(
    image_path: str | None = None,
    prompt: str = "",
    duration: int = 6,
    resolution: str = "1080P",
    model: str = DEFAULT_MODEL,
) -> None:
    """Submit an image-to-video (or text-to-video) job and download the result."""
    payload: dict = {
        "model": model,
        "prompt_optimizer": True,
        "duration": duration,
        "resolution": resolution,
    }

    if prompt:
        payload["prompt"] = prompt[:2000]

    if image_path:
        path = Path(image_path).expanduser()
        if not path.exists():
            print_error(f"Image not found: {image_path}")
            return
        suffix = path.suffix.lower().lstrip(".")
        mime = "jpeg" if suffix in ("jpg", "jpeg") else suffix
        encoded = base64.b64encode(path.read_bytes()).decode()
        payload["first_frame_image"] = f"data:image/{mime};base64,{encoded}"
        console.print(f"[dim]Image loaded: {path.name} ({path.stat().st_size // 1024} KB)[/dim]")

    # Submit
    console.print(f"[dim]Submitting video job ({model}, {duration}s, {resolution})…[/dim]")
    try:
        resp = requests.post(f"{API_BASE}/video_generation", json=payload, headers=_headers(), timeout=30)
        resp.raise_for_status()
        result = resp.json()
    except requests.RequestException as e:
        print_error(f"Video submission failed: {e}")
        return

    if result.get("base_resp", {}).get("status_code") != 0:
        print_error(f"Video error: {result.get('base_resp', {}).get('status_msg', 'unknown')}")
        return

    task_id = result.get("task_id")
    if not task_id:
        print_error("No task_id returned.")
        return

    console.print(f"[dim]Task ID: {task_id}[/dim]")

    cost_tracker.session.record_video(model, resolution, duration)

    # Poll
    file_id = _poll(task_id)
    if not file_id:
        return

    # Retrieve download URL
    _download(file_id)


def _poll(task_id: str) -> str | None:
    """Poll until the video job succeeds or fails. Returns file_id on success."""
    import sys
    sys.stdout.write("Processing")
    sys.stdout.flush()
    try:
        while True:
            time.sleep(POLL_INTERVAL)
            resp = requests.get(
                f"{API_BASE}/query/video_generation",
                params={"task_id": task_id},
                headers=_headers(),
                timeout=30,
            )
            resp.raise_for_status()
            result = resp.json()
            status = result.get("status", "")
            sys.stdout.write(".")
            sys.stdout.flush()

            if status == "Success":
                sys.stdout.write("\n")
                sys.stdout.flush()
                return result.get("file_id")
            elif status == "Fail":
                sys.stdout.write("\n")
                sys.stdout.flush()
                print_error("Video generation failed.")
                return None
    except requests.RequestException as e:
        sys.stdout.write("\n")
        sys.stdout.flush()
        print_error(f"Polling failed: {e}")
        return None


def _download(file_id: str) -> None:
    """Retrieve the download URL and save the video locally."""
    try:
        resp = requests.get(
            f"{API_BASE}/files/retrieve",
            params={"file_id": file_id},
            headers=_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
    except requests.RequestException as e:
        print_error(f"File retrieve failed: {e}")
        return

    download_url = result.get("file", {}).get("download_url")
    if not download_url:
        print_error("No download URL in response.")
        return

    filename = result.get("file", {}).get("filename") or f"wayland_{file_id}.mp4"
    out_path = _output_dir() / filename

    console.print(f"[dim]Downloading video…[/dim]")
    try:
        video_resp = requests.get(download_url, timeout=120, stream=True)
        video_resp.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in video_resp.iter_content(chunk_size=8192):
                f.write(chunk)
    except requests.RequestException as e:
        print_error(f"Download failed: {e}")
        return

    print_ok(f"Video saved: {out_path}")
    console.print(f"[dim]Play with: mpv \"{out_path}\"[/dim]")
