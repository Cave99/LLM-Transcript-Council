"""FastAPI application entrypoint."""

from __future__ import annotations

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend import schemas
from backend.api import analysis, edges, graph_runs, graphs, nodes, projects
from council.db import init_db

load_dotenv()
init_db()

app = FastAPI(title="LLM-Transcript-Council API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router, prefix="/api")
app.include_router(graphs.router, prefix="/api")
app.include_router(nodes.router, prefix="/api")
app.include_router(edges.router, prefix="/api")
app.include_router(graph_runs.router, prefix="/api")
app.include_router(analysis.router, prefix="/api")


@app.get("/api/health", response_model=schemas.HealthResponse)
def health():
    """Report API health."""

    return schemas.HealthResponse()
