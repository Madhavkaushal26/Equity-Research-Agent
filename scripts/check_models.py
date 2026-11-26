"""Check Gemini access and select an available Flash model if the configured ID is unsupported."""

import argparse
import asyncio
from pathlib import Path

from dotenv import dotenv_values, set_key
from google import genai
from google.genai import errors, types


async def verify(list_only: bool = False, preferred_model: str | None = None) -> None:
    path = Path(".env")
    values = dotenv_values(path)
    key = values["GEMINI_API_KEY"]
    model = preferred_model or values["GEMINI_MODEL"]
    async with genai.Client(api_key=key, http_options=types.HttpOptions(
        timeout=20000, retry_options=types.HttpRetryOptions(attempts=1),
    )).aio as client:
        if list_only:
            async for item in await client.models.list():
                if item.name and "flash" in item.name:
                    print(item.name, item.supported_actions, flush=True)
            return

        async def probe(name: str) -> None:
            for attempt in range(2):
                try:
                    await client.models.generate_content(
                        model=name, contents="Reply with OK.",
                        config=types.GenerateContentConfig(max_output_tokens=64),
                    )
                    return
                except errors.APIError as exc:
                    if exc.code not in (429, 500, 502, 503, 504) or attempt == 1:
                        raise
                    delay = 2 ** (attempt + 1)
                    print(f"Transient Gemini HTTP {exc.code}; retrying in {delay}s.", flush=True)
                    await asyncio.sleep(delay)

        try:
            await probe(model)
        except errors.APIError as exc:
            message = str(exc).replace(key, "[redacted]")
            if exc.code not in (400, 404, 500, 502, 503, 504):
                raise SystemExit(message) from None
            print(f"Configured model {model} is unavailable: {message}. Inspecting available models.", flush=True)
            available = []
            async for item in await client.models.list():
                if item.name and "flash" in item.name and not any(kind in item.name for kind in ("tts", "image", "audio", "live")) and "generateContent" in (item.supported_actions or []):
                    available.append(item.name.removeprefix("models/"))
            print("Available Flash models: " + ", ".join(available), flush=True)
            candidates = list(dict.fromkeys(["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-2.5-flash-lite", "gemini-3.6-flash", "gemini-3.5-flash", "gemini-2.5-flash", *available]))
            for candidate in candidates:
                if candidate not in available or candidate == model:
                    continue
                try:
                    await probe(candidate)
                except errors.APIError as probe_error:
                    print(f"Model {candidate}: {str(probe_error).replace(key, '[redacted]')}", flush=True)
                    if probe_error.code in (400, 404, 500, 502, 503, 504):
                        continue
                    raise SystemExit(str(probe_error).replace(key, "[redacted]")) from None
                model = candidate
                break
            else:
                raise SystemExit("No available Flash model passed the live request")
        response = await client.models.embed_content(
            model=values["EMBEDDING_MODEL"], contents=["NVIDIA revenue drivers"],
            config=types.EmbedContentConfig(output_dimensionality=768),
        )
        assert response.embeddings and len(response.embeddings[0].values) == 768
    if model != values["GEMINI_MODEL"]:
        set_key(path, "GEMINI_MODEL", model)
    print(f"Gemini generation verified: {model}. Embeddings verified: 768 dimensions.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-only", action="store_true")
    parser.add_argument("--model", help="Verify and save a specific available Flash model")
    args = parser.parse_args()
    asyncio.run(verify(args.list_only, args.model))
