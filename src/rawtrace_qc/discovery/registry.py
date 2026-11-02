"""Registry for vendor-specific filesystem validators."""

from __future__ import annotations

from collections.abc import Callable, Iterator

from rawtrace_qc.discovery.models import TraversalTree, ValidationResult
from rawtrace_qc.errors import ConfigurationError

VendorValidator = Callable[[TraversalTree, int, float, float], ValidationResult]


Registration = tuple[str, str, VendorValidator]


class DiscoveryRegistry:
    """Register validators that identify complete vendor acquisitions."""

    def __init__(self) -> None:
        """Create an empty validator registry."""
        self._registrations: list[Registration] = []

    def register(self, vendor: str, format: str, validator: VendorValidator) -> None:
        """Register one validator for a vendor and input format.

        Args:
            vendor: Non-empty vendor identifier such as `bruker`.
            format: Non-empty format identifier such as `d`.
            validator: Callable returning valid and skipped paths from a
                traversal tree.

        Raises:
            ConfigurationError: If an identifier is empty or already registered.
        """
        if not isinstance(vendor, str) or not isinstance(format, str):
            raise ConfigurationError("Vendor and format identifiers must be strings.")
        if not vendor.strip() or not format.strip():
            raise ConfigurationError(
                "Vendor and format identifiers must be non-empty strings."
            )
        registration = (vendor, format, validator)
        if any(item[:2] == registration[:2] for item in self._registrations):
            raise ConfigurationError(
                f"A detector is already registered for vendor {vendor!r} and "
                f"format {format!r}."
            )
        self._registrations.append(registration)

    def __iter__(self) -> Iterator[Registration]:
        """Iterate over registered validators in registration order."""
        return iter(self._registrations)
