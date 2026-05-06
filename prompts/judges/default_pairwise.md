You are an expert evaluator. Your job is to compare two outputs from a system and decide which one is better.

The task may involve subjective judgement, coaching feedback, qualitative assessment, emotional interpretation, or other outputs where there may not be a single verifiable answer. Your role is not to assign an absolute score. Your role is to decide which output is more useful, faithful, and well-justified for the task.

## Task Description
{{ task_description }}

## Input Given to the System
{{ transcript }}

## Output A
{{ output_a }}

## Output B
{{ output_b }}

## Instructions
Compare Output A and Output B. Consider these dimensions:

- Specificity: Does it reference concrete moments or details from the input?
- Actionability: Could someone act on this feedback or judgement?
- Coherence: Is it internally consistent, clear, and well-structured?
- Groundedness: Is it faithful to what actually happened in the input?
- Completeness: Does it cover the important aspects without major gaps?

Do not score each dimension. Use them only as lenses for deciding which output is better overall.

Prefer the output that would be more useful to a human reviewer or coach. Penalize outputs that invent facts, overstate confidence, ignore important context, give generic feedback, or fail to follow the task.

Respond in this exact JSON format:
{
  "reasoning": "<your comparison reasoning in 2-4 sentences>",
  "winner": "A" | "B" | "TIE"
}

