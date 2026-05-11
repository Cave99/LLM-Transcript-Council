from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from backend.deps import get_session
from backend.main import app
from council.models import Project


def test_project_graph_node_edge_api_flow(tmp_path):
    """Graph-native API should expose project, graph, node, and edge CRUD."""

    engine = create_engine(f"sqlite:///{tmp_path / 'api.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        client = TestClient(app)

        project_response = client.post("/api/projects", json={"name": "demo"})
        assert project_response.status_code == 200
        project = project_response.json()
        assert project["name"] == "demo"

        graph_response = client.post("/api/graphs", json={"project_id": project["id"], "name": "graph"})
        assert graph_response.status_code == 200
        graph = graph_response.json()

        dataset = client.post(f"/api/graphs/{graph['id']}/nodes", json={"kind": "dataset"}).json()
        prompt = client.post(f"/api/graphs/{graph['id']}/nodes", json={"kind": "prompt"}).json()
        edge_response = client.post(
            f"/api/graphs/{graph['id']}/edges",
            json={
                "from_node_id": dataset["id"],
                "from_socket": "transcript",
                "to_node_id": prompt["id"],
                "to_socket": "transcript",
            },
        )
        assert edge_response.status_code == 200

        updated = client.patch(
            f"/api/nodes/{prompt['id']}",
            json={"title": "Prompt A", "body": "Use {{ transcript }}", "config": {"upstream_mode": "raw"}},
        ).json()
        assert updated["title"] == "Prompt A"
        assert updated["input_sockets"] == ["transcript"]

        detail = client.get(f"/api/graphs/{graph['id']}").json()
        assert detail["graph"]["id"] == graph["id"]
        assert len(detail["nodes"]) == 2
        assert len(detail["edges"]) == 1
        assert "generation_calls" in detail["plan"]
    finally:
        app.dependency_overrides.clear()


def test_graph_run_detail_api_returns_progress(tmp_path):
    """Graph run detail endpoint should include progress and report sections."""

    engine = create_engine(f"sqlite:///{tmp_path / 'api-run.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        client = TestClient(app)
        project_id = client.post("/api/projects", json={"name": "demo"}).json()["id"]
        graph_id = client.post("/api/graphs", json={"project_id": project_id, "name": "graph"}).json()["id"]
        run = client.post(f"/api/graphs/{graph_id}/launch", json={"run_mode": "test", "max_concurrency": 1}).json()

        detail = client.get(f"/api/graph-runs/{run['id']}").json()
        assert detail["run"]["id"] == run["id"]
        assert detail["progress"]["total"] == 0
        assert detail["leaderboards"]
        assert detail["invocations"] == []
    finally:
        app.dependency_overrides.clear()


def test_project_delete_removes_graph_native_rows(tmp_path):
    """Deleting a project through the API should remove graph-native children."""

    engine = create_engine(f"sqlite:///{tmp_path / 'api-delete.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        client = TestClient(app)
        project_id = client.post("/api/projects", json={"name": "demo"}).json()["id"]
        client.post("/api/graphs", json={"project_id": project_id, "name": "graph"})

        assert client.delete(f"/api/projects/{project_id}").status_code == 200
        with Session(engine) as session:
            assert session.get(Project, project_id) is None
    finally:
        app.dependency_overrides.clear()
