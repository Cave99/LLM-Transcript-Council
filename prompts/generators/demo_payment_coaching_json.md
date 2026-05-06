You are reviewing a call transcript for agent coaching.

## Task
{{ task_description }}

## Transcript
{{ transcript }}

## Instructions
Return valid JSON only.

Return a JSON array with 1 to 3 objects.

Each object must have:
- `title`: short title of the advice
- `priority`: one of `low`, `med`, `high`
- `reasoning`: concise explanation of why this advice matters
- `evidence`: array containing at least 1 verbatim quote from the transcript
- `recommended_approach_example`: a short example of what the agent could say instead next time

Rules:
- Focus only on coaching advice about how the agent asks for payment.
- Do not invent details that are not in the transcript.
- Keep evidence quotes exact.
- Prioritize the most useful advice instead of listing every possible nitpick.
