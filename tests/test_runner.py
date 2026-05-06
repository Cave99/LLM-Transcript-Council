from sqlmodel import Session, SQLModel, create_engine, select

from council.models import EloRating, Generation, GeneratorConfig, JudgeConfig, Judgement, Match, MatchResult, Project, Run, RunAnalysis, RunLog, Status, Task, Transcript
from council.runner import GeneratorSpec, JudgeSpec, _apply_match_elo, create_project, create_run, create_task, delete_project, delete_task, recover_run, rename_project, reset_run, stop_run
from app import judge_pattern_analysis_availability


def test_reset_run_clears_previous_results(tmp_path):
    """Resetting a run should clear outputs, votes, and leaderboard state."""

    engine = create_engine(f"sqlite:///{tmp_path / 'runner.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    task_path = tmp_path / "task.md"
    task_path.write_text("Demo task", encoding="utf-8")
    generator_prompt_path = tmp_path / "generator.md"
    generator_prompt_path.write_text("{{ task_description }}\n{{ transcript }}", encoding="utf-8")
    judge_prompt_path = tmp_path / "judge.md"
    judge_prompt_path.write_text("{{ output_a }}\n{{ output_b }}", encoding="utf-8")
    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()
    (transcript_dir / "call_01.md").write_text("[CUSTOMER]: Hi\n[AGENT]: Hello", encoding="utf-8")

    with Session(engine) as session:
        project = create_project(session, "demo")
        task = create_task(
            session,
            project_id=project.id,
            name="task",
            description_path=str(task_path),
            transcript_root=str(transcript_dir),
            default_judge_prompt_path=str(judge_prompt_path),
        )
        run = create_run(
            session,
            task_id=task.id,
            name="run",
            generator_specs=[
                GeneratorSpec("a", "model-a", 0.2, str(generator_prompt_path)),
                GeneratorSpec("b", "model-b", 0.2, str(generator_prompt_path)),
            ],
            judge_specs=[JudgeSpec("judge", "judge-model", 0.0, str(judge_prompt_path))],
        )

        generation = session.exec(select(Generation).where(Generation.run_id == run.id)).first()
        generation.status = Status.complete
        generation.output_raw = '{"ok":true}'
        generation.output_repaired = '{"ok":true}'
        generation.error = "old error"
        generation.prompt_tokens = 10
        generation.completion_tokens = 20
        generation.cost = 0.12
        session.add(generation)

        match = session.exec(select(Match).where(Match.run_id == run.id)).first()
        match.status = Status.complete
        session.add(match)

        session.add(
            Judgement(
                match_id=match.id,
                judge_config_id=1,
                direction="normal",
                winner="A",
                reasoning="A wins",
                raw_response='{"winner":"A"}',
            )
        )
        session.add(
            MatchResult(
                match_id=match.id,
                final_winner="A",
                agreement=1.0,
                votes_json='["A"]',
            )
        )

        rating = session.exec(select(EloRating).where(EloRating.run_id == run.id)).first()
        rating.rating = 1532
        rating.wins = 2
        rating.losses = 1
        rating.ties = 1
        session.add(rating)

        run.status = Status.complete
        run.error = "failed once"
        run.started_at = task.created_at
        run.completed_at = task.created_at
        session.add(run)
        session.commit()

        reset_run(session, run.id)

        refreshed_run = session.get(Run, run.id)
        refreshed_generation = session.get(Generation, generation.id)
        refreshed_match = session.get(Match, match.id)
        refreshed_rating = session.get(EloRating, rating.id)

        assert refreshed_run.status == Status.pending
        assert refreshed_run.error is None
        assert refreshed_run.started_at is None
        assert refreshed_run.completed_at is None

        assert refreshed_generation.status == Status.pending
        assert refreshed_generation.output_raw is None
        assert refreshed_generation.output_repaired is None
        assert refreshed_generation.error is None
        assert refreshed_generation.prompt_tokens is None
        assert refreshed_generation.completion_tokens is None
        assert refreshed_generation.cost is None
        assert refreshed_generation.completed_at is None

        assert refreshed_match.status == Status.pending

        assert refreshed_rating.rating == refreshed_run.elo_start
        assert refreshed_rating.wins == 0
        assert refreshed_rating.losses == 0
        assert refreshed_rating.ties == 0

        assert session.exec(select(Judgement).where(Judgement.match_id == match.id)).all() == []
        assert session.exec(select(MatchResult).where(MatchResult.match_id == match.id)).all() == []


def test_recover_run_only_requeues_missing_outputs_and_stop_pauses(tmp_path):
    """Recover should preserve partial work, while stop should pause the run."""

    engine = create_engine(f"sqlite:///{tmp_path / 'recover.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    task_path = tmp_path / "task.md"
    task_path.write_text("Demo task", encoding="utf-8")
    generator_prompt_path = tmp_path / "generator.md"
    generator_prompt_path.write_text("{{ task_description }}\n{{ transcript }}", encoding="utf-8")
    judge_prompt_path = tmp_path / "judge.md"
    judge_prompt_path.write_text("{{ output_a }}\n{{ output_b }}", encoding="utf-8")
    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()
    (transcript_dir / "call_01.md").write_text("[CUSTOMER]: Hi\n[AGENT]: Hello", encoding="utf-8")

    with Session(engine) as session:
        project = create_project(session, "demo")
        task = create_task(
            session,
            project_id=project.id,
            name="task",
            description_path=str(task_path),
            transcript_root=str(transcript_dir),
            default_judge_prompt_path=str(judge_prompt_path),
        )
        run = create_run(
            session,
            task_id=task.id,
            name="run",
            generator_specs=[
                GeneratorSpec("a", "model-a", 0.2, str(generator_prompt_path)),
                GeneratorSpec("b", "model-b", 0.2, str(generator_prompt_path)),
            ],
            judge_specs=[JudgeSpec("judge", "judge-model", 0.0, str(judge_prompt_path))],
        )

        generations = session.exec(select(Generation).where(Generation.run_id == run.id)).all()
        generations[0].status = Status.failed
        generations[0].error = "no output"
        generations[1].status = Status.failed
        generations[1].output_raw = '{"kept": true}'
        generations[1].error = "has output"
        session.add(generations[0])
        session.add(generations[1])

        match = session.exec(select(Match).where(Match.run_id == run.id)).first()
        match.status = Status.failed
        session.add(match)
        session.commit()

        recover_run(session, run.id)

        assert session.get(Generation, generations[0].id).status == Status.pending
        assert session.get(Generation, generations[0].id).error is None
        assert session.get(Generation, generations[1].id).status == Status.failed
        assert session.get(Generation, generations[1].id).output_raw == '{"kept": true}'
        assert session.get(Match, match.id).status == Status.pending
        assert session.get(Run, run.id).status == Status.pending

        stop_run(session, run.id)

        assert session.get(Run, run.id).status == Status.paused
        logs = session.exec(select(RunLog).where(RunLog.run_id == run.id)).all()
        assert any("Recover run requested" in log.message for log in logs)
        assert any("Stop requested" in log.message for log in logs)


def test_apply_match_elo_updates_leaderboard_immediately(tmp_path):
    """One completed match should update the live ELO rows right away."""

    engine = create_engine(f"sqlite:///{tmp_path / 'elo.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    task_path = tmp_path / "task.md"
    task_path.write_text("Demo task", encoding="utf-8")
    generator_prompt_path = tmp_path / "generator.md"
    generator_prompt_path.write_text("{{ task_description }}\n{{ transcript }}", encoding="utf-8")
    judge_prompt_path = tmp_path / "judge.md"
    judge_prompt_path.write_text("{{ output_a }}\n{{ output_b }}", encoding="utf-8")
    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()
    (transcript_dir / "call_01.md").write_text("[CUSTOMER]: Hi\n[AGENT]: Hello", encoding="utf-8")

    with Session(engine) as session:
        project = create_project(session, "demo")
        task = create_task(
            session,
            project_id=project.id,
            name="task",
            description_path=str(task_path),
            transcript_root=str(transcript_dir),
            default_judge_prompt_path=str(judge_prompt_path),
        )
        run = create_run(
            session,
            task_id=task.id,
            name="run",
            generator_specs=[
                GeneratorSpec("a", "model-a", 0.2, str(generator_prompt_path)),
                GeneratorSpec("b", "model-b", 0.2, str(generator_prompt_path)),
            ],
            judge_specs=[JudgeSpec("judge", "judge-model", 0.0, str(judge_prompt_path))],
        )

        match = session.exec(select(Match).where(Match.run_id == run.id)).first()
        _apply_match_elo(session, match, "A")
        session.commit()

        ratings = {
            row.generator_config_id: row
            for row in session.exec(select(EloRating).where(EloRating.run_id == run.id)).all()
        }

        assert ratings[match.config_a_id].rating == 1516
        assert ratings[match.config_a_id].wins == 1
        assert ratings[match.config_b_id].rating == 1484
        assert ratings[match.config_b_id].losses == 1


def test_pairing_sample_percent_reduces_match_rows(tmp_path):
    """Pairing sample percentage should trim the number of match rows."""

    engine = create_engine(f"sqlite:///{tmp_path / 'pairings.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    task_path = tmp_path / "task.md"
    task_path.write_text("Demo task", encoding="utf-8")
    generator_prompt_path = tmp_path / "generator.md"
    generator_prompt_path.write_text("{{ task_description }}\n{{ transcript }}", encoding="utf-8")
    judge_prompt_path = tmp_path / "judge.md"
    judge_prompt_path.write_text("{{ output_a }}\n{{ output_b }}", encoding="utf-8")
    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()
    (transcript_dir / "call_01.md").write_text("[CUSTOMER]: Hi\n[AGENT]: Hello", encoding="utf-8")

    with Session(engine) as session:
        project = create_project(session, "demo")
        task = create_task(
            session,
            project_id=project.id,
            name="task",
            description_path=str(task_path),
            transcript_root=str(transcript_dir),
            default_judge_prompt_path=str(judge_prompt_path),
        )
        run = create_run(
            session,
            task_id=task.id,
            name="run",
            generator_specs=[
                GeneratorSpec("a", "model-a", 0.2, str(generator_prompt_path)),
                GeneratorSpec("b", "model-b", 0.2, str(generator_prompt_path)),
                GeneratorSpec("c", "model-c", 0.2, str(generator_prompt_path)),
                GeneratorSpec("d", "model-d", 0.2, str(generator_prompt_path)),
            ],
            judge_specs=[JudgeSpec("judge", "judge-model", 0.0, str(judge_prompt_path))],
            pairing_sample_pct=50,
        )

        matches = session.exec(select(Match).where(Match.run_id == run.id)).all()

        assert run.pairing_sample_pct == 50
        assert len(matches) == 3


def test_rename_project_updates_name(tmp_path):
    """Renaming should persist a trimmed project name."""

    engine = create_engine(f"sqlite:///{tmp_path / 'rename-project.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        project = create_project(session, "before")

        renamed = rename_project(session, project.id, " after ")

        assert renamed is not None
        assert renamed.name == "after"
        assert session.get(Project, project.id).name == "after"


def test_create_task_stores_run_defaults(tmp_path):
    """Task creation should store the default pairing and swap settings."""

    engine = create_engine(f"sqlite:///{tmp_path / 'task-defaults.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    task_path = tmp_path / "task.md"
    task_path.write_text("Demo task", encoding="utf-8")
    judge_prompt_path = tmp_path / "judge.md"
    judge_prompt_path.write_text("{{ output_a }}\n{{ output_b }}", encoding="utf-8")
    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()

    with Session(engine) as session:
        project = create_project(session, "demo")
        task = create_task(
            session,
            project_id=project.id,
            name="task",
            description_path=str(task_path),
            transcript_root=str(transcript_dir),
            default_judge_prompt_path=str(judge_prompt_path),
            default_pairing_sample_pct=30,
            default_swap_enabled=False,
        )

        assert task.default_pairing_sample_pct == 30
        assert task.default_swap_enabled is False


def test_delete_task_removes_related_runs_and_snapshots(tmp_path):
    """Deleting a task should cascade through its runs and snapshots."""

    engine = create_engine(f"sqlite:///{tmp_path / 'delete-task.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    task_path = tmp_path / "task.md"
    task_path.write_text("Demo task", encoding="utf-8")
    generator_prompt_path = tmp_path / "generator.md"
    generator_prompt_path.write_text("{{ task_description }}\n{{ transcript }}", encoding="utf-8")
    judge_prompt_path = tmp_path / "judge.md"
    judge_prompt_path.write_text("{{ output_a }}\n{{ output_b }}", encoding="utf-8")
    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()
    (transcript_dir / "call_01.md").write_text("[CUSTOMER]: Hi\n[AGENT]: Hello", encoding="utf-8")

    with Session(engine) as session:
        project = create_project(session, "demo")
        task = create_task(
            session,
            project_id=project.id,
            name="task",
            description_path=str(task_path),
            transcript_root=str(transcript_dir),
            default_judge_prompt_path=str(judge_prompt_path),
        )
        create_run(
            session,
            task_id=task.id,
            name="run",
            generator_specs=[
                GeneratorSpec("a", "model-a", 0.2, str(generator_prompt_path)),
                GeneratorSpec("b", "model-b", 0.2, str(generator_prompt_path)),
            ],
            judge_specs=[JudgeSpec("judge", "judge-model", 0.0, str(judge_prompt_path))],
        )
        run = session.exec(select(Run).where(Run.task_id == task.id)).first()
        session.add(RunAnalysis(run_id=run.id, model_id="analysis", sample_size=1, summary="summary", prompt_snapshot="prompt"))
        session.commit()

        delete_task(session, task.id)
        session.commit()

        assert session.get(Task, task.id) is None
        assert session.exec(select(Run).where(Run.task_id == task.id)).all() == []
        assert session.exec(select(Generation)).all() == []
        assert session.exec(select(GeneratorConfig)).all() == []
        assert session.exec(select(JudgeConfig)).all() == []
        assert session.exec(select(Transcript)).all() == []
        assert session.exec(select(RunAnalysis)).all() == []
        assert session.get(Project, project.id) is not None


def test_delete_project_removes_its_tasks(tmp_path):
    """Deleting a project should remove all of its descendant records."""

    engine = create_engine(f"sqlite:///{tmp_path / 'delete-project.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    task_path = tmp_path / "task.md"
    task_path.write_text("Demo task", encoding="utf-8")
    generator_prompt_path = tmp_path / "generator.md"
    generator_prompt_path.write_text("{{ task_description }}\n{{ transcript }}", encoding="utf-8")
    judge_prompt_path = tmp_path / "judge.md"
    judge_prompt_path.write_text("{{ output_a }}\n{{ output_b }}", encoding="utf-8")
    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()
    (transcript_dir / "call_01.md").write_text("[CUSTOMER]: Hi\n[AGENT]: Hello", encoding="utf-8")

    with Session(engine) as session:
        project = create_project(session, "demo")
        task = create_task(
            session,
            project_id=project.id,
            name="task",
            description_path=str(task_path),
            transcript_root=str(transcript_dir),
            default_judge_prompt_path=str(judge_prompt_path),
        )
        create_run(
            session,
            task_id=task.id,
            name="run",
            generator_specs=[
                GeneratorSpec("a", "model-a", 0.2, str(generator_prompt_path)),
                GeneratorSpec("b", "model-b", 0.2, str(generator_prompt_path)),
            ],
            judge_specs=[JudgeSpec("judge", "judge-model", 0.0, str(judge_prompt_path))],
        )
        session.commit()

        delete_project(session, project.id)
        session.commit()

        assert session.get(Project, project.id) is None
        assert session.exec(select(Task).where(Task.project_id == project.id)).all() == []
        assert session.exec(select(Run)).all() == []


def test_judge_pattern_analysis_available_for_paused_runs_with_enough_votes():
    """Paused runs need enough judge votes before pattern analysis is allowed."""

    run = Run(task_id=1, name="demo", status=Status.paused)

    allowed, _message = judge_pattern_analysis_availability(run, 10)
    blocked, message = judge_pattern_analysis_availability(run, 9)

    assert allowed is True
    assert blocked is False
    assert "at least 10 judge votes" in message
