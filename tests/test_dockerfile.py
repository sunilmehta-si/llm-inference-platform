"""The image builds from a base pinned by digest and runs as a non-root user."""

import re
from pathlib import Path

DOCKERFILE = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text()


def test_every_base_image_is_pinned_by_digest():
    froms = re.findall(r"^FROM\s+(\S+)", DOCKERFILE, re.M)
    assert froms
    for image in froms:
        assert re.search(r"@sha256:[0-9a-f]{64}$", image), f"{image} is not pinned by digest"


def test_the_container_runs_as_a_non_root_user():
    users = re.findall(r"^USER\s+(\S+)", DOCKERFILE, re.M)
    assert users and users[-1] not in ("root", "0")


def test_dependencies_are_installed_from_the_tested_versions():
    assert re.search(r"pip install .*-c requirements-tested\.txt", DOCKERFILE)
