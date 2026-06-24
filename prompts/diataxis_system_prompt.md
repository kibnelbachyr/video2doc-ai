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
  the transcript or visual context (the "fidelity rule" — exact terminology,
  menu names, and labels are preserved as spoken or shown on screen).
- **Shared timeline:** Both inputs are timestamped — transcript lines as
  `[MM:SS] text` and frame analysis as `[MM:SS] filename / Visual: ... / Text
  on screen: ...` — so the model can place each screenshot next to the
  narration it illustrates instead of clustering images at the end.
- **Inline image placement:** The model references frames it judges relevant
  as `![caption](frame_NNNNNN.png)`; `embed_frame_images()` then resolves
  those references to base64 data URIs after generation.
- **Automatic language detection:** Output language follows the detected
  transcript language (French or English), defaulting to English when the
  transcript is empty.
- **Token budget:** `max_tokens=8192` supports long, richly illustrated
  documents. Increase further for very long videos or add chunking logic.

## Extending the Prompt

For product documentation covering multiple features, split the video into
segments (by chapter or scene) and generate one Markdown file per segment,
then aggregate with a table of contents.

For the full current system prompt and step-by-step pipeline behaviour, see
[Pipeline → Step 4](../docs/pipeline.md#step-4--documentation-generation-srcgenerate_docspy).
