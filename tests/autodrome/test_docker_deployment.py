from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_runtime_image_uses_packaged_entrypoint_and_non_root_dependencies():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    runtime = dockerfile.split(" AS runtime", 1)[1]

    assert "COPY --from=wheel /src/dist/*.whl" in runtime
    assert "COPY --from=deno /deno /usr/local/bin/deno" in runtime
    assert "apt-get install -y --no-install-recommends ffmpeg" in runtime
    assert "USER 10001:10001" in runtime
    assert 'CMD ["autodrome"]' in runtime
    assert "HEALTHCHECK" in runtime
    assert "start_autodrome.sh" not in runtime
    assert "npm " not in runtime


def test_compose_keeps_all_durable_paths_on_one_music_mount():
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    assert set(compose["services"]) == {"autodrome"}
    service = compose["services"]["autodrome"]
    environment = service["environment"]

    assert environment["API_HOST"] == "0.0.0.0"
    assert environment["LIBRARY_PATH"] == "/music"
    assert environment["STAGING_PATH"].startswith("/music/")
    assert environment["QUEUE_STATE_PATH"].startswith("/music/")
    assert environment["COVER_STORAGE_PATH"].startswith("/music/")
    assert service["volumes"] == [
        "${MUSIC_PATH:?Set MUSIC_PATH to a writable host music directory}:/music"
    ]
    assert service["user"] == "${AUTODROME_UID:-10001}:${AUTODROME_GID:-10001}"
    assert "redis" not in compose["services"]


def test_container_build_context_excludes_secrets_and_local_state():
    ignored = set(
        (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    )

    assert {".git", ".env", ".venv", "covers", "library"} <= ignored


def test_release_workflow_publishes_only_stable_release_tags_to_ghcr():
    workflow = (ROOT / ".github/workflows/release-container.yml").read_text(
        encoding="utf-8"
    )

    assert "types: [published]" in workflow
    assert "branches:" not in workflow
    assert "packages: write" in workflow
    assert "platforms: linux/amd64" in workflow
    assert "type=semver,pattern={{version}}" in workflow
    assert "type=raw,value=latest" in workflow
    assert "scripts/smoke_container.sh" in workflow
