"""ImageAgent — Google Imagen 4 via google-genai SDK."""

from __future__ import annotations

import re
from pathlib import Path

from .. import config as cfg
from .. import cost as cost_tracker
from ..ui import spinner, print_ok, print_error, print_warn


def _prompt_to_filename(prompt: str, max_words: int = 6) -> str:
    words = re.sub(r"[^\w\s]", "", prompt.lower()).split()
    slug = "-".join(words[:max_words]) or "image"
    return f"{slug}.png"


class ImageAgent:
    name = "image"

    def __init__(self):
        self.conf = cfg.load()

    def generate(self, prompt: str, filename: str | None = None) -> Path | None:
        """Generate an image with Imagen 4 and save it. Returns path or None on failure."""
        cfg.ensure_dirs()

        api_key = cfg.get_google_key()
        if not api_key:
            assistant_name = self.conf.get("name", "assistant")
            print_warn(f"No Google API key configured. Run `{assistant_name} config` to set it.")
            return None

        try:
            from google import genai
            from google.genai import types as gentypes

            client = genai.Client(api_key=api_key)

            with spinner(f"generating image: {prompt[:60]}…"):
                response = client.models.generate_images(
                    model="imagen-4.0-generate-001",
                    prompt=prompt,
                    config=gentypes.GenerateImagesConfig(
                        number_of_images=1,
                        aspect_ratio="16:9",
                        output_mime_type="image/png",
                    ),
                )

            if not response.generated_images:
                print_error("No images returned from Imagen.")
                return None

            images_dir = self.conf.get("images_dir") or str(
                Path.home() / "Pictures" / self.conf.get("name", "assistant")
            )
            out_dir = Path(images_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / (filename or _prompt_to_filename(prompt))

            image_bytes = response.generated_images[0].image.image_bytes
            out_path.write_bytes(image_bytes)

            cost_tracker.session.record_image("imagen-4.0-generate-001")
            print_ok(f"Image saved: {out_path}")
            return out_path

        except ImportError:
            print_error("google-genai not installed. Run: pip install 'rogue-assistant[imagen]'")
            return None
        except Exception as e:
            print_error(f"Image generation failed: {e}")
            return None
