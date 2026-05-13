from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from backend.deps import get_session
from backend.main import app
from council.models import Project


def test_project_graph_spec_api_flow(tmp_path):
    """Graph API should expose spec-backed graph CRUD and validation."""

    engine = create_engine(f"sqlite:///{tmp_path / 'api.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        client = TestClient(app)
        project = client.post("/api/projects", json={"name": "demo"}).json()
        graph = client.post("/api/graphs", json={"project_id": project["id"], "name": "graph"}).json()

        detail = client.get(f"/api/graphs/{graph['id']}").json()
        assert detail["spec"]["version"] == 1
        assert detail["nodes"][0]["id"] == "dataset"

        spec = {
            "version": 1,
            "dataset": {"provider": "markdown_folder", "config": {"path": str(tmp_path)}},
            "stages": [{"id": "score", "candidates": [{"id": "a", "model": "model-a", "prompt_inline": "{{ transcript }}"}]}],
            "evaluators": [],
        }
        validation = client.post("/api/graphs/validate-spec", json=spec).json()
        assert validation["valid"] is True
        updated = client.put(f"/api/graphs/{graph['id']}/spec", json=spec).json()
        assert updated["spec"]["stages"][0]["id"] == "score"
        assert "generation_calls" in updated["plan"]
    finally:
        app.dependency_overrides.clear()


def test_graph_draft_save_allows_incomplete_candidate(tmp_path):
    """Draft edits should persist empty candidate nodes before they are executable."""

    engine = create_engine(f"sqlite:///{tmp_path / 'api-draft.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        client = TestClient(app)
        project = client.post("/api/projects", json={"name": "demo"}).json()
        graph = client.post("/api/graphs", json={"project_id": project["id"], "name": "graph"}).json()
        spec = {
            "version": 1,
            "dataset": {"provider": "markdown_folder", "config": {"path": str(tmp_path)}},
            "stages": [{"id": "score", "candidates": [{"id": "candidate_1", "title": "New candidate", "model": "", "prompt_inline": ""}]}],
            "evaluators": [],
        }

        updated = client.patch(f"/api/graphs/{graph['id']}", json={"spec": spec}).json()

        assert updated["spec"]["stages"][0]["candidates"][0]["id"] == "candidate_1"
        assert {"id": "candidate_1", "kind": "candidate", "title": "New candidate", "x": 760, "y": 160} in updated["nodes"]
        validation = client.post("/api/graphs/validate-spec", json=spec).json()
        assert validation["valid"] is False
        assert {error["code"] for error in validation["errors"]} == {"missing_prompt"}
    finally:
        app.dependency_overrides.clear()


def test_graph_run_detail_api_returns_progress(tmp_path):
    """Graph run detail endpoint should include spec-backed report sections."""

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

        graph_detail = client.get(f"/api/graphs/{graph_id}").json()
        assert [item["id"] for item in graph_detail["graph_runs"]] == [run["id"]]
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
