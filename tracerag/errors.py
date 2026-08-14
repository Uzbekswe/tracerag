from __future__ import annotations


class TraceRAGError(RuntimeError):
    """Base class for expected, user-actionable TraceRAG failures."""


class IndexCompatibilityError(TraceRAGError):
    """The active index cannot safely be used with the current configuration."""


class IncompatibleIndexError(IndexCompatibilityError):
    """The index manifest exists but does not match the current identity."""


class LegacyIndexError(IndexCompatibilityError):
    """An unversioned v1 index needs an explicit one-time rebuild."""


class ConcurrentIngestError(TraceRAGError):
    """Another process currently owns the persistent ingest write boundary."""


class PruneConfirmationRequired(TraceRAGError):
    """A prune plan exists but explicit confirmation was not supplied."""

    def __init__(self, missing: list[str]) -> None:
        self.missing = tuple(missing)
        details = "\n".join(f"- {source}" for source in self.missing)
        super().__init__(
            f"prune would remove these missing sources:\n{details}\n"
            "Use --prune --yes to confirm"
        )


class GenerationTransactionError(OSError, TraceRAGError):
    """Base class for failures while preparing or activating one generation."""


class GenerationStageError(GenerationTransactionError):
    """A staged generation could not be written completely."""


class GenerationValidationError(GenerationTransactionError):
    """A staged generation failed an integrity or queryability check."""


class GenerationActivationError(GenerationTransactionError):
    """The active generation manifest could not be replaced safely."""
