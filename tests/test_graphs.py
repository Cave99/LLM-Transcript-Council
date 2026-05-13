import asyncio

from sqlmodel import Session, SQLModel, create_engine, select

from council.graph_runtime import continue_graph_native_run, create_graph_native_run, execute_graph_native_run, graph_run_leaderboards, submit_human_judgement
from council.graph_spec import validate_spec_payload
from council.graphs import create_graph, plan_graph, semantic_nodes_edges
from council.models import GraphInvocation, GraphJudgement, GraphPair, Project, Status
from council.openrouter import LLMResponse


def test_spec_validation_reports_stable_errors():
    result = validate_spec_payload({"version": 1, "stages": [{"id": "score", "candidates": []}], "evaluators": [{"id": "judge", "target_stage": "missing"}]})

    assert not result.valid
    assert {error.code for error in result.errors} == {"unknown_target_stage", "missing_judge_model", "missing_prompt"}


def test_spec_plan_counts_matrix_generation_and_pairs(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'plan.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()
    for index in range(3):
        (transcript_dir / f"call_{index}.md").write_text(f"call {index}", encoding="utf-8")

    with Session(engine) as session:
        project = Project(name="demo")
        session.add(project)
        session.commit()
        session.refresh(project)
        graph = create_graph(session, project.id, "graph", _spec(transcript_dir))

        plan = plan_graph(session, graph.id)

        assert plan.transcript_count == 3
        assert plan.generation_calls == 18
        assert plan.pair_count == 18
        assert plan.judge_calls == 18


def test_semantic_graph_includes_candidate_nodes(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'layout.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()

    with Session(engine) as session:
        project = Project(name="demo")
        session.add(project)
        session.commit()
        session.refresh(project)
        graph = create_graph(session, project.id, "graph", _spec(transcript_dir))

        nodes, edges = semantic_nodes_edges(graph)

    kinds_by_id = {node.id: node.kind for node in nodes}
    nodes_by_id = {node.id: node for node in nodes}
    assert kinds_by_id["score_a"] == "candidate"
    assert kinds_by_id["score_b"] == "candidate"
    assert nodes_by_id["score_a"].x > nodes_by_id["scoring"].x
    assert nodes_by_id["coaching"].x > nodes_by_id["score_a"].x
    assert {"id": "scoring->score_a", "source": "scoring", "target": "score_a"} in edges
    assert {"id": "score_a->coaching", "source": "score_a", "target": "coaching"} in edges
    assert {"id": "score_b->coaching", "source": "score_b", "target": "coaching"} in edges
    assert {"id": "scoring->coaching", "source": "scoring", "target": "coaching"} not in edges
    assert {"id": "coach_a->judge", "source": "coach_a", "target": "judge"} in edges


def test_spec_runtime_stores_generation_pairs_judgements_and_human_reviews(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'runtime.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()
    (transcript_dir / "call_1.md").write_text("hello transcript", encoding="utf-8")

    def session_factory():
        return Session(engine)

    with Session(engine) as session:
        project = Project(name="demo")
        session.add(project)
        session.commit()
        session.refresh(project)
        graph = create_graph(session, project.id, "graph", _spec(transcript_dir, include_human=True))
        run = create_graph_native_run(session, graph.id, max_concurrency=1, sample_size=1)
        run_id = run.id

    asyncio.run(execute_graph_native_run(run_id, session_factory, client=FakeClient()))

    with Session(engine) as session:
        generations = session.exec(select(GraphInvocation).where(GraphInvocation.graph_run_id == run_id, GraphInvocation.kind == "generation")).all()
        judges = session.exec(select(GraphInvocation).where(GraphInvocation.graph_run_id == run_id, GraphInvocation.kind == "llm_judge")).all()
        pairs = session.exec(select(GraphPair).where(GraphPair.graph_run_id == run_id)).all()
        judgements = session.exec(select(GraphJudgement)).all()

        assert len(generations) == 6
        assert judges
        assert any("hello transcript" in row.rendered_prompt for row in generations)
        assert any(pair.status == Status.pending for pair in pairs)
        assert any(judgement.evaluator_type == "llm_pairwise" for judgement in judgements)

        human_pair = next(pair for pair in pairs if pair.evaluator_id == "human_review")
        judgement = submit_human_judgement(session, run_id, human_pair.id, winner="A", reasoning="better", human_reviewer="cave")
        assert judgement.winner == "A"

        rows = graph_run_leaderboards(session, run_id)[0]["rows"]
        assert rows


def test_json_stage_blocks_judges_when_a_candidate_returns_invalid_json(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'json-gate.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()
    (transcript_dir / "call_1.md").write_text("hello transcript", encoding="utf-8")

    def session_factory():
        return Session(engine)

    with Session(engine) as session:
        project = Project(name="demo")
        session.add(project)
        session.commit()
        session.refresh(project)
        graph = create_graph(session, project.id, "graph", _json_gate_spec(transcript_dir))
        run = create_graph_native_run(session, graph.id, max_concurrency=1, sample_size=1)
        run_id = run.id

    asyncio.run(execute_graph_native_run(run_id, session_factory, client=JsonGateClient()))

    with Session(engine) as session:
        generations = session.exec(select(GraphInvocation).where(GraphInvocation.graph_run_id == run_id, GraphInvocation.kind == "generation")).all()
        judges = session.exec(select(GraphInvocation).where(GraphInvocation.graph_run_id == run_id, GraphInvocation.kind == "llm_judge")).all()
        pairs = session.exec(select(GraphPair).where(GraphPair.graph_run_id == run_id)).all()

        assert len(generations) == 2
        failed = next(row for row in generations if row.candidate_id == "bad_json")
        assert failed.status == Status.failed
        assert failed.error_category == "invalid_json_output"
        assert judges == []
        assert pairs == []


def test_continue_requeues_stuck_running_invocations(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'resume.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()
    (transcript_dir / "call_1.md").write_text("hello transcript", encoding="utf-8")

    with Session(engine) as session:
        project = Project(name="demo")
        session.add(project)
        session.commit()
        session.refresh(project)
        graph = create_graph(session, project.id, "graph", _spec(transcript_dir))
        run = create_graph_native_run(session, graph.id, max_concurrency=1, sample_size=1)
        run_id = run.id
        session.add(
            GraphInvocation(
                graph_run_id=run_id,
                kind="generation",
                stage_id="scoring",
                candidate_id="score_a",
                item_key="call_1",
                lineage_key="score_a",
                model_id="model-a",
                stage_index=0,
                status=Status.running,
                rendered_prompt="prompt",
            )
        )
        session.commit()

        resumed = continue_graph_native_run(session, run_id)

        refreshed = session.exec(select(GraphInvocation).where(GraphInvocation.graph_run_id == run_id)).all()
        assert resumed.status == Status.pending
        assert all(row.status == Status.pending for row in refreshed)


def _spec(transcript_dir, include_human=False):
    evaluators = [
        {
            "id": "judge",
            "title": "Judge",
            "type": "llm_pairwise",
            "target_stage": "coaching",
            "model": "judge-model",
            "prompt_inline": "{{ output_a }}\n{{ output_b }}",
            "pairing": {"sample_pct": 100, "swap": False},
        }
    ]
    if include_human:
        evaluators.append({"id": "human_review", "title": "Human Review", "type": "human_pairwise", "target_stage": "coaching", "pairing": {"sample_pct": 100, "swap": False}})
    return {
        "version": 1,
        "dataset": {"provider": "markdown_folder", "config": {"path": str(transcript_dir), "sample_size": None}},
        "stages": [
            {
                "id": "scoring",
                "title": "Scoring",
                "candidates": [
                    {"id": "score_a", "title": "Score A", "model": "model-a", "prompt_inline": "score a {{ transcript }}"},
                    {"id": "score_b", "title": "Score B", "model": "model-b", "prompt_inline": "score b {{ transcript }}"},
                ],
            },
            {
                "id": "coaching",
                "title": "Coaching",
                "candidates": [
                    {"id": "coach_a", "title": "Coach A", "model": "model-a", "prompt_inline": "coach a {{ previous_output }}"},
                    {"id": "coach_b", "title": "Coach B", "model": "model-b", "prompt_inline": "coach b {{ previous_output }}"},
                ],
            },
        ],
        "evaluators": evaluators,
    }


def _json_gate_spec(transcript_dir):
    return {
        "version": 1,
        "dataset": {"provider": "markdown_folder", "config": {"path": str(transcript_dir), "sample_size": None}},
        "stages": [
            {
                "id": "analysis",
                "title": "Analysis",
                "upstream_output": "json",
                "candidates": [
                    {"id": "good_json", "title": "Good JSON", "model": "model-good", "prompt_inline": "json a {{ transcript }}"},
                    {"id": "bad_json", "title": "Bad JSON", "model": "model-bad", "prompt_inline": "json b {{ transcript }}"},
                ],
            },
        ],
        "evaluators": [
            {
                "id": "judge",
                "title": "Judge",
                "type": "llm_pairwise",
                "target_stage": "analysis",
                "model": "judge-model",
                "prompt_inline": "{{ output_a }}\n{{ output_b }}",
                "pairing": {"sample_pct": 100, "swap": False},
            }
        ],
    }


class FakeClient:
    api_key = "test"

    async def chat(self, **kwargs):
        content = kwargs["messages"][0]["content"]
        if "output_b" in content or "response" in kwargs["model"] or kwargs["model"] == "judge-model":
            return LLMResponse(text='{"winner":"A","reasoning":"better"}', raw={}, prompt_tokens=10, completion_tokens=5)
        return LLMResponse(text=f"response from {kwargs['model']}: {content}", raw={}, prompt_tokens=10, completion_tokens=5)


class JsonGateClient:
    api_key = "test"

    async def chat(self, **kwargs):
        model = kwargs["model"]
        if model == "model-good":
            return LLMResponse(text='{"ok": true, "reason": "valid"}', raw={}, prompt_tokens=10, completion_tokens=5)
        if model == "model-bad":
            return LLMResponse(text="We need to decide if cross-sell", raw={}, prompt_tokens=10, completion_tokens=5)
        return LLMResponse(text='{"winner":"A","reasoning":"better"}', raw={}, prompt_tokens=10, completion_tokens=5)
