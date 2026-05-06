"""
generate_docs.py
----------------
Send the aggregated context (transcript + vision results) to Azure OpenAI
and generate structured Markdown documentation following the Diátaxis framework.

Diátaxis sections generated:
  • Tutorial     – learning-oriented step-by-step walkthrough
  • How-to Guide – task-oriented practical steps
  • Reference    – technical details, UI elements, options
  • Explanation  – conceptual background

Azure OpenAI is accessed via the `openai` Python package pointed at the
Azure endpoint (identical interface, different base URL + api-key header).
"""

import os
from openai import AzureOpenAI


# ── Prompt template ───────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a senior technical writer who produces thorough, structured product documentation.
You will receive:
  1. A video transcript (may be empty if audio extraction failed)
  2. Visual context extracted from video frames (captions and on-screen text)

Your task is to generate complete Markdown documentation following the
Diátaxis framework with exactly these four top-level sections:

## Tutorial
A learning-oriented, step-by-step walkthrough that guides a new user through
the topic from start to finish. Use numbered steps, include sub-steps where
relevant, and explain why each step matters — not just what to do.

## How-to Guide
Task-oriented numbered instructions for the most common tasks or concepts
demonstrated in the video. Group related tasks under ### sub-headings.

## Reference
A comprehensive technical reference covering all concepts, terms, components,
or parameters mentioned. Use tables where appropriate (Name | Description | Notes).

## Explanation
Two to four paragraphs of conceptual background explaining the topic, why it
works the way it does, trade-offs, and any important caveats or limitations.

Rules:
- Use GitHub-flavoured Markdown.
- Use backticks for technical terms, UI element names, values, and code.
- Use > blockquotes to highlight tips or important warnings.
- Derive as much detail as possible from the provided transcript and visual context.
- If the transcript is sparse or empty, rely on the visual context and produce
  the best documentation you can from what is available — never leave a section empty.
- Begin the document with a top-level H1 heading derived from the content.
- Aim for thorough, production-quality documentation — not a brief summary.
"""

USER_PROMPT_TEMPLATE = """\
## Video Transcript

{transcript}

---

## Visual Context from Video Frames

{image_context}

---

Generate the full Markdown documentation now.
"""


# ── LLM call ──────────────────────────────────────────────────────────────────

def generate_documentation(transcript: str, image_context: str) -> str:
    """
    Call Azure OpenAI and return the generated Markdown as a string.
    """
    client = AzureOpenAI(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_key=os.environ["AZURE_OPENAI_KEY"],
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2025-04-01-preview"),
    )

    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1")

    user_message = USER_PROMPT_TEMPLATE.format(
        transcript=transcript.strip(),
        image_context=image_context.strip(),
    )

    print(f"[llm] Calling Azure OpenAI deployment '{deployment}' …")

    response = client.chat.completions.create(
        model=deployment,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=0.3,   # low temperature for factual, consistent output
        max_tokens=8192,
    )

    markdown = response.choices[0].message.content or ""
    tokens_used = response.usage.total_tokens if response.usage else "unknown"
    print(f"[llm] Generation complete – {tokens_used} tokens used")
    return markdown


def save_markdown(content: str, output_path: str) -> None:
    """Write the Markdown string to a file."""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[output] Markdown saved → '{output_path}'")
