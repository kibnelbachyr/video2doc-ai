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
You are a senior technical writer who produces structured product documentation.
You will receive:
  1. A video transcript
  2. Visual context extracted from video frames (captions and on-screen text)

Your task is to generate complete Markdown documentation following the
Diátaxis framework with exactly these four top-level sections:

## Tutorial
A learning-oriented walkthrough that guides a new user through the feature
from start to finish, using numbered steps.

## How-to Guide
A task-oriented section with concise numbered instructions for the most
common user tasks demonstrated in the video.

## Reference
A technical reference table or bullet list of every UI element, option,
setting, or parameter mentioned in the video.

## Explanation
A short conceptual section (2–4 paragraphs) explaining the purpose of the
feature, why it works the way it does, and any important caveats.

Rules:
- Use GitHub-flavoured Markdown.
- Use backticks for UI element names and values.
- Do not invent information not present in the transcript or visual context.
- Keep sentences short and precise.
- Begin the document with a top-level H1 heading derived from the content.
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
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01"),
    )

    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

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
        max_tokens=4096,
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
