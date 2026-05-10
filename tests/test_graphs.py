import asyncio

from sqlmodel import Session, SQLModel, create_engine, select

from council.graph_runtime import create_graph_native_run, dataset_items, execute_graph_native_run
from council.graphs import add_constant_node, add_dataset_node, add_judge_node, add_model_node, add_prompt_node, create_edge, create_graph, graph_edges, launch_graph_run, plan_graph, update_node, update_node_position
from council.models import Generation, GeneratorConfig, GraphInvocation, GraphNode, JudgeConfig, Match, Project, Run, Status, Transcript
from council.openrouter import LLMResponse
from council.runner import create_project


def test_graph_plan_counts_generation_matches_and_swapped_judges(tmp_path):
    """Planner should make the graph's execution shape visible before launch."""

    engine = create_engine(f"sqlite:///{tmp_path / 'graph-plan.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()
    for index in range(10):
        (transcript_dir / f"call_{index:02d}.md").write_text(f"call {index}", encoding="utf-8")

    with Session(engine) as session:
        project = create_project(session, "demo")
        graph = create_graph(session, project.id, "graph")
        dataset, _prompt, judge = _basic_graph(session, graph.id)
        update_node(session, dataset.id, title=dataset.title, body="", config_values={"source_type": "markdown", "path": str(transcript_dir), "sample_size": "", "id_column": "call_id", "text_column": "transcript"})
        update_node(session, judge.id, title=judge.title, body=judge.body, config_values={"pairing_sample_pct": "20", "swap_enabled": True, "seed": "", "winner_key": "winner", "reasoning_key": "reasoning"})
        add_model_node(session, graph.id, title="C", model_id="model-c", role="generator")
        add_model_node(session, graph.id, title="D", model_id="model-d", role="generator")
        add_model_node(session, graph.id, title="Judge 2", model_id="judge-2", role="judge")
        add_model_node(session, graph.id, title="Judge 3", model_id="judge-3", role="judge")

        plan = plan_graph(session, graph.id)

        assert plan.transcript_count == 10
        assert plan.generator_model_count == 4
        assert plan.pair_count == 6
        assert plan.sampled_matches_per_transcript == 1
        assert plan.generation_calls == 40
        assert plan.match_count == 10
        assert plan.judge_model_count == 3
        assert plan.judge_calls == 60


def test_launch_graph_compiles_to_existing_run_tables(tmp_path):
    """Graph launches should produce the current auditable run work rows."""

    engine = create_engine(f"sqlite:///{tmp_path / 'graph-launch.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()
    for index in range(3):
        (transcript_dir / f"call_{index:02d}.md").write_text(f"call {index}", encoding="utf-8")

    with Session(engine) as session:
        project = create_project(session, "demo")
        graph = create_graph(session, project.id, "graph")
        dataset, _prompt, _judge = _basic_graph(session, graph.id)
        update_node(session, dataset.id, title=dataset.title, body="", config_values={"source_type": "markdown", "path": str(transcript_dir), "sample_size": "", "id_column": "call_id", "text_column": "transcript"})

        run = launch_graph_run(session, graph.id, max_concurrency=2)

        assert isinstance(run, Run)
        assert run.max_concurrency == 2
        assert session.exec(select(Transcript).where(Transcript.run_id == run.id)).all()
        assert len(session.exec(select(GeneratorConfig).where(GeneratorConfig.run_id == run.id)).all()) == 2
        assert len(session.exec(select(JudgeConfig).where(JudgeConfig.run_id == run.id)).all()) == 1
        assert len(session.exec(select(Generation).where(Generation.run_id == run.id)).all()) == 6
        assert len(session.exec(select(Match).where(Match.run_id == run.id)).all()) == 3


def test_csv_dataset_counts_rows_and_exposes_columns(tmp_path):
    """CSV datasets should count rows and expose row columns as prompt values."""

    engine = create_engine(f"sqlite:///{tmp_path / 'graph-csv.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    csv_path = tmp_path / "calls.csv"
    csv_path.write_text("call_id,transcript,rubric\nc1,hello,be specific\nc2,bye,be brief\n", encoding="utf-8")

    with Session(engine) as session:
        project = create_project(session, "demo")
        graph = create_graph(session, project.id, "graph")
        dataset = add_dataset_node(session, graph.id)
        update_node(
            session,
            dataset.id,
            title=dataset.title,
            body="",
            config_values={
                "source_type": "csv",
                "path": str(csv_path),
                "sample_size": "",
                "id_column": "call_id",
                "text_column": "transcript",
            },
        )

        plan = plan_graph(session, graph.id)
        items = dataset_items(session.exec(select(GraphNode).where(GraphNode.graph_id == graph.id)).all())

        assert plan.transcript_count == 2
        assert items[0].key == "c1"
        assert items[0].values["rubric"] == "be specific"
        assert items[0].values["transcript"] == "hello"


def test_prompt_stages_and_positions_are_persisted(tmp_path):
    """Graphs should support chained prompt stages and saved canvas coordinates."""

    engine = create_engine(f"sqlite:///{tmp_path / 'graph-stages.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()
    (transcript_dir / "call_01.md").write_text("call", encoding="utf-8")

    with Session(engine) as session:
        project = create_project(session, "demo")
        graph = create_graph(session, project.id, "graph")
        dataset, _first_prompt, _judge = _basic_graph(session, graph.id)
        update_node(session, dataset.id, title=dataset.title, body="", config_values={"source_type": "markdown", "path": str(transcript_dir), "sample_size": "", "id_column": "call_id", "text_column": "transcript"})
        prompt = add_prompt_node(session, graph.id, title="Second prompt")
        update_node(session, prompt.id, title=prompt.title, body="{{ previous_output }}", config_values={"upstream_mode": "json"})
        update_node_position(session, prompt.id, x=777, y=333, width=640, height=420)

        refreshed = session.get(GraphNode, prompt.id)
        plan = plan_graph(session, graph.id)

        assert refreshed.x == 777
        assert refreshed.y == 333
        assert refreshed.width == 640
        assert refreshed.height == 420
        assert plan.prompt_stage_count == 2
        assert plan.generation_calls == 4


def test_new_graphs_start_empty_and_edges_persist(tmp_path):
    """New graphs should be blank canvases with explicit socket edges."""

    engine = create_engine(f"sqlite:///{tmp_path / 'graph-empty.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        project = create_project(session, "demo")
        graph = create_graph(session, project.id, "graph")

        assert session.exec(select(GraphNode).where(GraphNode.graph_id == graph.id)).all() == []
        dataset = add_dataset_node(session, graph.id)
        prompt = add_prompt_node(session, graph.id)
        edge = create_edge(
            session,
            graph.id,
            from_node_id=dataset.id,
            from_socket="transcript",
            to_node_id=prompt.id,
            to_socket="transcript",
        )

        edges = graph_edges(session, graph.id)

        assert edges == [edge]


def test_graph_native_run_uses_edge_target_names_for_prompt_inputs(tmp_path):
    """Runtime prompt rendering should follow visual edge target socket names."""

    engine = create_engine(f"sqlite:///{tmp_path / 'graph-runtime-edges.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()
    (transcript_dir / "call_01.md").write_text("hello transcript", encoding="utf-8")

    def session_factory():
        return Session(engine)

    with Session(engine) as session:
        project = create_project(session, "demo")
        graph = create_graph(session, project.id, "graph")
        dataset = add_dataset_node(session, graph.id)
        prompt = add_prompt_node(session, graph.id, title="Prompt")
        constant = add_constant_node(session, graph.id, title="Task Description", body="edge mapped task")
        model = add_model_node(session, graph.id, title="A", model_id="model-a", role="generator")
        update_node(session, dataset.id, title=dataset.title, body="", config_values={"source_type": "markdown", "path": str(transcript_dir), "sample_size": "", "id_column": "call_id", "text_column": "transcript"})
        update_node(session, prompt.id, title=prompt.title, body="{{ task_description }}\n{{ transcript }}", config_values={"upstream_mode": "raw"})
        update_node(session, constant.id, title=constant.title, body=constant.body, config_values={"socket": "Description"})
        create_edge(session, graph.id, from_node_id=constant.id, from_socket="Description", to_node_id=prompt.id, to_socket="task_description")
        create_edge(session, graph.id, from_node_id=dataset.id, from_socket="transcript", to_node_id=prompt.id, to_socket="transcript")
        create_edge(session, graph.id, from_node_id=prompt.id, from_socket="full_prompt", to_node_id=model.id, to_socket="prompt")
        graph_run = create_graph_native_run(session, graph.id, max_concurrency=1, sample_size=1)

    asyncio.run(execute_graph_native_run(graph_run.id, session_factory, client=FakeClient()))

    with Session(engine) as session:
        invocation = session.exec(select(GraphInvocation).where(GraphInvocation.graph_run_id == graph_run.id)).one()
        assert invocation.status == Status.complete
        assert "edge mapped task" in invocation.rendered_prompt
        assert "{{ task_description }}" not in invocation.rendered_prompt


def _node(session: Session, graph_id: int, kind: str):
    return session.exec(select(GraphNode).where(GraphNode.graph_id == graph_id, GraphNode.kind == kind)).first()


def _basic_graph(session: Session, graph_id: int):
    dataset = add_dataset_node(session, graph_id)
    prompt = add_prompt_node(session, graph_id, title="Generator prompt")
    add_model_node(session, graph_id, title="A", model_id="model-a", role="generator")
    add_model_node(session, graph_id, title="B", model_id="model-b", role="generator")
    judge = add_judge_node(session, graph_id)
    add_model_node(session, graph_id, title="Judge 1", model_id="judge-1", role="judge")
    return dataset, prompt, judge


class FakeClient:
    api_key = "test"

    async def chat(self, **_kwargs):
        return LLMResponse(text='{"ok": true}', raw={}, prompt_tokens=3, completion_tokens=2, cost=0.0)
