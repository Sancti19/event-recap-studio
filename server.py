"""
Event Recap Studio: web server for GMI Agentbox (or any Docker host).

- Serves the web page at /
- /health for health checks
- /api/text streams one recap format from a GMI text model
- /api/graphic starts a recap graphic on a GMI image model; the page polls for it

On Agentbox, turn on MaaS integration: GMI injects GMI_MAAS_API_KEY and GMI_MAAS_BASE_URL,
so no key needs to live in the image. See README.md for every setting.
"""

import hmac
import logging
import os
import queue
import re
import threading
import time
from collections import OrderedDict, defaultdict, deque
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

import gmi
import prompts

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("recap-studio")


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def env_int(name: str, default: int) -> int:
    try:
        return int(env(name, str(default)))
    except ValueError:
        return default


MEDIA_WORDS = re.compile(r"seedream|image|video|tts|speech|music|flux|kling|veo|sora|audio", re.I)


def first_text_model(models: str) -> str:
    for model in re.split(r"[,;\s]+", models):
        if model and not MEDIA_WORDS.search(model):
            return model
    return ""


# Keys: Agentbox injects GMI_MAAS_API_KEY when MaaS integration is on. GMI_API_KEY is an optional
# override (useful if the injected key can't reach the image request queue).
MAAS_KEY = env("GMI_MAAS_API_KEY")
TEXT_KEY = MAAS_KEY or env("GMI_API_KEY")
IMAGE_KEY = env("GMI_API_KEY") or MAAS_KEY
TEXT_BASE_URL = env("TEXT_BASE_URL") or (env("GMI_MAAS_BASE_URL") if MAAS_KEY else "") or gmi.TEXT_BASE_URL
TEXT_MODEL = env("TEXT_MODEL") or first_text_model(env("GMI_MODELS")) or "deepseek-ai/DeepSeek-V3.2"
IMAGE_MODEL = env("IMAGE_MODEL") or "seedream-5.0-lite"
AI_IMAGES = IMAGE_MODEL.lower() not in ("none", "off", "false", "0")  # IMAGE_MODEL=none → free recap card only
ACCESS_CODE = env("ACCESS_CODE")
ALLOW_USER_KEYS = env("ALLOW_USER_KEYS", "true").lower() not in ("0", "false", "no")
MAX_CALLS_PER_HOUR = env_int("MAX_CALLS_PER_HOUR", 60)
# How many AI calls run at once on the host's key. Free models may be rate-limited, so 1 is safest there.
MAX_PARALLEL = max(1, env_int("MAX_PARALLEL", 3))
model_slots = threading.BoundedSemaphore(MAX_PARALLEL)

ERROR_MARK = "[[RECAP_ERROR]]"
STATIC = Path(__file__).parent / "static"

@asynccontextmanager
async def lifespan(_: FastAPI):
    log.info(
        "Text model %s via %s (key from %s) · image model %s · access code %s · %s calls/hour per visitor · %s at once",
        TEXT_MODEL,
        TEXT_BASE_URL,
        "GMI_MAAS_API_KEY" if MAAS_KEY else ("GMI_API_KEY" if TEXT_KEY else "visitors only"),
        IMAGE_MODEL if AI_IMAGES else "off (free recap card only)",
        "on" if ACCESS_CODE else "off",
        MAX_CALLS_PER_HOUR,
        MAX_PARALLEL,
    )
    yield


app = FastAPI(title="Event Recap Studio", docs_url=None, redoc_url=None, lifespan=lifespan)


# --------------------------------------------------------------------------- #
# Limits and keys
# --------------------------------------------------------------------------- #

class HourlyLimiter:
    def __init__(self, limit: int):
        self.limit = limit
        self.hits = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, who: str) -> bool:
        now = time.time()
        with self.lock:
            q = self.hits[who]
            while q and now - q[0] > 3600:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True


limiter = HourlyLimiter(MAX_CALLS_PER_HOUR)


def take_slot() -> None:
    """Waits for a free model slot, so free (rate-limited) models get calls one or two at a time."""
    if not model_slots.acquire(timeout=150):
        raise HTTPException(503, "The app is busy right now. Try regenerating in a minute.")


@contextmanager
def slot():
    take_slot()
    try:
        yield
    finally:
        model_slots.release()


def visitor(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def same(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def resolve_key(request: Request, kind: str, count: bool = True) -> tuple:
    """Returns (api_key, text_base_url). Visitor keys skip the host's code and limits."""
    own = request.headers.get("x-gmi-key", "").strip()
    if own and ALLOW_USER_KEYS:
        return own, env("TEXT_BASE_URL") or gmi.TEXT_BASE_URL  # visitors use the public API

    host_key = TEXT_KEY if kind == "text" else IMAGE_KEY
    if not host_key:
        raise HTTPException(400, "This app has no GMI key of its own. Add your GMI API key under Settings.")
    if ACCESS_CODE and not same(request.headers.get("x-access-code", "").strip(), ACCESS_CODE):
        raise HTTPException(401, "Enter the access code under Settings.")
    if count and not limiter.allow(visitor(request)):
        extra = " or add your own GMI key under Settings" if ALLOW_USER_KEYS else ""
        raise HTTPException(429, f"You've reached this app's limit of {MAX_CALLS_PER_HOUR} AI calls per hour. Try again later{extra}.")
    return host_key, TEXT_BASE_URL


# --------------------------------------------------------------------------- #
# Request bodies
# --------------------------------------------------------------------------- #

def text_field(limit: int = 20_000):
    return Field(default="", max_length=limit)


class EventForm(BaseModel):
    name: str = text_field(300)
    event_type: str = text_field(100)
    date: str = text_field(200)
    location: str = text_field(300)
    organizer: str = text_field(300)
    partners: str = text_field(1000)
    audience: str = text_field(500)
    speakers: str = text_field()
    results: str = text_field()
    highlights: str = text_field()
    notes: str = text_field(60_000)
    thanks: str = text_field(2000)
    cta: str = text_field(2000)
    tags: str = text_field(500)


class TextRequest(BaseModel):
    form: EventForm
    format: str
    language: str = Field(default="English", max_length=60)
    tone: str = Field(default="Friendly & warm", max_length=60)


class GraphicRequest(BaseModel):
    form: EventForm
    style: str = Field(default="Bold & modern", max_length=60)
    aspect: str = Field(default=list(gmi.IMAGE_SIZES)[0], max_length=100)
    include_title: bool = True


class CardRequest(BaseModel):
    form: EventForm
    language: str = Field(default="English", max_length=60)


def check_form(form: EventForm) -> None:
    if not form.name.strip():
        raise HTTPException(400, "Give the event a name.")
    if not any(getattr(form, k).strip() for k in ("speakers", "results", "highlights", "notes")):
        raise HTTPException(400, "Add some sessions, results, highlights or notes so there's something to write about.")


REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{6,80}$")


def check_request_id(request_id: str) -> None:
    if not REQUEST_ID.match(request_id):
        raise HTTPException(400, "That isn't a valid image request.")


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #

@app.get("/", include_in_schema=False)
def page():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/config")
def config():
    return {
        "formats": [{"key": k, "label": v["label"], "help": v["help"]} for k, v in prompts.FORMATS.items()],
        "graphic_label": prompts.GRAPHIC_LABEL,
        "languages": prompts.LANGUAGES,
        "tones": list(prompts.TONES),
        "event_types": prompts.EVENT_TYPES,
        "image_styles": list(prompts.IMAGE_STYLES),
        "image_sizes": list(gmi.IMAGE_SIZES),
        "host_key": bool(TEXT_KEY),
        "access_code": bool(ACCESS_CODE),
        "allow_user_keys": ALLOW_USER_KEYS,
        "text_model": TEXT_MODEL,
        "image_model": IMAGE_MODEL if AI_IMAGES else "",
        "ai_images": AI_IMAGES,
        "card_themes": prompts.CARD_THEMES,
    }


@app.post("/api/text")
def text(req: TextRequest, request: Request):
    if req.format not in prompts.FORMATS:
        raise HTTPException(400, "Unknown recap format.")
    check_form(req.form)
    api_key, base_url = resolve_key(request, "text")

    brief = prompts.build_brief(req.form.model_dump())
    pieces = gmi.stream_text(
        api_key,
        base_url,
        TEXT_MODEL,
        prompts.system_prompt(req.language.strip() or "English", req.tone),
        prompts.user_prompt(brief, req.format),
        max_tokens=prompts.FORMATS[req.format]["max_tokens"],
    )
    take_slot()
    try:
        first = next(pieces)  # surfaces key, balance and model errors before the stream starts
    except StopIteration:
        model_slots.release()
        raise HTTPException(502, "The model sent back an empty answer. Try regenerating.")
    except gmi.GMIError as e:
        model_slots.release()
        raise HTTPException(502, str(e))
    except BaseException:
        model_slots.release()
        raise

    # Read the rest of the answer in a worker thread, so the model slot is always released when
    # GMI finishes, even if the visitor closes the tab halfway through.
    out: "queue.Queue[str | None]" = queue.Queue()

    def pump():
        try:
            for piece in pieces:
                out.put(piece)
        except gmi.GMIError as e:
            out.put(f"\n\n{ERROR_MARK}{e}")
        except Exception:
            log.exception("Stream failed")
            out.put(f"\n\n{ERROR_MARK}The connection to GMI dropped. Try regenerating.")
        finally:
            model_slots.release()
            out.put(None)

    threading.Thread(target=pump, daemon=True).start()

    def body():
        yield first
        while (piece := out.get()) is not None:
            yield piece

    return StreamingResponse(
        body(),
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/graphic")
def graphic(req: GraphicRequest, request: Request):
    if not AI_IMAGES:
        raise HTTPException(400, "AI artwork is turned off on this app. Use the free recap card instead.")
    check_form(req.form)
    if req.aspect not in gmi.IMAGE_SIZES:
        raise HTTPException(400, "Unknown graphic format.")
    text_key, base_url = resolve_key(request, "text")
    image_key, _ = resolve_key(request, "image", count=False)

    brief = prompts.build_brief(req.form.model_dump())
    try:
        with slot():
            image_prompt = gmi.generate_text(
                text_key,
                base_url,
                TEXT_MODEL,
                "You are an art director who writes precise, vivid prompts for AI image generators.",
                prompts.graphic_prompt_request(brief, req.style, req.aspect, req.form.name, req.include_title),
                max_tokens=400,
                temperature=0.8,
            )
        request_id = gmi.start_image(image_key, IMAGE_MODEL, image_prompt, gmi.IMAGE_SIZES[req.aspect])
    except gmi.GMIError as e:
        raise HTTPException(502, str(e))
    return {"request_id": request_id, "prompt": image_prompt}


@app.post("/api/card")
def card(req: CardRequest, request: Request):
    """Text for the free recap card. The browser draws the card itself, so no image model is needed."""
    check_form(req.form)
    form = req.form.model_dump()
    brief = prompts.build_brief(form)
    try:
        api_key, base_url = resolve_key(request, "text")
        with slot():
            raw = gmi.generate_text(
                api_key, base_url, TEXT_MODEL, prompts.CARD_SYSTEM,
                prompts.card_request(brief, req.language.strip() or "English"),
                max_tokens=500, temperature=0.4,
            )
        return prompts.parse_card(raw, form, brief)
    except (gmi.GMIError, HTTPException) as e:
        # Still give people a card, built straight from what they typed.
        log.warning("Recap card fell back to form data: %s", getattr(e, "detail", e))
        return prompts.card_from_form(form)


IMAGE_CACHE: "OrderedDict[str, tuple]" = OrderedDict()
IMAGE_CACHE_SIZE = 30


@app.get("/api/graphic/{request_id}")
def graphic_status(request_id: str, request: Request):
    check_request_id(request_id)
    api_key, _ = resolve_key(request, "image", count=False)
    try:
        status = gmi.check_image(api_key, request_id)
    except gmi.GMIError as e:
        raise HTTPException(502, str(e))
    return {"status": status["status"]}


@app.get("/api/graphic/{request_id}/image")
def graphic_image(request_id: str, request: Request):
    check_request_id(request_id)
    api_key, _ = resolve_key(request, "image", count=False)
    if request_id not in IMAGE_CACHE:
        try:
            status = gmi.check_image(api_key, request_id)
            if status["status"] != "success":
                raise HTTPException(409, "The image isn't ready yet.")
            IMAGE_CACHE[request_id] = gmi.download(status["url"])
        except gmi.GMIError as e:
            raise HTTPException(502, str(e))
        while len(IMAGE_CACHE) > IMAGE_CACHE_SIZE:
            IMAGE_CACHE.popitem(last=False)
    content, media_type = IMAGE_CACHE[request_id]
    return Response(content, media_type=media_type, headers={"Cache-Control": "private, max-age=3600"})

