"""
Everything the AI is told, in one place. Edit the instructions below to change
how each recap format is written.
"""

import json
import re

LANGUAGES = ["English", "French", "Kiswahili", "Kinyarwanda", "Portuguese", "Spanish", "Arabic", "Other…"]

TONES = {
    "Friendly & warm": "friendly, warm and human, like a community builder thanking their people",
    "Professional": "clear, credible and professional, suitable for partners and employers",
    "Energetic": "high-energy and celebratory, but never spammy or full of buzzwords",
    "Educational": "explanatory and beginner-friendly, teaching the key ideas from the event",
}

EVENT_TYPES = [
    "Workshop",
    "Meetup",
    "Conference",
    "Conference talk or panel",
    "Hackathon",
    "Booth or activation",
    "University tour",
    "Online event / X Space",
    "Other",
]

IMAGE_STYLES = {
    "Bold & modern": "bold modern graphic design, vibrant gradients, geometric shapes, strong contrast",
    "Photographic": "realistic photo of a lively tech event atmosphere, natural light, candid energy, no identifiable real people",
    "Illustrated": "flat vector illustration, friendly characters, clean shapes, rich colour palette",
    "Minimal & clean": "minimal, lots of white space, one strong focal element, soft colours",
}

# Brief fields, in the order the AI sees them: (form key, label)
BRIEF_FIELDS = [
    ("name", "Event name"),
    ("event_type", "Event type"),
    ("date", "Date"),
    ("location", "Location"),
    ("organizer", "Organised by"),
    ("partners", "Partners / sponsors"),
    ("audience", "Audience"),
    ("speakers", "Speakers and sessions"),
    ("results", "Results and numbers"),
    ("highlights", "Highlights, quotes and standout moments"),
    ("notes", "Organiser's raw notes"),
    ("thanks", "People to thank"),
    ("cta", "Call to action and links"),
    ("tags", "Handles and hashtags to use"),
]

MAX_FIELD_CHARS = 15_000

# Text outputs: key -> label, short description, token budget, instructions
FORMATS = {
    "x_thread": {
        "label": "🧵 X thread",
        "help": "5 to 8 posts, each under 280 characters",
        "max_tokens": 1200,
        "instructions": """Write an X (Twitter) thread recapping the event.
- 5 to 8 posts. Every post must be under 270 characters, counting spaces, emojis and links.
- Post 1 is a strong hook that makes people want to read on. Don't open with the word "Thread".
- Middle posts: what happened, the key sessions or ideas, standout moments, and results (only numbers from the brief).
- Final post: thank speakers and partners (use their handles if given) and include the call to action.
- At most 3 hashtags in the whole thread.
- Do not number the posts. Put a line containing only --- between posts.""",
    },
    "linkedin": {
        "label": "💼 LinkedIn post",
        "help": "150 to 300 words",
        "max_tokens": 900,
        "instructions": """Write a LinkedIn post recapping the event.
- 150 to 300 words.
- The first line is a hook that works before LinkedIn's "see more" cut-off.
- Short paragraphs of 1 to 3 sentences. A short bullet list for highlights or results is fine.
- Cover what the event was, who came, what they learned or built, the results (only from the brief), thanks to speakers and partners by name, and the call to action.
- End with 3 to 5 relevant hashtags on their own line.
- At most 3 emojis. Plain text only: no Markdown, no asterisks.""",
    },
    "blog": {
        "label": "📝 Blog recap",
        "help": "500 to 800 words, for Medium or your website",
        "max_tokens": 2000,
        "instructions": """Write a blog recap suitable for Medium or a website, in Markdown.
- Start with a title on its own line as "# Title", then a one-sentence subtitle in italics.
- 500 to 800 words.
- Use "## " section headings, for example: Why we gathered, What happened, Key takeaways, By the numbers (only if the brief has numbers), Thank you, What's next.
- Explain any technical ideas simply, for newcomers.
- End with the call to action and links from the brief.""",
    },
    "community": {
        "label": "📣 Community update",
        "help": "For Telegram, WhatsApp or Discord groups",
        "max_tokens": 600,
        "instructions": """Write a short community announcement for Telegram, WhatsApp or Discord groups.
- 60 to 120 words.
- Open with one short celebratory line, then 3 to 5 bullet highlights that start with "•".
- Include the call to action and links from the brief.
- Emojis are welcome but keep it readable (at most 6).
- Plain text only: no Markdown headings, bold or asterisks.""",
    },
    "thank_you": {
        "label": "🙏 Thank-you note",
        "help": "For attendees, speakers and partners, by email or DM",
        "max_tokens": 600,
        "instructions": """Write a thank-you message to attendees, speakers and partners that can be sent by email or DM.
- 80 to 150 words.
- Warm and specific: mention one or two real highlights from the brief.
- Thank speakers and partners by name if the brief gives them.
- End with the next step (call to action, feedback form, next event) if the brief has one.
- Start with a greeting such as "Hi everyone," and sign off as the organiser named in the brief.
- Plain text only.""",
    },
    "partner_report": {
        "label": "📊 Partner report",
        "help": "An outcomes brief for the protocol or sponsor",
        "max_tokens": 1600,
        "instructions": """Write a post-event report for the protocol, sponsor or partner that backed this event. It should read like a professional outcomes brief they can forward internally. Use Markdown with these sections:
## Summary (3 to 4 sentences)
## Event at a glance (bullets: name, date, location, format, audience; skip any that aren't in the brief)
## What we delivered (sessions, workshops, demos, booth activity)
## Results (bullets with only the numbers and outcomes from the brief. If the brief has no numbers, write "No numbers were recorded for this event" and suggest 3 things to track next time.)
## Highlights and feedback
## Learnings (only if the notes mention challenges or lessons; otherwise leave this section out)
## Recommended next steps (3 concrete suggestions)
- 300 to 550 words. Factual and confident, no hype.""",
    },
}

GRAPHIC_LABEL = "🎨 Recap graphic"


def build_brief(form: dict) -> str:
    lines = []
    for key, label in BRIEF_FIELDS:
        value = str(form.get(key) or "").strip()
        if value:
            lines.append(f"{label}:\n{value[:MAX_FIELD_CHARS]}")
    return "\n\n".join(lines)


def system_prompt(language: str, tone: str) -> str:
    return f"""You are an experienced event marketer and community manager who writes post-event recaps for Web3 and tech communities.

Rules:
- Use only the facts in the EVENT BRIEF. Never invent numbers, names, quotes, dates, links, rewards or outcomes. If something isn't in the brief, leave it out.
- Write in {language}. Keep names, handles, hashtags and links exactly as given.
- Tone: {TONES.get(tone, tone)}.
- Credit speakers, partners and organisers using the names or handles in the brief.
- Raw notes may mention problems (late start, bad Wi-Fi). Don't put those in public posts; only the partner report may mention them, as learnings.
- Output only the finished content. No preamble, no notes to the user, no options."""


def user_prompt(brief: str, fmt_key: str) -> str:
    return f"EVENT BRIEF\n\n{brief}\n\nTASK\n\n{FORMATS[fmt_key]['instructions']}"


def graphic_prompt_request(brief: str, style: str, aspect: str, event_name: str, include_title: bool) -> str:
    if include_title and event_name.strip():
        text_rule = (
            f'Include the text "{event_name.strip()}" once, large, clearly spelled and easy to read. '
            "No other words, letters or numbers anywhere in the image."
        )
    else:
        text_rule = "No text, words, letters or numbers anywhere in the image."
    return f"""EVENT BRIEF

{brief}

TASK

Write a prompt for an AI image generator to create a recap graphic for this event, to post on social media.
- Visual style: {IMAGE_STYLES.get(style, style)}.
- Format: {aspect}.
- Describe the composition, colours, lighting and mood so they reflect the event's theme and its city or region.
- {text_rule}
- No logos, brand marks or identifiable real people.
- Output only the image prompt, in English, under 120 words."""


def split_thread(text: str) -> list:
    """Split an X thread on lines that contain only dashes."""
    posts, current = [], []
    for line in text.splitlines():
        if line.strip() and set(line.strip()) == {"-"} and len(line.strip()) >= 3:
            if current:
                posts.append("\n".join(current).strip())
            current = []
        else:
            current.append(line)
    if current:
        posts.append("\n".join(current).strip())
    return [p for p in posts if p]


def x_length(text: str) -> int:
    """Approximate X's character count: links count as 23, emojis and most non-Latin characters as 2."""
    text = re.sub(r"https?://\S+", "x" * 23, text)
    count = 0
    for ch in text:
        o = ord(ch)
        light = o <= 4351 or 8192 <= o <= 8205 or 8208 <= o <= 8223 or 8242 <= o <= 8247
        count += 1 if light else 2
    return count


# --------------------------------------------------------------------------- #
# Free recap card: the AI writes the short text, the browser draws the card
# --------------------------------------------------------------------------- #

CARD_THEMES = ["Midnight & lime", "Violet", "Sunset", "Clean white"]

CARD_SYSTEM = "You turn event briefs into the short text for a social media recap card. Reply with JSON only."


def card_request(brief: str, language: str) -> str:
    return f"""EVENT BRIEF

{brief}

TASK

Write the text for a recap card, in {language}. Reply with only a JSON object in this shape:
{{"kicker": "Event recap", "headline": "…", "stats": [{{"value": "112", "label": "builders checked in"}}], "quote": "…"}}

Rules:
- kicker: 2 to 4 words shown above the headline, such as "Event recap" or "Thank you, Kigali".
- headline: the event name or a punchy version of it, at most 8 words.
- stats: up to 3 of the most impressive numbers from the brief. "value" is only the number (for example "112", "47", "3x"); "label" is 2 to 5 words. Use only numbers that appear in the brief. If there are none, use an empty list.
- quote: one short highlight or attendee quote from the brief, at most 14 words, or "" if there is none.
- Keep names, handles and numbers exactly as given. No Markdown, no explanation."""


NUMBER = re.compile(r"\d[\d,.]*")


def _clip(value, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip().strip('"').strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def card_from_form(form: dict) -> dict:
    """A card built straight from the form, with no AI. Used when the AI reply can't be used."""
    stats = []
    for line in str(form.get("results") or "").splitlines():
        m = re.match(r"\s*[-•*]?\s*(\d[\d,.]*\+?%?x?)\s+(.+)", line)
        if m:
            label = re.sub(r"\(.*?\)", "", m.group(2)).strip()
            stats.append({"value": m.group(1), "label": _clip(" ".join(label.split()[:5]), 40)})
        if len(stats) == 3:
            break
    quote = ""
    for line in str(form.get("highlights") or "").splitlines():
        line = line.strip(" -•*")
        if line and len(line) <= 120:
            quote = line
            break
    return {"kicker": "Event recap", "headline": _clip(form.get("name"), 80), "stats": stats, "quote": _clip(quote, 140), "source": "form"}


def parse_card(raw: str, form: dict, brief: str) -> dict:
    """Validates the AI's card JSON. Drops any number that isn't in the brief, so the card can't invent results."""
    match = re.search(r"\{.*\}", raw or "", flags=re.DOTALL)
    try:
        data = json.loads(match.group(0)) if match else None
    except (ValueError, TypeError):
        data = None
    if not isinstance(data, dict):
        return card_from_form(form)

    brief_numbers = {n.replace(",", "").rstrip(".") for n in NUMBER.findall(brief)}
    stats = []
    for item in data.get("stats") or []:
        if not isinstance(item, dict):
            continue
        value, label = _clip(item.get("value"), 12), _clip(item.get("label"), 40)
        digits = [n.replace(",", "").rstrip(".") for n in NUMBER.findall(value)]
        if value and label and digits and all(d in brief_numbers for d in digits):
            stats.append({"value": value, "label": label})
        if len(stats) == 3:
            break

    fallback = card_from_form(form)
    return {
        "kicker": _clip(data.get("kicker"), 30) or "Event recap",
        "headline": _clip(data.get("headline"), 80) or fallback["headline"],
        "stats": stats or fallback["stats"],
        "quote": _clip(data.get("quote"), 140),
        "source": "ai",
    }
