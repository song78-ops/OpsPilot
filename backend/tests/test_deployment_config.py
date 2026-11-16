"""Static checks for the local-only Docker deployment boundary."""

from pathlib import Path

import pytest
from starlette.requests import Request

from app.api.deps import (
    require_local_agent_access,
    require_local_approval_access,
)
from app.core.exceptions import ApplicationError

PROJECT_DIR = Path(__file__).resolve().parents[2]


def _request(client_host: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "client": (client_host, 12345),
        }
    )


@pytest.mark.parametrize(
    "dependency",
    [
        require_local_agent_access,
        require_local_approval_access,
    ],
)
def test_local_apis_still_reject_nonlocal_clients(dependency) -> None:
    with pytest.raises(ApplicationError) as caught:
        dependency(_request("203.0.113.10"))

    assert caught.value.status_code == 403
    assert caught.value.code in {
        "AGENT_LOCAL_ONLY",
        "APPROVAL_LOCAL_ONLY",
    }


def test_compose_keeps_backend_internal_and_frontend_loopback_only() -> None:
    compose = (PROJECT_DIR / "compose.yaml").read_text(encoding="utf-8")

    assert '127.0.0.1:8080:80' in compose
    assert "source: ./storage" in compose
    assert "target: /app/storage" in compose
    assert "172.30.240.10" in compose
    assert "LLM_PROVIDER: ${LLM_PROVIDER:-mock}" in compose
    assert "DEEPSEEK_API_KEY: ${DEEPSEEK_API_KEY:-}" in compose
    assert "0.0.0.0:8000:8000" not in compose
    assert "\n    ports:" in compose
    backend_block = compose.split("  backend:", 1)[1].split(
        "  frontend:",
        1,
    )[0]
    assert "\n    ports:" not in backend_block
    assert "\n    expose:" in backend_block


def test_backend_uses_one_worker_and_trusts_only_nginx_proxy() -> None:
    dockerfile = (PROJECT_DIR / "backend" / "Dockerfile").read_text(
        encoding="utf-8"
    )

    assert '"--workers", "1"' in dockerfile
    assert '"--forwarded-allow-ips", "172.30.240.10"' in dockerfile
    assert "COPY backend/.env" not in dockerfile


def test_nginx_proxies_api_and_overwrites_forwarding_headers() -> None:
    nginx = (PROJECT_DIR / "frontend" / "nginx.conf").read_text(
        encoding="utf-8"
    )

    assert "proxy_pass http://backend:8000;" in nginx
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in nginx
    assert "$proxy_add_x_forwarded_for" not in nginx
    assert "try_files $uri $uri/ /index.html;" in nginx
    assert "client_max_body_size 12m;" in nginx


def test_model_weights_and_secrets_are_excluded_from_build_context() -> None:
    dockerignore = (PROJECT_DIR / ".dockerignore").read_text(
        encoding="utf-8"
    )

    assert "\nstorage\n" in f"\n{dockerignore}"
    assert "**/.env" in dockerignore
    assert "backend/.venv" in dockerignore
    assert "frontend/node_modules" in dockerignore
