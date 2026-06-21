"""
generate_docs.py
----------------
Send the aggregated context (transcript + vision results) to Azure AI Foundry
and generate structured Markdown documentation following the Diátaxis framework.

Language behaviour:
  The LLM detects the primary language of the transcript and produces all
  documentation in that same language (French → French, English → English).
  If the transcript is empty the output defaults to English.

Diátaxis sections generated:
  • Tutorial     – learning-oriented step-by-step walkthrough
  • How-to Guide – task-oriented practical steps
  • Reference    – technical details, UI elements, options
  • Explanation  – conceptual background

Image placement:
  Both the transcript and the visual context are timestamped. The LLM is
  instructed to reference the frame filename it judges most relevant right
  next to the text it illustrates, using a standard Markdown image tag
  (e.g. ![Caption](frame_000004.png)). embed_frame_images() then resolves
  those filenames against the real extracted frame files and inlines them
  as base64 data URIs, so the final Markdown is self-contained.
"""

import base64
import os
import pathlib
import re
import time

from openai import AzureOpenAI, RateLimitError


# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a senior technical writer specialising in software product documentation.
You receive two time-aligned inputs extracted from an internal training or
product video:
  1. A timestamped speech transcript: lines formatted as "[MM:SS] text"
     (may be partial or empty if audio was unclear)
  2. Timestamped visual context from video frames: lines formatted as
     "[MM:SS] frame_NNNNNN.png" followed by a scene caption and any
     on-screen text (OCR)

Both inputs share the same timeline — a transcript line at [02:15] and a
frame at [02:18] describe the same moment in the video.

━━━ LANGUAGE RULE (mandatory) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Detect the primary language of the transcript.
Generate ALL documentation — headings, body text, tips, table headers,
everything — in that same detected language.
  • Transcript in French  → write entirely in French
  • Transcript in English → write entirely in English
  • Transcript empty or indeterminate → default to English
Never mix languages within the document.

━━━ FIDELITY RULE (mandatory) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Stay strictly faithful to the transcript and the visual context.
  • Preserve exact terminology, menu names, button labels, and field names
    exactly as spoken or shown on screen — do not rename, simplify, or
    "improve" a product-specific term into a generic one.
  • Polish grammar, flow, and clarity, but never alter the meaning, invent
    a step that was not shown, or invent a UI element that was not
    mentioned or visible.
  • If the transcript and visual context disagree, trust the visual
    context for what is on screen and the transcript for intent/rationale.
  • When information is genuinely missing, say so briefly rather than
    inventing plausible-sounding detail.

━━━ IMAGE PLACEMENT RULE (mandatory) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
You have a set of numbered frames, each with a timestamp. For every step
or concept where a frame clearly shows the screen being described, insert
that frame inline, immediately after the sentence it illustrates, using:
  ![Short, specific caption](frame_NNNNNN.png)
Use the EXACT filename given in the visual context — never invent a
filename. Match frames by timestamp proximity to the text being written at
that point. Use as many distinct frames as add real value — favour a
richly illustrated document over a sparse one, but skip frames that are
near-duplicates of one already used or that show a blank/transition
screen with no useful content. Do not cluster every image at the end of a
section — distribute them at the point they are relevant.

━━━ OUTPUT FORMAT ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Start with a descriptive H1 title derived from the video content.
Then produce exactly four top-level sections in this order:

## Tutorial
Learning-oriented. Guide a new user through the topic step-by-step from start
to finish. Use numbered steps with sub-steps where relevant. Explain WHY each
step matters, not only WHAT to do. Reference on-screen elements seen in the
visual context (e.g. "You will see…", "Click the … button in the top-right")
and place the matching frame next to each step per the IMAGE PLACEMENT RULE.

## How-to Guide
Task-oriented. Cover the 3–6 most important tasks or workflows demonstrated.
Use ### sub-headings to separate distinct tasks. Each task uses numbered steps
that are concise and immediately actionable, illustrated with frames where useful.

## Reference
Technical reference. List and describe every concept, UI element, parameter,
menu item, setting, or feature mentioned in the transcript OR visible in the
visual context. Use tables wherever possible:
  | Name | Description | Notes / Default |

## Explanation
Conceptual background (2–4 paragraphs). Explain the topic's architecture,
rationale, and design decisions — why things work the way they do, trade-offs,
limitations, and context a practitioner should understand before or after
following the tutorial.

━━━ QUALITY RULES ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Use GitHub-flavoured Markdown exclusively.
- Use `backticks` for UI element names, technical terms, values, commands,
  and code identifiers.
- Use > blockquotes for tips, warnings, or important callouts.
- Extract every concrete detail from both inputs. Do not invent information
  that is absent from the inputs, but do infer logical gaps when the intent
  is unambiguous from context.
- Never leave a section empty. When information is limited, draw from the
  visual context and produce the best documentation possible.
- Target length: thorough, production-quality documentation — not a summary.
"""

USER_PROMPT_TEMPLATE = """\
## Timestamped Video Transcript

{transcript}

---

## Timestamped Visual Context from Video Frames

{image_context}

---

Detect the language of the transcript above, then generate the full Markdown \
documentation in that same language, placing frames inline per the IMAGE \
PLACEMENT RULE.
"""


# ── LLM call ──────────────────────────────────────────────────────────────────

def generate_documentation(transcript: str, image_context: str) -> str:
    """
    Call Azure AI Foundry (GPT-4.1) and return the generated Markdown.

    *transcript* and *image_context* are expected to already be formatted
    as "[MM:SS] ..." blocks (see transcribe.format_transcript and
    analyze_images.format_image_context) so the LLM can align them on a
    shared timeline.

    Language is auto-detected from the transcript: French input → French
    output, English input → English output. Empty transcript defaults to
    English.
    """
    client = AzureOpenAI(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_key=os.environ["AZURE_OPENAI_KEY"],
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2025-04-01-preview"),
    )

    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1")

    user_message = USER_PROMPT_TEMPLATE.format(
        transcript=transcript.strip() or "(no transcript available)",
        image_context=image_context.strip() or "(no visual context available)",
    )

    print(f"[llm] Calling Azure AI Foundry deployment '{deployment}' …")

    max_attempts = 5
    base_delay_seconds = 15   # Azure TPM quotas reset on a rolling 60s window
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.chat.completions.create(
                model=deployment,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": user_message},
                ],
                temperature=0.2,   # low temperature — factual, deterministic output
                max_tokens=8192,
            )
            break
        except RateLimitError as exc:
            if attempt == max_attempts:
                raise
            delay = base_delay_seconds * attempt
            print(f"[llm] Rate limited (attempt {attempt}/{max_attempts}), "
                  f"retrying in {delay}s … ({exc})")
            time.sleep(delay)

    markdown = response.choices[0].message.content or ""
    tokens_used = response.usage.total_tokens if response.usage else "unknown"
    print(f"[llm] Generation complete – {tokens_used} tokens used, "
          f"{len(markdown)} chars output")
    return markdown


# ── Image embedding ───────────────────────────────────────────────────────────

_FRAME_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\((frame_\d+\.png)\)")


def embed_frame_images(markdown: str, frames_dir: str) -> str:
    """
    Resolve ![caption](frame_NNNNNN.png) references in *markdown* into
    self-contained base64 data URIs read from *frames_dir*.

    The LLM only ever sees frame filenames as text (never the image
    bytes), so this step is what actually inlines the real screenshots.
    A reference to a filename that doesn't exist (e.g. a hallucinated
    name) is dropped rather than left as a broken image link.
    """
    frames_path = pathlib.Path(frames_dir)
    embedded_count = 0

    def _replace(match: re.Match) -> str:
        nonlocal embedded_count
        caption, filename = match.group(1), match.group(2)
        frame_file = frames_path / filename
        if not frame_file.exists():
            print(f"[embed] Referenced frame not found, dropping: {filename}")
            return ""
        encoded = base64.b64encode(frame_file.read_bytes()).decode("ascii")
        embedded_count += 1
        return f"![{caption}](data:image/png;base64,{encoded})"

    embedded, total_refs = _FRAME_IMAGE_RE.subn(_replace, markdown)
    dropped = total_refs - embedded_count
    print(f"[embed] Inlined {embedded_count} frame image(s) into the Markdown"
          f"{f', dropped {dropped} unresolved reference(s)' if dropped else ''}")
    return embedded


def save_markdown(content: str, output_path: str) -> None:
    """Write the Markdown string to a file."""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[output] Markdown saved → '{output_path}'")
