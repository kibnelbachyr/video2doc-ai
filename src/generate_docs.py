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
"""

import os
from openai import AzureOpenAI


# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a senior technical writer specialising in software product documentation.
You receive two inputs extracted from an internal training or product video:
  1. A speech transcript (may be partial or empty if audio was unclear)
  2. Visual context from video frames: scene captions and on-screen text (OCR)

━━━ LANGUAGE RULE (mandatory) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Detect the primary language of the transcript.
Generate ALL documentation — headings, body text, tips, table headers,
everything — in that same detected language.
  • Transcript in French  → write entirely in French
  • Transcript in English → write entirely in English
  • Transcript empty or indeterminate → default to English
Never mix languages within the document.

━━━ OUTPUT FORMAT ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Start with a descriptive H1 title derived from the video content.
Then produce exactly four top-level sections in this order:

## Tutorial
Learning-oriented. Guide a new user through the topic step-by-step from start
to finish. Use numbered steps with sub-steps where relevant. Explain WHY each
step matters, not only WHAT to do. Reference on-screen elements seen in the
visual context (e.g. "You will see…", "Click the … button in the top-right").

## How-to Guide
Task-oriented. Cover the 3–6 most important tasks or workflows demonstrated.
Use ### sub-headings to separate distinct tasks. Each task uses numbered steps
that are concise and immediately actionable.

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
## Video Transcript

{transcript}

---

## Visual Context from Video Frames

{image_context}

---

Detect the language of the transcript above, then generate the full Markdown \
documentation in that same language.
"""


# ── LLM call ──────────────────────────────────────────────────────────────────

def generate_documentation(transcript: str, image_context: str) -> str:
    """
    Call Azure AI Foundry (GPT-4.1) and return the generated Markdown.

    Language is auto-detected from the transcript: French input → French output,
    English input → English output. Empty transcript defaults to English.
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

    response = client.chat.completions.create(
        model=deployment,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_message},
        ],
        temperature=0.2,   # low temperature — factual, deterministic output
        max_tokens=8192,
    )

    markdown = response.choices[0].message.content or ""
    tokens_used = response.usage.total_tokens if response.usage else "unknown"
    print(f"[llm] Generation complete – {tokens_used} tokens used, "
          f"{len(markdown)} chars output")
    return markdown


def save_markdown(content: str, output_path: str) -> None:
    """Write the Markdown string to a file."""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[output] Markdown saved → '{output_path}'")
