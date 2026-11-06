"""
Thin wrappers around the two GMI Cloud APIs this app uses.

- Text: OpenAI-compatible chat completions (streamed), default https://api.gmi-serving.com/v1
- Images: the request queue at https://console.gmicloud.ai (submit, poll, download)
"""

import os
import re

import requests
from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError, OpenAI

TEXT_BASE_URL = "https://api.gmi-serving.com/v1"
QUEUE_BASE_URL = os.getenv(
    "GMI_QUEUE_BASE_URL", "https://console.gmicloud.ai/api/v1/ie/requestqueue/apikey"
).rstrip("/")

# Seedream needs at least ~3.7 million pixels per image, so these are the smallest valid sizes.
IMAGE_SIZES = {
    "Square (1:1), for Instagram and X": "2048x2048",
    "Portrait (4:5), for Instagram and LinkedIn": "1728x2160",
    "Landscape (16:9), for X, LinkedIn and blog headers": "2560x1440",
}

THINK_TAGS = re.compile(r"<think>.*?</think>", flags=re.DOTALL | re.IGNORECASE)


class GMIError(Exception):
    """An error with a message that is safe and useful to show to the person using the app."""


def friendly_error(status: int, detail: str = "") -> str:
    if status == 401:
        return "GMI rejected the API key. Check it at console.gmicloud.ai → Settings → API Keys."
    if status == 402:
        return "The GMI account has run out of balance. Add credits in the GMI console and try again."
    if status == 403:
        return "This GMI key isn't allowed to use that model."
    if status == 404:
        return "GMI couldn't find that model. Check the model ID in the app's settings."
    if status == 429:
        return "GMI is limiting requests right now. Wait a minute and try again."
    if status >= 500:
        return "GMI had a temporary problem. Try again in a minute."
    return f"GMI returned an error ({status}). {detail[:200]}".strip()


# --------------------------------------------------------------------------- #
# Text
# --------------------------------------------------------------------------- #

def _client(api_key: str, base_url: str) -> OpenAI:
    return OpenAI(base_url=base_url or TEXT_BASE_URL, api_key=api_key, timeout=180, max_retries=3)  # retries 429s with backoff


def _raise_friendly(e: Exception):
    if isinstance(e, APIStatusError):
        raise GMIError(friendly_error(e.status_code, str(e.message))) from e
    if isinstance(e, APITimeoutError):
        raise GMIError("GMI took too long to answer. Try again.") from e
    if isinstance(e, APIConnectionError):
        raise GMIError("Couldn't connect to GMI. Try again in a moment.") from e
    raise GMIError("GMI sent back something unexpected. Try again.") from e


class ThinkFilter:
    """Removes a leading <think>…</think> block that some reasoning models stream first."""

    def __init__(self):
        self.buf = ""
        self.state = "start"  # start → (thinking →) passthrough

    def feed(self, piece: str) -> str:
        if self.state == "passthrough":
            return piece
        self.buf += piece
        if self.state == "start":
            stripped = self.buf.lstrip()
            if not stripped or "<think>".startswith(stripped):
                return ""  # not enough text yet to decide
            if stripped.startswith("<think>"):
                self.state = "thinking"
            else:
                self.state, out, self.buf = "passthrough", self.buf, ""
                return out
        end = self.buf.find("</think>")
        if end == -1:
            return ""
        out = self.buf[end + len("</think>"):].lstrip()
        self.state, self.buf = "passthrough", ""
        return out

    def flush(self) -> str:
        return self.buf if self.state == "start" else ""


def stream_text(api_key, base_url, model, system, user, max_tokens=1200, temperature=0.6):
    """Yields the answer piece by piece. Raises GMIError with a friendly message on failure."""
    try:
        stream = _client(api_key, base_url).chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
        )
        think = ThinkFilter()
        for chunk in stream:
            if not chunk.choices:
                continue
            out = think.feed(chunk.choices[0].delta.content or "")
            if out:
                yield out
        tail = think.flush()
        if tail:
            yield tail
    except (APIError, APIConnectionError) as e:
        _raise_friendly(e)


def generate_text(api_key, base_url, model, system, user, max_tokens=600, temperature=0.7) -> str:
    try:
        response = _client(api_key, base_url).chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=max_tokens,
            temperature=temperature,
        )
    except (APIError, APIConnectionError) as e:
        _raise_friendly(e)
    text = (response.choices[0].message.content or "") if response.choices else ""
    text = THINK_TAGS.sub("", text).strip()
    if not text:
        raise GMIError("The model sent back an empty answer. Try again.")
    return text


# --------------------------------------------------------------------------- #
# Images (request queue: submit, then poll)
# --------------------------------------------------------------------------- #

def image_payload(model: str, prompt: str, size: str) -> dict:
    """Request body for the image model. Seedream is the default; other models may need other fields."""
    if model.lower().startswith("seedream"):
        return {"prompt": prompt, "size": size, "output_format": "png", "max_images": 1, "watermark": False}
    return {"prompt": prompt, "size": size}


def media_urls(outcome) -> list:
    """GMI returns outcome.media_urls as a list of {"id", "url"} objects; accept plain strings too."""
    urls = []
    for item in (outcome or {}).get("media_urls") or []:
        if isinstance(item, str):
            urls.append(item)
        elif isinstance(item, dict) and item.get("url"):
            urls.append(item["url"])
    return urls


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def start_image(api_key: str, model: str, prompt: str, size: str) -> str:
    try:
        r = requests.post(
            f"{QUEUE_BASE_URL}/requests",
            headers=_headers(api_key),
            json={"model": model, "payload": image_payload(model, prompt, size)},
            timeout=30,
        )
    except requests.RequestException as e:
        raise GMIError("Couldn't connect to GMI to start the image. Try again.") from e
    if r.status_code >= 400:
        raise GMIError(friendly_error(r.status_code, r.text))
    request_id = (r.json() or {}).get("request_id")
    if not request_id:
        raise GMIError("GMI didn't return a request ID for the image.")
    return str(request_id)


def check_image(api_key: str, request_id: str) -> dict:
    """Returns {"status": queued|processing|success|failed|cancelled, "url": str|None}."""
    try:
        r = requests.get(f"{QUEUE_BASE_URL}/requests/{request_id}", headers=_headers(api_key), timeout=30)
    except requests.RequestException:
        return {"status": "processing", "url": None}  # a network blip shouldn't fail the image
    if r.status_code >= 400:
        raise GMIError(friendly_error(r.status_code, r.text))
    data = r.json() or {}
    status = str(data.get("status", "processing")).lower()
    urls = media_urls(data.get("outcome")) if status == "success" else []
    if status == "success" and not urls:
        raise GMIError("The image finished, but GMI didn't return a download link.")
    return {"status": status, "url": urls[0] if urls else None}


def download(url: str) -> tuple:
    try:
        r = requests.get(url, timeout=60)
    except requests.RequestException as e:
        raise GMIError("The image finished but couldn't be downloaded. Try again.") from e
    if r.status_code >= 400:
        raise GMIError("The image finished but couldn't be downloaded. Try again.")
    return r.content, r.headers.get("content-type", "image/png").split(";")[0]
