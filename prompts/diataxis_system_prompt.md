# Diátaxis Documentation Prompt Reference

This file documents the system prompt strategy used in `src/generate_docs.py`.

## Framework: Diátaxis

[Diátaxis](https://diataxis.fr/) organises documentation into four modes based on
whether the reader is *learning*, *doing*, *understanding*, or *consulting*.

| Section       | Orientation | Answers                          |
|---------------|-------------|----------------------------------|
| Tutorial      | Learning    | "Help me get started"            |
| How-to Guide  | Doing       | "How do I accomplish X?"         |
| Reference     | Consulting  | "What are all the options?"      |
| Explanation   | Understanding | "Why does it work this way?"   |

## Prompt Design Decisions

- **Low temperature (0.2):** Reduces hallucinations, ensures factual grounding.
- **No invented information:** The prompt explicitly forbids adding facts not in
  the transcript or visual context.
- **Compact visual context:** Frame analysis results are serialised as
  `[filename] / Visual: ... / Text on screen: ...` blocks so the LLM can
  reference specific screens.
- **Token budget:** `max_tokens=8192` supports thorough, production-quality
  documentation. Increase or add chunking logic for very long videos.

## Extending the Prompt

For product documentation covering multiple features, split the video into
segments (by chapter or scene) and generate one Markdown file per segment,
then aggregate with a table of contents.
