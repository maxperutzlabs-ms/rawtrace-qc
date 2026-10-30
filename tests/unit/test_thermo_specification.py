"""Sanity checks for the pinned Thermo helper release metadata."""

from __future__ import annotations

import json
import ssl
from dataclasses import replace
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import pytest
from rawtrace_qc import environment
from rawtrace_qc.errors import UnsupportedPlatformError
from rawtrace_qc.thermo import (
    THERMO_HELPER_RELEASE,
    ThermoHelperRelease,
    resolve_thermo_helper_specification,
    verify_thermo_helper_archive,
)
from tests.support.network import urlopen_or_skip
from tests.support.thermo_helper import get_or_download_thermo_helper_archive, resolve_specification_or_skip


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


class TestThermoHelperRelease:
    @pytest.mark.parametrize("runtime", sorted(THERMO_HELPER_RELEASE.assets))
    def test_every_pinned_asset_is_internally_consistent(self, runtime: str) -> None:
        release = THERMO_HELPER_RELEASE
        specification = release.specification(runtime)

        assert specification.runtime == runtime
        assert specification.version == release.version
        assert len(specification.sha256) == 64
        int(specification.sha256, 16)
        assert f"v{release.version}" in specification.asset_name
        assert runtime in specification.asset_name
        assert f"/v{release.version}/" in specification.download_url
        assert specification.download_url.endswith(specification.asset_name)
        assert specification.asset_name.endswith(f".{specification.archive_format}")
        assert specification.executable_name.endswith(".exe") == runtime.startswith("win")

    def test_specification_raises_unsupported_platform_error_listing_supported_runtimes(self) -> None:
        with pytest.raises(UnsupportedPlatformError, match=r"'linux-x64'.*\['win-x64'\]"):
            THERMO_HELPER_RELEASE.specification("linux-x64")


class TestResolveThermoHelperSpecification:
    def test_resolves_explicit_runtime(self) -> None:
        assert resolve_thermo_helper_specification("win-x64").runtime == "win-x64"

    def test_win_arm64_falls_back_to_win_x64(self) -> None:
        assert resolve_thermo_helper_specification("win-arm64") == THERMO_HELPER_RELEASE.specification("win-x64")

    def test_unpinned_runtime_without_fallback_raises_unsupported_platform_error(self) -> None:
        with pytest.raises(UnsupportedPlatformError, match="'osx-arm64'"):
            resolve_thermo_helper_specification("osx-arm64")

    def test_fallback_is_skipped_when_runtime_is_pinned(self) -> None:
        arm_asset = replace(
            THERMO_HELPER_RELEASE.assets["win-x64"], asset_name="ThermoScanHeaderExtractor-v0.2.0-win-arm64.zip"
        )
        release = ThermoHelperRelease(version="0.2.0", assets={**THERMO_HELPER_RELEASE.assets, "win-arm64": arm_asset})

        assert resolve_thermo_helper_specification("win-arm64", release=release).asset_name == arm_asset.asset_name

    def test_detects_host_runtime_when_none_is_given(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(environment, "get_platform", lambda: "win32")
        monkeypatch.setattr(environment, "get_machine", lambda: "ARM64")

        assert resolve_thermo_helper_specification().runtime == "win-x64"

    def test_unsupported_host_raises_unsupported_platform_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(environment, "get_platform", lambda: "linux")
        monkeypatch.setattr(environment, "get_machine", lambda: "x86_64")

        with pytest.raises(UnsupportedPlatformError, match="'linux-x64'"):
            resolve_thermo_helper_specification()


class TestPublishedThermoHelperRelease:
    @pytest.mark.network
    def test_published_archive_is_available(self) -> None:
        specification = resolve_specification_or_skip()

        with urlopen_or_skip(specification.download_url, timeout=10.0, method="HEAD") as response:
            assert response.status == 200

    @pytest.mark.network
    def test_published_archive_sha256_matches_pinned_checksum_for_every_runtime(self) -> None:
        release_url = (
            "https://api.github.com/repos/maxperutzlabs-ms/"
            f"thermo-scan-header-extractor/releases/tags/v{THERMO_HELPER_RELEASE.version}"
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

        published_digests = {asset["name"]: asset.get("digest") for asset in release["assets"]}
        for runtime in THERMO_HELPER_RELEASE.assets:
            specification = THERMO_HELPER_RELEASE.specification(runtime)
            assert specification.asset_name in published_digests, (
                f"Expected a GitHub release asset named {specification.asset_name!r} for runtime {runtime!r}. "
                "Check the pinned release metadata."
            )
            actual = published_digests[specification.asset_name]
            expected = f"sha256:{specification.sha256.casefold()}"
            assert actual == expected, (
                f"GitHub asset {specification.asset_name!r} has digest {actual!r}, "
                f"but the pinned digest is {expected!r}. Verify the release before updating the checksum."
            )

    @pytest.mark.network
    def test_cached_release_archive_matches_pinned_sha256(self) -> None:
        specification = resolve_specification_or_skip()
        archive_path = get_or_download_thermo_helper_archive(specification)

        assert verify_thermo_helper_archive(archive_path, specification=specification) == specification.sha256
