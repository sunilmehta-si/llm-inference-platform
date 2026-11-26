"""CI checks the tested dependency versions against the OSV database, with a pinned osv-scanner."""

import re
from pathlib import Path

CI = (Path(__file__).resolve().parents[1] / ".github/workflows/ci.yaml").read_text()


def test_ci_scans_the_tested_requirements_for_known_vulnerabilities():
    assert re.search(
        r"osv-scanner\"? scan source --lockfile requirements\.txt:requirements-tested\.txt", CI
    )


def test_the_scanner_is_pinned_by_version_and_checksum():
    assert re.search(r"OSV_SCANNER_VERSION: v\d+\.\d+\.\d+", CI)
    assert re.search(r"OSV_SCANNER_SHA256: [0-9a-f]{64}", CI)
    assert "sha256sum -c -" in CI
