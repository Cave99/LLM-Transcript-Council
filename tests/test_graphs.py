import asyncio

from sqlmodel import Session, SQLModel, create_engine, select

from council.analysis import generate_graph_run_judge_summary, sample_graph_judge_reasoning_traces
from council.graph_runtime import create_graph_native_run, dataset_items, execute_graph_native_run, graph_run_leaderboards
from council.graphs import add_constant_node, add_dataset_node, add_judge_node, add_model_node, add_prompt_node, create_edge, create_graph, graph_edges, graph_nodes, launch_graph_run, plan_graph, update_node, update_node_position
from council.models import Generation, GeneratorConfig, GraphInvocation, GraphNode, GraphRunAnalysis, JudgeConfig, Match, Project, Run, Status, Transcript
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


def test_graph_plan_scopes_models_and_judges_by_visual_phase_edges(tmp_path):
    """Planner should not apply every model node to every prompt and judge round."""

    engine = create_engine(f"sqlite:///{tmp_path / 'graph-phase-plan.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()
    for index in range(11):
        (transcript_dir / f"call_{index:02d}.md").write_text(f"call {index}", encoding="utf-8")

    with Session(engine) as session:
        project = create_project(session, "demo")
        graph = create_graph(session, project.id, "graph")
        dataset = add_dataset_node(session, graph.id)
        prompt_a = add_prompt_node(session, graph.id, title="Prompt A")
        prompt_b = add_prompt_node(session, graph.id, title="Prompt B")
        judge_a = add_judge_node(session, graph.id, title="Judge round 1")
        judge_b = add_judge_node(session, graph.id, title="Judge round 2")
        update_node(session, dataset.id, title=dataset.title, body="", config_values={"source_type": "markdown", "path": str(transcript_dir), "sample_size": "", "id_column": "call_id", "text_column": "transcript"})
        update_node(session, judge_a.id, title=judge_a.title, body=judge_a.body, config_values={"pairing_sample_pct": "10", "swap_enabled": False, "seed": "", "winner_key": "winner", "reasoning_key": "reasoning"})
        update_node(session, judge_b.id, title=judge_b.title, body=judge_b.body, config_values={"pairing_sample_pct": "10", "swap_enabled": False, "seed": "", "winner_key": "winner", "reasoning_key": "reasoning"})
        stage_a_models = [add_model_node(session, graph.id, title=f"A{i}", model_id=f"a-{i}", role="generator") for i in range(3)]
        stage_b_models = [add_model_node(session, graph.id, title=f"B{i}", model_id=f"b-{i}", role="generator") for i in range(3)]
        judge_a_models = [add_model_node(session, graph.id, title=f"JA{i}", model_id=f"ja-{i}", role="judge") for i in range(2)]
        judge_b_models = [add_model_node(session, graph.id, title=f"JB{i}", model_id=f"jb-{i}", role="judge") for i in range(2)]
        for model in stage_a_models:
            create_edge(session, graph.id, from_node_id=prompt_a.id, from_socket="full_prompt", to_node_id=model.id, to_socket="prompt")
        for model in stage_b_models:
            create_edge(session, graph.id, from_node_id=prompt_b.id, from_socket="full_prompt", to_node_id=model.id, to_socket="prompt")
        create_edge(session, graph.id, from_node_id=prompt_a.id, from_socket="full_prompt", to_node_id=judge_a.id, to_socket="models")
        create_edge(session, graph.id, from_node_id=prompt_b.id, from_socket="full_prompt", to_node_id=judge_b.id, to_socket="models")
        for model in judge_a_models:
            create_edge(session, graph.id, from_node_id=judge_a.id, from_socket="judge_prompt", to_node_id=model.id, to_socket="judge_prompt")
        for model in judge_b_models:
            create_edge(session, graph.id, from_node_id=judge_b.id, from_socket="judge_prompt", to_node_id=model.id, to_socket="judge_prompt")

        plan = plan_graph(session, graph.id)

        assert plan.generation_calls == 132
        assert plan.match_count == 55
        assert plan.judge_calls == 110


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
        assert plan.generation_calls == 6


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


def test_graph_native_run_fans_out_downstream_outputs_by_item_branch(tmp_path):
    """A downstream prompt should run once per same-item upstream output and model."""

    engine = create_engine(f"sqlite:///{tmp_path / 'graph-runtime-fanout.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()
    (transcript_dir / "call_01.md").write_text("hello transcript", encoding="utf-8")

    def session_factory():
        return Session(engine)

    with Session(engine) as session:
        project = create_project(session, "demo")
        graph = create_graph(session, project.id, "graph")
        dataset, first_prompt, judge = _basic_graph(session, graph.id)
        second_prompt = add_prompt_node(session, graph.id, title="Second prompt")
        update_node(session, dataset.id, title=dataset.title, body="", config_values={"source_type": "markdown", "path": str(transcript_dir), "sample_size": "", "id_column": "call_id", "text_column": "transcript"})
        update_node(session, first_prompt.id, title=first_prompt.title, body="first {{ transcript }}", config_values={"upstream_mode": "raw"})
        update_node(session, second_prompt.id, title=second_prompt.title, body="second {{ transcript }} {{ previous_output }}", config_values={"upstream_mode": "raw"})
        graph_run = create_graph_native_run(session, graph.id, max_concurrency=1, sample_size=1)
        graph_run_id = graph_run.id
        judge_id = judge.id
        second_prompt_id = second_prompt.id

    asyncio.run(execute_graph_native_run(graph_run_id, session_factory, client=FakeClient()))

    with Session(engine) as session:
        generations = session.exec(
            select(GraphInvocation)
            .where(GraphInvocation.graph_run_id == graph_run_id)
            .where(GraphInvocation.node_id != judge_id)
        ).all()
        second_stage = [row for row in generations if row.node_id == second_prompt_id]

        assert len(generations) == 6
        assert len(second_stage) == 4
        assert {row.item_key.split("|", 1)[0] for row in second_stage} == {"call_01"}
        assert all("hello transcript" in row.rendered_prompt for row in second_stage)


def test_graph_runtime_scopes_models_by_prompt_edges(tmp_path):
    """Runtime should use only the generator models connected to each prompt stage."""

    engine = create_engine(f"sqlite:///{tmp_path / 'graph-runtime-scoped-models.db'}", connect_args={"check_same_thread": False})
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
        prompt_a = add_prompt_node(session, graph.id, title="Prompt A")
        prompt_b = add_prompt_node(session, graph.id, title="Prompt B")
        models_a = [add_model_node(session, graph.id, title=f"A{i}", model_id=f"a-{i}", role="generator") for i in range(2)]
        models_b = [add_model_node(session, graph.id, title=f"B{i}", model_id=f"b-{i}", role="generator") for i in range(3)]
        update_node(session, dataset.id, title=dataset.title, body="", config_values={"source_type": "markdown", "path": str(transcript_dir), "sample_size": "", "id_column": "call_id", "text_column": "transcript"})
        for model in models_a:
            create_edge(session, graph.id, from_node_id=prompt_a.id, from_socket="full_prompt", to_node_id=model.id, to_socket="prompt")
        for model in models_b:
            create_edge(session, graph.id, from_node_id=prompt_b.id, from_socket="full_prompt", to_node_id=model.id, to_socket="prompt")
        graph_run = create_graph_native_run(session, graph.id, max_concurrency=1, sample_size=1)
        graph_run_id = graph_run.id
        prompt_a_id = prompt_a.id
        prompt_b_id = prompt_b.id

    asyncio.run(execute_graph_native_run(graph_run_id, session_factory, client=FakeClient()))

    with Session(engine) as session:
        stage_a = session.exec(select(GraphInvocation).where(GraphInvocation.graph_run_id == graph_run_id, GraphInvocation.node_id == prompt_a_id)).all()
        stage_b = session.exec(select(GraphInvocation).where(GraphInvocation.graph_run_id == graph_run_id, GraphInvocation.node_id == prompt_b_id)).all()

        assert len(stage_a) == 2
        assert len(stage_b) == 6


def test_judge_prompt_targets_connected_prompt_stage(tmp_path):
    """A judge connected to the first prompt should judge first-stage outputs."""

    engine = create_engine(f"sqlite:///{tmp_path / 'graph-runtime-judge-target.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()
    (transcript_dir / "call_01.md").write_text("hello transcript", encoding="utf-8")

    def session_factory():
        return Session(engine)

    with Session(engine) as session:
        project = create_project(session, "demo")
        graph = create_graph(session, project.id, "graph")
        dataset, first_prompt, judge = _basic_graph(session, graph.id)
        add_prompt_node(session, graph.id, title="Second prompt")
        update_node(session, dataset.id, title=dataset.title, body="", config_values={"source_type": "markdown", "path": str(transcript_dir), "sample_size": "", "id_column": "call_id", "text_column": "transcript"})
        create_edge(session, graph.id, from_node_id=first_prompt.id, from_socket="output", to_node_id=judge.id, to_socket="output")
        graph_run = create_graph_native_run(session, graph.id, max_concurrency=1, sample_size=1)
        graph_run_id = graph_run.id
        judge_id = judge.id

    asyncio.run(execute_graph_native_run(graph_run_id, session_factory, client=FakeClient()))

    with Session(engine) as session:
        judge_invocations = session.exec(
            select(GraphInvocation)
            .where(GraphInvocation.graph_run_id == graph_run_id)
            .where(GraphInvocation.node_id == judge_id)
        ).all()

        assert len(judge_invocations) == 1
        assert ">" not in judge_invocations[0].item_key


def test_judge_prompt_can_target_stage_through_connected_generator_models(tmp_path):
    """A judge fed by first-stage model outputs should not fall back to the final stage."""

    engine = create_engine(f"sqlite:///{tmp_path / 'graph-runtime-judge-model-target.db'}", connect_args={"check_same_thread": False})
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
        prompt_a = add_prompt_node(session, graph.id, title="Prompt A")
        prompt_b = add_prompt_node(session, graph.id, title="Prompt B")
        judge = add_judge_node(session, graph.id)
        model_a = add_model_node(session, graph.id, title="A", model_id="model-a", role="generator")
        model_b = add_model_node(session, graph.id, title="B", model_id="model-b", role="generator")
        model_c = add_model_node(session, graph.id, title="C", model_id="model-c", role="generator")
        model_d = add_model_node(session, graph.id, title="D", model_id="model-d", role="generator")
        judge_model = add_model_node(session, graph.id, title="Judge 1", model_id="judge-1", role="judge")
        update_node(session, dataset.id, title=dataset.title, body="", config_values={"source_type": "markdown", "path": str(transcript_dir), "sample_size": "", "id_column": "call_id", "text_column": "transcript"})
        create_edge(session, graph.id, from_node_id=prompt_a.id, from_socket="full_prompt", to_node_id=model_a.id, to_socket="prompt")
        create_edge(session, graph.id, from_node_id=prompt_a.id, from_socket="full_prompt", to_node_id=model_b.id, to_socket="prompt")
        create_edge(session, graph.id, from_node_id=prompt_b.id, from_socket="full_prompt", to_node_id=model_c.id, to_socket="prompt")
        create_edge(session, graph.id, from_node_id=prompt_b.id, from_socket="full_prompt", to_node_id=model_d.id, to_socket="prompt")
        create_edge(session, graph.id, from_node_id=model_a.id, from_socket="raw", to_node_id=judge.id, to_socket="models")
        create_edge(session, graph.id, from_node_id=model_b.id, from_socket="raw", to_node_id=judge.id, to_socket="models")
        create_edge(session, graph.id, from_node_id=judge.id, from_socket="judge_prompt", to_node_id=judge_model.id, to_socket="judge_prompt")
        graph_run = create_graph_native_run(session, graph.id, max_concurrency=1, sample_size=1)
        graph_run_id = graph_run.id
        judge_id = judge.id

    asyncio.run(execute_graph_native_run(graph_run_id, session_factory, client=FakeClient()))

    with Session(engine) as session:
        judge_invocations = session.exec(
            select(GraphInvocation)
            .where(GraphInvocation.graph_run_id == graph_run_id)
            .where(GraphInvocation.node_id == judge_id)
        ).all()

        assert len(judge_invocations) == 1
        assert ">" not in judge_invocations[0].item_key


def test_graph_leaderboard_view_can_aggregate_or_show_chains(tmp_path):
    """Leaderboard view mode should be a read-time choice over chain judge keys."""

    engine = create_engine(f"sqlite:///{tmp_path / 'graph-leaderboard-view.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        project = create_project(session, "demo")
        graph = create_graph(session, project.id, "graph")
        _dataset, _prompt, judge = _basic_graph(session, graph.id)
        model_a = session.exec(select(GraphNode).where(GraphNode.graph_id == graph.id, GraphNode.title == "A")).one()
        model_b = session.exec(select(GraphNode).where(GraphNode.graph_id == graph.id, GraphNode.title == "B")).one()
        judge_model = session.exec(select(GraphNode).where(GraphNode.graph_id == graph.id, GraphNode.title == "Judge 1")).one()
        graph_run = create_graph_native_run(session, graph.id, max_concurrency=1)
        graph_run.status = Status.complete
        session.add(graph_run)
        session.add(
            GraphInvocation(
                graph_run_id=graph_run.id,
                node_id=judge.id,
                model_node_id=judge_model.id,
                item_key=f"call_01:{model_a.id}>{model_b.id}-vs-{model_b.id}>{model_a.id}",
                stage_index=10_000,
                status=Status.complete,
                output_json='{"winner": "A", "reasoning": "chain wins"}',
            )
        )
        session.commit()

        aggregate = graph_run_leaderboards(session, graph_run.id, graph_nodes(session, graph.id), view_mode="aggregate")[0]["rows"]
        chain = graph_run_leaderboards(session, graph_run.id, graph_nodes(session, graph.id), view_mode="chain")[0]["rows"]

        assert {row["label"] for row in aggregate} == {"A", "B"}
        assert {row["label"] for row in chain} == {"A -> B", "B -> A"}


def test_leaderboard_truncates_stale_chain_keys_to_judge_target_stage(tmp_path):
    """Old runs with over-long judge keys should display at the judge target depth."""

    engine = create_engine(f"sqlite:///{tmp_path / 'graph-leaderboard-stale-chain.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        project = create_project(session, "demo")
        graph = create_graph(session, project.id, "graph")
        prompt_a = add_prompt_node(session, graph.id, title="Prompt A")
        prompt_b = add_prompt_node(session, graph.id, title="Prompt B")
        judge = add_judge_node(session, graph.id, title="Scoring Judges")
        model_a = add_model_node(session, graph.id, title="A", model_id="model-a", role="generator")
        model_b = add_model_node(session, graph.id, title="B", model_id="model-b", role="generator")
        model_c = add_model_node(session, graph.id, title="C", model_id="model-c", role="generator")
        judge_model = add_model_node(session, graph.id, title="Judge", model_id="judge", role="judge")
        create_edge(session, graph.id, from_node_id=prompt_a.id, from_socket="full_prompt", to_node_id=model_a.id, to_socket="prompt")
        create_edge(session, graph.id, from_node_id=prompt_a.id, from_socket="full_prompt", to_node_id=model_b.id, to_socket="prompt")
        create_edge(session, graph.id, from_node_id=prompt_b.id, from_socket="full_prompt", to_node_id=model_c.id, to_socket="prompt")
        create_edge(session, graph.id, from_node_id=model_a.id, from_socket="json", to_node_id=judge.id, to_socket="models")
        create_edge(session, graph.id, from_node_id=model_b.id, from_socket="json", to_node_id=judge.id, to_socket="models")
        graph_run = create_graph_native_run(session, graph.id, max_concurrency=1)
        graph_run.status = Status.complete
        session.add(graph_run)
        session.add(
            GraphInvocation(
                graph_run_id=graph_run.id,
                node_id=judge.id,
                model_node_id=judge_model.id,
                item_key=f"call_01:{model_a.id}>{model_c.id}-vs-{model_b.id}>{model_c.id}",
                stage_index=10_000,
                status=Status.complete,
                output_json='{"winner": "A", "reasoning": "stale downstream keys"}',
            )
        )
        session.commit()

        rows = graph_run_leaderboards(session, graph_run.id, graph_nodes(session, graph.id), view_mode="chain")[1]["rows"]

        assert {row["label"] for row in rows} == {"A", "B"}


def test_graph_judge_summary_samples_top_model_wins_and_losses(tmp_path):
    """Graph summaries should cap top-model win and loss reasoning samples."""

    engine = create_engine(f"sqlite:///{tmp_path / 'graph-summary-sample.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        project = create_project(session, "demo")
        graph = create_graph(session, project.id, "graph")
        _dataset, _prompt, judge = _basic_graph(session, graph.id)
        model_a = session.exec(select(GraphNode).where(GraphNode.graph_id == graph.id, GraphNode.title == "A")).one()
        model_b = session.exec(select(GraphNode).where(GraphNode.graph_id == graph.id, GraphNode.title == "B")).one()
        judge_model = session.exec(select(GraphNode).where(GraphNode.graph_id == graph.id, GraphNode.title == "Judge 1")).one()
        graph_run = create_graph_native_run(session, graph.id, max_concurrency=1)
        graph_run.status = Status.complete
        session.add(graph_run)
        for index in range(25):
            session.add(_judge_invocation(graph_run.id, judge.id, judge_model.id, model_a.id, model_b.id, index, "A", f"A was more specific {index}"))
        for index in range(15):
            session.add(_judge_invocation(graph_run.id, judge.id, judge_model.id, model_a.id, model_b.id, index + 25, "B", f"B was clearer {index}"))
        session.commit()

        traces = sample_graph_judge_reasoning_traces(session, graph_run.id, model_a.id)

        assert len(traces["wins"]) == 20
        assert len(traces["losses"]) == 10
        assert all("specific" in trace["reasoning"] for trace in traces["wins"])
        assert all("clearer" in trace["reasoning"] for trace in traces["losses"])


def test_generate_graph_judge_summary_persists_model_summary(tmp_path, monkeypatch):
    """Graph judge summaries should call the configured model and save the result."""

    engine = create_engine(f"sqlite:///{tmp_path / 'graph-summary-generate.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    def session_factory():
        return Session(engine)

    with Session(engine) as session:
        project = create_project(session, "demo")
        graph = create_graph(session, project.id, "graph")
        _dataset, _prompt, judge = _basic_graph(session, graph.id)
        model_a = session.exec(select(GraphNode).where(GraphNode.graph_id == graph.id, GraphNode.title == "A")).one()
        model_b = session.exec(select(GraphNode).where(GraphNode.graph_id == graph.id, GraphNode.title == "B")).one()
        judge_model = session.exec(select(GraphNode).where(GraphNode.graph_id == graph.id, GraphNode.title == "Judge 1")).one()
        graph_run = create_graph_native_run(session, graph.id, max_concurrency=1)
        graph_run.status = Status.complete
        session.add(graph_run)
        session.add(_judge_invocation(graph_run.id, judge.id, judge_model.id, model_a.id, model_b.id, 1, "A", "A gave more concrete transcript-grounded steps."))
        session.add(_judge_invocation(graph_run.id, judge.id, judge_model.id, model_a.id, model_b.id, 2, "B", "B was shorter and easier to scan."))
        session.commit()
        graph_run_id = graph_run.id

    client = SummaryClient()
    monkeypatch.setenv("JUDGE_SUMMARY_MODEL", "qwen/qwen3.6-flash")
    monkeypatch.setenv("JUDGE_SUMMARY_REASONING", "medium")

    asyncio.run(generate_graph_run_judge_summary(graph_run_id, session_factory, client=client))

    with Session(engine) as session:
        analysis = session.exec(select(GraphRunAnalysis)).one()
        assert analysis.model_id == "qwen/qwen3.6-flash"
        assert analysis.win_sample_size == 1
        assert analysis.loss_sample_size == 1
        assert analysis.summary == "A usually won for concrete evidence. It lost when brevity mattered."
        assert client.kwargs["reasoning_effort"] == "medium"
        assert "Winning traces" in client.kwargs["messages"][1]["content"]


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


class SummaryClient:
    api_key = "test"

    async def chat(self, **kwargs):
        self.kwargs = kwargs
        return LLMResponse(text="A usually won for concrete evidence. It lost when brevity mattered.", raw={}, prompt_tokens=4, completion_tokens=5, cost=0.0)


def _judge_invocation(graph_run_id: int, judge_id: int, judge_model_id: int, model_a_id: int, model_b_id: int, index: int, winner: str, reasoning: str) -> GraphInvocation:
    return GraphInvocation(
        graph_run_id=graph_run_id,
        node_id=judge_id,
        model_node_id=judge_model_id,
        item_key=f"call_{index:02d}:{model_a_id}-vs-{model_b_id}",
        stage_index=10_000,
        status=Status.complete,
        output_json=f'{{"winner": "{winner}", "reasoning": "{reasoning}"}}',
    )
