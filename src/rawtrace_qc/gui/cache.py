"""Cache extracted trace artifacts for the desktop workflow."""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from rawtrace_qc import __version__
from rawtrace_qc.discovery import DiscoveryCandidate
from rawtrace_qc.errors import ArtifactValidationError, ConfigurationError
from rawtrace_qc.extractors.protocol import Extractor, PrecisionMode
from rawtrace_qc.models import ExtractionResult
from rawtrace_qc.traces import load_trace

_CACHE_OUTPUT_NAME = "trace"
# Entries of earlier layouts may be incomplete, because they were written in
# place. Changing this value leaves them unused.
_CACHE_LAYOUT = "2"


@dataclass(frozen=True, slots=True)
class CacheResult:
    """Store extraction paths and whether they were loaded from cache."""

    extraction: ExtractionResult
    cache_hit: bool


class TraceCache:
    """Store validated trace artifacts under content-metadata cache keys."""

    def __init__(self, directory: Path) -> None:
        """Create a cache in a `<major>.<minor>` subfolder of `directory`.

        Each `rawtrace-qc` major.minor version keeps its own entries, so traces
        from another such version are not reused. Patch releases share a folder.

        Args:
            directory: Root directory of the trace cache.
        """
        major_minor = ".".join(__version__.split(".")[:2])
        self.directory = Path(directory).expanduser().resolve() / major_minor

    def extract(
        self,
        candidate: DiscoveryCandidate,
        extractor: Extractor,
        *,
        precision_mode: PrecisionMode = "low",
        select_ms1: bool = True,
        select_msn: bool = True,
    ) -> CacheResult:
        """Load a valid cached extraction or create one for `candidate`.

        The cache key includes the resolved source path, source metadata,
        vendor, extractor class, precision, and selected MS levels. Existing
        cache artifacts are loaded through `load_trace()` so unreadable or
        incompatible files are treated as cache misses.

        An extraction only appears in the cache once it has finished, so the
        artifacts in an entry are everything the acquisition provides. A file
        without MSn scans therefore hits the cache with its MS1 artifact alone.

        Args:
            candidate: Validated raw acquisition to extract.
            extractor: Vendor extractor used to create trace artifacts.
            precision_mode: Trace precision passed to the extractor.
            select_ms1: Whether the MS1 artifact is requested.
            select_msn: Whether the MSn artifact is requested.

        Returns:
            Cached or freshly extracted artifact paths and cache-hit state.

        Raises:
            ConfigurationError: If the source signature cannot be read.
        """
        source = candidate.path.expanduser().resolve()
        cache_directory = self.directory / _cache_key(
            source,
            candidate,
            extractor,
            precision_mode,
            select_ms1,
            select_msn,
        )
        cached = _read_cached_result(
            cache_directory,
            select_ms1=select_ms1,
            select_msn=select_msn,
        )
        if cached is not None:
            return CacheResult(cached, True)

        self.directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".staging-", dir=self.directory
        ) as staging:
            staged_directory = Path(staging) / cache_directory.name
            result = extractor.extract(
                source,
                output_directory=staged_directory,
                output_name=_CACHE_OUTPUT_NAME,
                precision_mode=precision_mode,
                select_ms1=select_ms1,
                select_msn=select_msn,
            )
            if result.ms1_path is None and result.msn_path is None:
                return CacheResult(result, False)
            shutil.rmtree(cache_directory, ignore_errors=True)
            staged_directory.rename(cache_directory)
        return CacheResult(
            ExtractionResult(
                ms1_path=_published_path(result.ms1_path, cache_directory),
                msn_path=_published_path(result.msn_path, cache_directory),
            ),
            False,
        )


def _published_path(staged_path: Path | None, cache_directory: Path) -> Path | None:
    return None if staged_path is None else cache_directory / staged_path.name


def _cache_key(
    source: Path,
    candidate: DiscoveryCandidate,
    extractor: Extractor,
    precision_mode: PrecisionMode,
    select_ms1: bool,
    select_msn: bool,
) -> str:
    digest = hashlib.sha256()
    _update_digest(digest, _CACHE_LAYOUT)
    _update_digest(digest, str(source).casefold())
    _update_digest(digest, candidate.vendor)
    _update_digest(digest, candidate.format)
    extractor_type = type(extractor)
    _update_digest(
        digest,
        f"{extractor_type.__module__}.{extractor_type.__qualname__}",
    )
    _update_digest(digest, precision_mode)
    _update_digest(digest, str(select_ms1))
    _update_digest(digest, str(select_msn))
    try:
        source_metadata = source.stat()
        _update_digest(digest, str(source_metadata.st_size))
        _update_digest(digest, str(source_metadata.st_mtime_ns))
        if source.is_dir():
            for member in sorted(
                source.iterdir(), key=lambda item: item.name.casefold()
            ):
                if not member.is_file():
                    continue
                metadata = member.stat()
                _update_digest(digest, member.name.casefold())
                _update_digest(digest, str(metadata.st_size))
                _update_digest(digest, str(metadata.st_mtime_ns))
    except OSError as error:
        raise ConfigurationError(
            f"Could not read source metadata for cache key {source}: {error}."
        ) from error
    return digest.hexdigest()[:16]


def _read_cached_result(
    cache_directory: Path,
    *,
    select_ms1: bool,
    select_msn: bool,
) -> ExtractionResult | None:
    expected = {
        "ms1": cache_directory / f"{_CACHE_OUTPUT_NAME}.ms1-trace.parquet",
        "msn": cache_directory / f"{_CACHE_OUTPUT_NAME}.msn-trace.parquet",
    }
    present = {
        level: path
        for level, path in expected.items()
        if ((level == "ms1" and select_ms1) or (level == "msn" and select_msn))
        and path.is_file()
    }
    if not present:
        return None
    try:
        for path in present.values():
            load_trace(path)
    except ArtifactValidationError:
        return None
    return ExtractionResult(
        ms1_path=present.get("ms1"),
        msn_path=present.get("msn"),
    )


def _update_digest(digest: hashlib._Hash, value: str) -> None:
    digest.update(value.encode("utf-8"))
    digest.update(b"\0")
