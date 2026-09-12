from unittest.mock import patch

import pytest

from autodrome import server


def test_server_runs_packaged_app_with_one_worker(tmp_path):
    (tmp_path / "index.html").write_text("Autodrome", encoding="utf-8")

    with patch.object(server, "FRONTEND_DIRECTORY", tmp_path), patch.object(
        server.conf, "validate"
    ) as validate, patch.object(server.uvicorn, "run") as run:
        server.main()

    validate.assert_called_once_with()
    run.assert_called_once_with(
        server.app,
        host=server.conf.api_host,
        port=server.conf.api_port,
        workers=1,
    )


def test_server_fails_clearly_when_packaged_frontend_is_missing(tmp_path):
    with patch.object(server, "FRONTEND_DIRECTORY", tmp_path), patch.object(
        server.conf, "validate"
    ), pytest.raises(SystemExit, match="Packaged frontend is missing"):
        server.main()
