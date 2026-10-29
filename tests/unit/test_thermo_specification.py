"""Sanity checks for the pinned Thermo helper release metadata."""

from __future__ import annotations

import json
import ssl
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import pytest
from rawtrace_qc.thermo import THERMO_HELPER_SPECIFICATION, verify_thermo_helper_archive
from tests.support.network import urlopen_or_skip
from tests.support.thermo_helper import get_or_download_thermo_helper_archive


def _is_github_rate_limit(error: HTTPError) -> bool:
    """Determine whether a GitHub API error confirms a rate limit.

    Args:
        error: HTTP error returned by the GitHub API.

    Returns:
        True if the response indicates a GitHub API rate limit.
    """
    if error.code == 429:
        return True
    if error.code != 403:
        return False
    if error.headers and (
        error.headers.get("X-RateLimit-Remaining") == "0" or error.headers.get("Retry-After") is not None
    ):
        return True
    if error.fp is None:
        return False
    try:
        body = json.load(error)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(body, dict):
        return False
    message = body.get("message")
    return isinstance(message, str) and "rate limit" in message.casefold()


class TestThermoHelperSpecification:
    def test_pinned_release_metadata_is_internally_consistent(self) -> None:
        specification = THERMO_HELPER_SPECIFICATION

        assert len(specification.sha256) == 64
        int(specification.sha256, 16)
        assert f"v{specification.version}" in specification.asset_name
        assert f"/v{specification.version}/" in specification.download_url
        assert specification.download_url.endswith(specification.asset_name)

    @pytest.mark.network
    def test_published_archive_is_available(self) -> None:
        with urlopen_or_skip(THERMO_HELPER_SPECIFICATION.download_url, timeout=10.0, method="HEAD") as response:
            assert response.status == 200

    @pytest.mark.network
    def test_published_archive_sha256_matches_pinned_checksum(self) -> None:
        specification = THERMO_HELPER_SPECIFICATION
        release_url = (
            "https://api.github.com/repos/maxperutzlabs-ms/"
            f"thermo-scan-header-extractor/releases/tags/v{specification.version}"
        )
        try:
            with urlopen(release_url, timeout=30.0) as response:
                release = json.load(response)
        except HTTPError as error:
            if _is_github_rate_limit(error):
                pytest.skip(f"GitHub API rate limit reached; release checksum was not verified: {error}.")
            raise
        except URLError as error:
            pytest.skip(f"Cannot reach GitHub to verify the release checksum: {error}.")
        except ssl.SSLError as error:
            pytest.skip(f"TLS error contacting GitHub; release checksum was not verified: {error}.")
        except OSError as error:
            pytest.skip(f"Cannot reach GitHub to verify the release checksum: {error}.")

        assets = [asset for asset in release["assets"] if asset["name"] == specification.asset_name]
        assert len(assets) == 1, (
            f"Expected exactly one GitHub release asset named {specification.asset_name!r}; "
            f"found {len(assets)}. Check the pinned release metadata."
        )
        actual = assets[0].get("digest")
        expected = f"sha256:{specification.sha256.casefold()}"
        assert actual == expected, (
            f"GitHub asset {specification.asset_name!r} has digest {actual!r}, "
            f"but the pinned digest is {expected!r}. Verify the release before updating the checksum."
        )

    @pytest.mark.network
    def test_cached_release_archive_matches_pinned_sha256(self) -> None:
        archive_path = get_or_download_thermo_helper_archive()

        assert (
            verify_thermo_helper_archive(archive_path, specification=THERMO_HELPER_SPECIFICATION)
            == THERMO_HELPER_SPECIFICATION.sha256
        )
