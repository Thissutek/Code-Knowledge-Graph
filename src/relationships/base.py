"""Base classes for language-specific relationship detectors."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class DetectedRelationship:
    """A relationship detected in source code with provenance metadata."""
    source_name: str
    target_name: str
    relationship_type: str   # CALLS, EXTENDS, IMPLEMENTS, INSTANTIATES, USES_CLASS
    confidence: float        # 0.0–1.0
    detection_method: str    # e.g. "AST_call", "AST_extends", "name_match"
    line_number: int
    file_path: str
    context: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseRelationshipDetector(ABC):
    """Abstract base for language-specific relationship detectors."""

    @abstractmethod
    def detect(self, source_code: str, file_path: str) -> List[DetectedRelationship]:
        """Detect relationships in source code.

        Args:
            source_code: Raw source text to analyse.
            file_path: Relative path to the file (used as context).

        Returns:
            List of detected relationships (may be empty).
        """

    @abstractmethod
    def supported_extensions(self) -> List[str]:
        """Return file extensions this detector handles (e.g. ['.py'])."""
