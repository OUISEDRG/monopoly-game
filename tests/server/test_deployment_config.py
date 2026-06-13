from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def load_render_config() -> dict:
    config_path = ROOT / "render.yaml"
    assert config_path.exists(), "render.yaml must exist at the repository root"
    with config_path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_render_blueprint_defines_one_free_python_web_service():
    config = load_render_config()

    services = config.get("services")
    assert isinstance(services, list)
    assert len(services) == 1

    service = services[0]
    assert service["type"] == "web"
    assert service["name"] == "online-monopoly"
    assert service["runtime"] == "python"
    assert service["plan"] == "free"


def test_render_service_uses_required_build_start_and_health_settings():
    service = load_render_config()["services"][0]

    assert service["buildCommand"] == "pip install -r requirements.txt"
    assert service["startCommand"] == (
        "uvicorn server.app:app --host 0.0.0.0 --port $PORT "
        "--no-access-log --log-level warning"
    )
    assert "--workers" not in service["startCommand"]
    assert "--no-access-log" in service["startCommand"]
    assert "--log-level warning" in service["startCommand"]
    assert service["healthCheckPath"] == "/healthz"


def test_render_service_sets_required_environment_variables():
    service = load_render_config()["services"][0]
    env_vars = {
        item["key"]: item.get("value")
        for item in service.get("envVars", [])
        if "key" in item
    }

    assert env_vars["PYTHON_VERSION"]
    assert env_vars["APP_ENV"] == "production"
    assert "ALLOWED_ORIGINS" in env_vars


def test_render_deployment_document_covers_operational_notes():
    doc_path = ROOT / "docs/superpowers/workflow/render-free-deployment.md"
    assert doc_path.exists()
    text = doc_path.read_text(encoding="utf-8")

    required_phrases = [
        "GitHub",
        "Render Blueprint",
        "ALLOWED_ORIGINS",
        "首次冷启动",
        "免费休眠",
        "重启后房间会丢失",
        "/healthz",
        "WebSocket",
    ]
    for phrase in required_phrases:
        assert phrase in text
