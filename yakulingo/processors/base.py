# yakulingo/processors/base.py
"""
Abstract base class for file processors.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Iterator, Optional

from yakulingo.models.types import TextBlock, FileInfo, FileType


class FileProcessor(ABC):
    """
    Abstract base class for file processors.
    Each file type (Excel, Word, etc.) implements this interface.
    """

    @property
    @abstractmethod
    def file_type(self) -> FileType:
        """Return the file type this processor handles"""
        pass

    @property
    @abstractmethod
    def supported_extensions(self) -> list[str]:
        """Return list of supported file extensions"""
        pass

    @abstractmethod
    def get_file_info(self, file_path: Path) -> FileInfo:
        """
        Get file metadata for UI display.

        Args:
            file_path: Path to the file

        Returns:
            FileInfo with file metadata
        """
        pass

    @abstractmethod
    def extract_text_blocks(
        self, file_path: Path, output_language: str = "en"
    ) -> Iterator[TextBlock]:
        """
        Extract translatable text blocks from file.

        Args:
            file_path: Path to the file
            output_language: "en" for JP→EN, "jp" for EN→JP translation.
                           Used to filter text based on translation direction.

        Yields:
            TextBlock for each translatable text unit
        """
        pass

    @abstractmethod
    def apply_translations(
        self,
        input_path: Path,
        output_path: Path,
        translations: dict[str, str],  # block_id -> translated_text
        direction: str = "jp_to_en",
    ) -> Optional[dict[str, Any]]:
        """
        Apply translations to file and save.

        Args:
            input_path: Path to original file
            output_path: Path for translated file
            translations: Mapping of block IDs to translated text
            direction: Translation direction for font selection

        Returns:
            Optional dict with processing statistics (processor-specific).
            Most processors return None. PdfProcessor returns:
            - 'total': Total blocks to translate
            - 'success': Successfully translated blocks
            - 'failed': List of failed block IDs
            - 'failed_fonts': List of fonts that failed to embed
        """
        pass

    def should_translate(self, text: str) -> bool:
        """
        Check if text should be translated.
        Override for custom logic.

        Args:
            text: Text to check

        Returns:
            True if text should be translated
        """
        # Skip empty, whitespace-only, numbers-only
        text = text.strip()
        if not text:
            return False
        if text.replace('.', '').replace(',', '').replace('-', '').replace(' ', '').isdigit():
            return False
        return True

    def supports_extension(self, extension: str) -> bool:
        """Check if this processor supports the given file extension"""
        return extension.lower() in self.supported_extensions
