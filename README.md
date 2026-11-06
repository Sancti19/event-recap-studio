# 🎤 Event Recap Studio

**Turn event notes into ready-to-post recaps in about a minute, built on GMI Cloud.**

You fill in what happened at an event, or paste your messy notes, and Event Recap Studio writes:

| Output | What you get |
|---|---|
| 🧵 X thread | 5 to 8 posts, each with a character counter and its own copy button |
| 💼 LinkedIn post | 150 to 300 words, with a hook line and hashtags |
| 📝 Blog recap | 500 to 800 words in Markdown, ready for Medium |
| 📣 Community update | A short post for Telegram, WhatsApp or Discord |
| 🙏 Thank-you note | For attendees, speakers and partners |
| 📊 Partner report | An outcomes brief for the protocol or sponsor that backed the event |
| 🎨 Recap graphic | A **free recap card** your browser draws from your numbers, or **AI artwork** from a GMI image model. Both come in square, portrait or landscape. |

It writes in English, French, Kiswahili, Kinyarwanda, Portuguese, Spanish, Arabic or any language you type, in four tones. It only uses the facts you give it, so it won't invent numbers, quotes or links. Problems from your raw notes, such as a late start or bad Wi-Fi, stay out of the public posts and only show up as learnings in the partner report.

## How it uses GMI Cloud

- **GMI Agentbox** hosts the app: GMI runs the container and gives it a public URL.
- **GMI Inference Engine (MaaS)** writes the text. Each format streams from a GMI text model through the OpenAI-compatible API. On Agentbox, the key is injected automatically.
- **The recap card** is free: a GMI text model picks the headline and the top three numbers, then your browser draws the card. Any number that isn't in your notes is thrown out, so the card can't invent results.
- **AI artwork** is optional and uses credits: a GMI text model writes the image prompt, then a GMI image model (`seedream-5.0-lite` by default) paints it through the request queue.

```
Browser ──► Agentbox container (FastAPI, port 8080)
              ├─► GMI chat completions (streamed)       → 6 text formats
              ├─► GMI chat completions (short JSON)     → free recap card, drawn in the browser
              └─► GMI request queue (submit, then poll) → optional AI artwork
```

## Run it for $0

All three pieces have a free option:

- **Text:** set `TEXT_MODEL` to a model that Model Hub marks **FREE**. Free endpoints may be rate-limited, so also set `MAX_PARALLEL=1`.
- **Graphic:** use the recap card, and set `IMAGE_MODEL=none` to hide the AI artwork option.
- **Hosting:** run the same repo on a free Docker host such as Render.

On Render, choose **New → Web Service**, pick this repo (Render finds the Dockerfile), and choose the **Free** instance type. Then add the environment variables `GMI_API_KEY`, `TEXT_MODEL`, `IMAGE_MODEL=none` and `MAX_PARALLEL=1`, and set the health check path to `/health`. Render's free services go to sleep after 15 minutes without visitors and take about a minute to wake up.

When you have credits, the same image moves to Agentbox unchanged.

## Deploy on GMI Agentbox

**1. Publish the image.** Push this repo to GitHub on the `main` branch. The **Publish Agentbox image** workflow in `.github/workflows/` builds the container and pushes it to `ghcr.io/<your-github-username>/<repo-name>:latest`. Then make the package public: on GitHub, go to your profile → **Packages** → this package → **Package settings** → **Change visibility** → **Public**.

**2. Register it in Agentbox.** In console.gmicloud.ai, open **Agentbox** → **Register an agent**:

| Wizard step | Setting |
|---|---|
| Basics & Template | A name and description. Choose **GMI CE Deployment**, so GMI hosts the container. |
| Infrastructure | Image URL `ghcr.io/<you>/<repo>:latest`, credentials **off**, tier **Container**, any region. Turn **MaaS integration on** and pick your text model. |
| Networking | Port mapping **443 → 8080** |
| Env Variables | Optional. See `agentbox.env.example`, and mark `ACCESS_CODE` and `GMI_API_KEY` as **SECRET**. |
| Review & Register | Register. The agent is saved as a private draft. |

**3. Launch it.** From the agent's **Monitor** tab, launch an instance and open its URL. `https://<your-url>/health` should return `{"ok": true}`.

## Settings (environment variables)

| Variable | Default | What it does |
|---|---|---|
| `GMI_MAAS_API_KEY`, `GMI_MAAS_BASE_URL` | injected by Agentbox | The key and endpoint for text calls. Don't set these yourself on Agentbox. |
| `TEXT_MODEL` | `deepseek-ai/DeepSeek-V3.2` (or the first text model from MaaS) | Any chat model ID from Model Hub |
| `IMAGE_MODEL` | `seedream-5.0-lite` | The image model ID for AI artwork. `none` turns AI artwork off, which leaves only the free recap card. For non-Seedream models, update `image_payload()` in `gmi.py`. |
| `GMI_API_KEY` | none | Optional. A normal GMI key, used for images and as a text fallback, for example when running outside Agentbox. |
| `ACCESS_CODE` | none | Visitors must enter this code to use your credits |
| `MAX_PARALLEL` | `3` | How many AI calls run at once on the host's key. Use `1` for free models, which may be rate-limited. |
| `MAX_CALLS_PER_HOUR` | `60` | AI calls one visitor can make per hour on your credits. A full recap uses 7. |
| `ALLOW_USER_KEYS` | `true` | Lets visitors paste their own GMI key, which bills their account and skips your code and limit |
| `TEXT_BASE_URL` | GMI's public API | Overrides the text endpoint |

## Run it on your computer

Use Python 3.10 or newer.

```bash
pip install -r requirements.txt
GMI_API_KEY=your-key uvicorn server:app --port 8080
```

Then open http://localhost:8080. With Docker instead:

```bash
docker build -t recap-studio .
docker run -p 8080:8080 -e GMI_API_KEY=your-key recap-studio
```

## Files

| File | What's in it |
|---|---|
| `server.py` | The web server: page, health check, text streaming, graphic start and status |
| `gmi.py` | Calls to GMI: streamed chat completions, and image submit, poll and download |
| `prompts.py` | Everything the AI is told: formats, tones, languages and graphic styles. Edit this to change the writing. |
| `static/index.html` | The whole web page: form, live results, copy and download buttons |
| `Dockerfile` | The container image, serving on port 8080 |
| `.github/workflows/publish-image.yml` | Builds the image and publishes it to ghcr.io |
| `agentbox.env.example` | Optional environment variables for Agentbox |

## Privacy

Event details go to GMI's models to write the recap. The server stores nothing except recently made graphics, which are kept in memory for up to 30 images. Your draft is saved only in your own browser.
