import json
from pathlib import Path

from h42mesh.controller.openapi import DEFAULT_OUTPUT, main, render_openapi


def test_openapi_contract() -> None:
    schema = json.loads(render_openapi())
    assert schema["info"]["title"] == "h42-mesh controller"
    assert all(path.startswith("/api/v1/") for path in schema["paths"])
    health = schema["paths"]["/api/v1/health"]["get"]
    assert health["operationId"] == "get_health"
    assert set(health["responses"]) >= {"200", "503"}
    assert set(schema["components"]["schemas"]["HealthResponse"]["properties"]) == {
        "status",
        "version",
    }


def test_export_and_check(tmp_path: Path) -> None:
    output = tmp_path / "openapi" / "controller.json"
    assert main(["--check", "--output", str(output)]) == 1  # missing
    assert main(["--output", str(output)]) == 0
    assert output.read_text(encoding="utf-8") == render_openapi()
    assert main(["--check", "--output", str(output)]) == 0


def test_committed_openapi_is_up_to_date() -> None:
    """Fails if the API changed without exporting the description again."""
    assert DEFAULT_OUTPUT.exists(), "run: uv run python -m h42mesh.controller.openapi"
    assert DEFAULT_OUTPUT.read_text(encoding="utf-8") == render_openapi(), (
        "openapi/controller.json is out of date: run uv run python -m h42mesh.controller.openapi"
    )
