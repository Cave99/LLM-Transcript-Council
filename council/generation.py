"""Generation phase execution for run workers."""

from __future__ import annotations

import asyncio
from pathlib import Path

from sqlmodel import select

from council.judge import render_generation_prompt
from council.json_tools import maybe_repair_json
from council.models import Generation, GeneratorConfig, Run, Status, Task, Transcript, utc_now
from council.openrouter import OpenRouterClient
from council.run_state import add_run_log, is_run_paused


async def run_generations(run_id: int, session_factory, client: OpenRouterClient, semaphore: asyncio.Semaphore) -> None:
    """Queue and execute every incomplete generation in parallel."""

    with session_factory() as session:
        generation_ids = [
            row.id
            for row in session.exec(
                select(Generation).where(
                    Generation.run_id == run_id,
                    Generation.status != Status.complete,
                )
            ).all()
            if row.id is not None
        ]
        add_run_log(session, run_id, f"Generation phase queued {len(generation_ids)} incomplete calls.")
        session.commit()
    await asyncio.gather(*[generate_one(generation_id, session_factory, client, semaphore) for generation_id in generation_ids])


async def generate_one(generation_id: int, session_factory, client: OpenRouterClient, semaphore: asyncio.Semaphore) -> None:
    """Run one generator call and persist either the output or failure."""

    async with semaphore:
        with session_factory() as session:
            generation = session.get(Generation, generation_id)
            if not generation:
                return
            if is_run_paused(session, generation.run_id):
                return
            if generation.status == Status.complete:
                return
            run = session.get(Run, generation.run_id)
            task = session.get(Task, run.task_id)
            transcript = session.get(Transcript, generation.transcript_id)
            config = session.get(GeneratorConfig, generation.generator_config_id)
            run_id = generation.run_id
            task_description = task.description_snapshot
            transcript_content = transcript.content_snapshot
            prompt_snapshot = config.prompt_snapshot
            model_id = config.model_id
            temperature = config.temperature
            transcript_name = Path(transcript.path).name
            config_label = config.label
            generation.status = Status.running
            generation.started_at = utc_now()
            session.add(generation)
            add_run_log(session, run_id, f"Generation started: {config_label} on {transcript_name}.")
            session.commit()

        prompt = render_generation_prompt(
            prompt_snapshot,
            transcript=transcript_content,
            task_description=task_description,
        )
        try:
            response = await client.chat(
                model=model_id,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            with session_factory() as session:
                generation = session.get(Generation, generation_id)
                run_id = generation.run_id
                generation.status = Status.complete
                generation.output_raw = response.text
                generation.output_repaired = maybe_repair_json(response.text)
                generation.prompt_tokens = response.prompt_tokens
                generation.completion_tokens = response.completion_tokens
                generation.cost = response.cost
                generation.completed_at = utc_now()
                session.add(generation)
                add_run_log(session, run_id, f"Generation complete: {model_id} on generation #{generation_id}.")
                session.commit()
        except Exception as exc:
            with session_factory() as session:
                generation = session.get(Generation, generation_id)
                run_id = generation.run_id if generation else 0
                if generation:
                    generation.status = Status.failed
                    generation.error = str(exc)
                    session.add(generation)
                add_run_log(session, run_id, f"Generation failed: {model_id} on generation #{generation_id}: {exc}", level="error")
                session.commit()
