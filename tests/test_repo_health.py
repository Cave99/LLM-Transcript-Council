from scripts.repo_health import static_findings


def test_repo_health_static_checks_pass():
    """Keep refactor risk diagnostics wired into the normal test suite."""

    assert static_findings() == []
