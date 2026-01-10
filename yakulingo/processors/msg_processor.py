# yakulingo/processors/msg_processor.py
"""
Outlook MSG file processor for email translation.

Uses extract-msg library to read .msg files (Outlook email format).
On Windows with Outlook installed, saves translated output as a .msg file while
preserving the "received mail" style (read mode) whenever possible.
Falls back to .txt output on other platforms.
"""

import gc
import logging
import re
import sys
import threading
from pathlib import Path
from typing import Any, Iterator, Optional

from yakulingo.models.types import TextBlock, FileInfo, FileType, SectionDetail
from yakulingo.processors.base import FileProcessor

logger = logging.getLogger(__name__)

# Pre-compiled regex for sentence splitting (AGENTS.md: Pre-compile regex patterns)
_SENTENCE_SPLIT_PATTERN = re.compile(r'(?<=[\u3002\uFF01\uFF1F!?\n])')
# Basic email validation for recipient normalization (ASCII-only)
_EMAIL_PATTERN = re.compile(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}')
_RECIPIENT_SPLIT_PATTERN = re.compile(r'[;\n]+')
_ANGLE_ADDR_FIND_PATTERN = re.compile(
    r'(?P<name>[^<]*)<(?P<address>[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})>'
)
_PAREN_ADDR_PATTERN = re.compile(
    r'^(?P<address>[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})\s*\((?P<name>[^)]*)\)$'
)
_QUOTE_NAME_PATTERN = re.compile(r'[",;<>]')

# Maximum characters per block for translation batching
MAX_CHARS_PER_BLOCK = 3000


def _lazy_import_extract_msg():
    """Lazy import extract_msg to avoid startup overhead."""
    try:
        import extract_msg
        return extract_msg
    except ImportError:
        raise ImportError(
            "extract-msg is required for MSG file support. "
            "Install with: uv pip install extract-msg"
        )


def _is_outlook_available() -> bool:
    """Check if Outlook COM is available (Windows with Outlook installed).

    Note:
        Release COM objects explicitly to avoid leaving Outlook running.    """
    if sys.platform != 'win32':
        return False
    outlook = None
    try:
        import win32com.client
        # Try to create Outlook application object
        outlook = win32com.client.Dispatch("Outlook.Application")
        return outlook is not None
    except Exception:
        return False
    finally:
        # Ensure COM objects are released (same pattern as create_msg_via_outlook).
        if outlook is not None:
            del outlook
        gc.collect()

class MsgProcessor(FileProcessor):
    """
    Processor for Outlook MSG files (.msg).

    Extracts subject and body text for translation.
    On Windows with Outlook, saves translated output as a .msg file while trying
    to preserve the "received mail" form (read mode, not a sendable draft).
    Falls back to .txt output on other platforms.

    Note:
        Cache access is thread-safe; uses a lock to avoid concurrent access.
    """
    def __init__(self):
        self._outlook_available: Optional[bool] = None
        self._cached_content: Optional[dict] = None
        self._cached_file_path: Optional[str] = None
        self._cache_lock = threading.Lock()

    def _get_cached_content(self, file_path: Path) -> dict:
        """Get MSG content with caching to avoid multiple file reads.

        Thread-safe: Uses lock to protect cache access.
        """
        file_path_str = str(file_path)
        with self._cache_lock:
            if self._cached_file_path != file_path_str or self._cached_content is None:
                extract_msg = _lazy_import_extract_msg()
                msg = extract_msg.Message(file_path_str)
                try:
                    subject = msg.subject or ""
                    body = msg.body or ""
                    body = body.replace('\r\n', '\n').replace('\r', '\n')
                    self._cached_content = {
                        'subject': subject,
                        'body': body,
                        'sender': msg.sender or "",
                        'to': msg.to or "",
                        'cc': msg.cc or "",
                        'date': str(msg.date) if msg.date else "",
                    }
                    self._cached_file_path = file_path_str
                finally:
                    msg.close()
            return self._cached_content

    def clear_cache(self):
        """Clear cached MSG content.

        Thread-safe: Uses lock to protect cache access.
        """
        with self._cache_lock:
            self._cached_content = None
            self._cached_file_path = None

    @property
    def outlook_available(self) -> bool:
        """Check if Outlook COM is available (cached)."""
        if self._outlook_available is None:
            self._outlook_available = _is_outlook_available()
        return self._outlook_available

    @property
    def file_type(self) -> FileType:
        return FileType.EMAIL

    @property
    def supported_extensions(self) -> list[str]:
        return ['.msg']

    def extract_sample_text_fast(self, file_path: Path, max_chars: int = 500) -> Optional[str]:
        """Fast text extraction for language detection.

        Uses cached content to avoid multiple file reads.

        Args:
            file_path: Path to MSG file.
            max_chars: Maximum characters to return.

        Returns:
            Sample text for language detection (subject + start of body).
        """
        try:
            content = self._get_cached_content(file_path)
            subject = content.get('subject', '')
            body = content.get('body', '')

            # Combine subject and start of body
            sample_parts = []
            if subject:
                sample_parts.append(subject)
            if body:
                # Take first few hundred chars from body
                sample_parts.append(body[:max_chars - len(subject) if subject else max_chars])

            sample = ' '.join(sample_parts)
            return sample[:max_chars] if sample else None

        except Exception as e:
            logger.warning("Fast MSG text extraction failed: %s", e)
            return None

    def get_file_info(self, file_path: Path) -> FileInfo:
        """Get file metadata for UI display."""
        content = self._get_cached_content(file_path)

        # Count body paragraphs for section details
        body = content.get('body', '')
        paragraphs = self._split_body_into_paragraphs(body)
        paragraph_count = len(paragraphs)

        # Create section details
        section_details = [
            SectionDetail(index=0, name="\u4ef6\u540d", selected=True),
        ]
        if paragraph_count > 0:
            for i in range(paragraph_count):
                section_details.append(SectionDetail(
                    index=i + 1,
                    name=f"\u672c\u6587\u6bb5\u843d{i + 1}",
                    selected=True,
                ))

        return FileInfo(
            path=file_path,
            file_type=FileType.EMAIL,
            size_bytes=file_path.stat().st_size,
            page_count=1,  # Single email = 1 page
            section_details=section_details,
        )

    def _split_body_into_paragraphs(self, body: str) -> list[dict]:
        """Split body into paragraphs while preserving structure.

        Returns a list of paragraph dicts with:
        - 'text': paragraph text (may be empty for blank paragraphs)
        - 'is_empty': True if paragraph is effectively empty
        - 'original_text': original text before stripping (preserves leading/trailing spaces)

        This preserves the structure including empty lines between sections.
        """
        if not body:
            return []

        # Split by double newlines (paragraph separator)
        raw_paragraphs = body.split('\n\n')
        paragraphs = []

        for p in raw_paragraphs:
            stripped = p.strip()
            paragraphs.append({
                'text': stripped,
                'is_empty': len(stripped) == 0,
                'original_text': p,
            })

        return paragraphs

    def extract_text_blocks(
        self, file_path: Path, output_language: str = "en"
    ) -> Iterator[TextBlock]:
        """
        Extract text blocks from MSG file.

        Extracts:
        - Subject line
        - Body paragraphs (split by double newlines, preserving structure)
        """
        content = self._get_cached_content(file_path)

        # Extract subject
        subject = content.get('subject', '')
        if subject and self.should_translate(subject):
            yield TextBlock(
                id="msg_subject",
                text=subject,
                location="\u4ef6\u540d",
                metadata={'field': 'subject', 'section_idx': 0}
            )

        # Extract body paragraphs
        body = content.get('body', '')
        paragraphs = self._split_body_into_paragraphs(body)

        # Track index for non-empty paragraphs
        non_empty_index = 0
        for para_index, para_info in enumerate(paragraphs):
            paragraph = para_info['text']
            is_empty = para_info['is_empty']

            # Skip empty paragraphs but record their position
            if is_empty:
                continue

            # Split long paragraphs into chunks
            if len(paragraph) > MAX_CHARS_PER_BLOCK:
                chunks = self._split_into_chunks(paragraph, MAX_CHARS_PER_BLOCK)
                for chunk_index, chunk in enumerate(chunks):
                    if self.should_translate(chunk):
                        yield TextBlock(
                            id=f"msg_body_{para_index}_chunk_{chunk_index}",
                            text=chunk,
                            location=f"\u672c\u6587\u6bb5\u843d{non_empty_index + 1} (\u5206\u5272{chunk_index + 1})",
                            metadata={
                                'field': 'body',
                                # Section index for partial translation UI:
                                # 0 = subject, 1.. = body paragraphs (including empty paragraphs).
                                'section_idx': para_index + 1,
                                'paragraph_index': para_index,  # Original index including empty paragraphs
                                'chunk_index': chunk_index,
                                'is_chunked': True,
                            }
                        )
            else:
                if self.should_translate(paragraph):
                    yield TextBlock(
                        id=f"msg_body_{para_index}",
                        text=paragraph,
                        location=f"\u672c\u6587\u6bb5\u843d{non_empty_index + 1}",
                        metadata={
                            'field': 'body',
                            # Section index for partial translation UI:
                            # 0 = subject, 1.. = body paragraphs (including empty paragraphs).
                            'section_idx': para_index + 1,
                            'paragraph_index': para_index,  # Original index including empty paragraphs
                            'is_chunked': False,
                        }
                    )

            non_empty_index += 1

    def _split_into_chunks(self, text: str, max_chars: int) -> list[str]:
        """Split long text into chunks, preferring sentence boundaries."""
        # Split by sentence-ending punctuation (keep delimiter with preceding text)
        # Uses pre-compiled regex at module level for performance
        sentences = _SENTENCE_SPLIT_PATTERN.split(text)
        sentences = [s for s in sentences if s]

        chunks = []
        current_chunk = ""

        for sentence in sentences:
            if len(current_chunk) + len(sentence) <= max_chars:
                current_chunk += sentence
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                # Handle very long sentences
                if len(sentence) > max_chars:
                    while len(sentence) > max_chars:
                        chunks.append(sentence[:max_chars].strip())
                        sentence = sentence[max_chars:]
                    current_chunk = sentence
                else:
                    current_chunk = sentence

        if current_chunk:
            chunks.append(current_chunk.strip())

        return chunks

    def _build_translated_content(
        self,
        input_path: Path,
        translations: dict[str, str],
    ) -> tuple[str, str]:
        """
        Build translated subject and body from translations dict.

        Preserves empty paragraphs to maintain email structure.

        Returns:
            Tuple of (translated_subject, translated_body)
        """
        content = self._get_cached_content(input_path)

        # Get original content
        original_subject = content.get('subject', '')
        original_body = content.get('body', '')

        # Build translated subject
        translated_subject = translations.get("msg_subject", original_subject)

        # Build translated body preserving empty paragraphs
        paragraphs = self._split_body_into_paragraphs(original_body)
        translated_paragraphs = []

        for para_index, para_info in enumerate(paragraphs):
            paragraph = para_info['text']
            is_empty = para_info['is_empty']

            # Preserve empty paragraphs as-is
            if is_empty:
                translated_paragraphs.append('')
                continue

            # Check if this paragraph was chunked
            chunked_ids = [
                block_id for block_id in translations.keys()
                if block_id.startswith(f"msg_body_{para_index}_chunk_")
            ]

            if chunked_ids:
                # Reconstruct from chunks
                chunk_texts = []
                chunks = self._split_into_chunks(paragraph, MAX_CHARS_PER_BLOCK)

                for chunk_index, chunk in enumerate(chunks):
                    chunk_id = f"msg_body_{para_index}_chunk_{chunk_index}"
                    chunk_texts.append(translations.get(chunk_id, chunk))

                translated_paragraphs.append(''.join(chunk_texts))
            else:
                # Single block paragraph
                block_id = f"msg_body_{para_index}"
                if block_id in translations:
                    translated_paragraphs.append(translations[block_id])
                else:
                    translated_paragraphs.append(paragraph)

        translated_body = '\n\n'.join(translated_paragraphs)
        return translated_subject, translated_body

    def _create_msg_via_outlook(
        self,
        input_path: Path,
        output_path: Path,
        subject: str,
        body: str,
    ) -> bool:
        """
        Create a translated .msg file using Outlook COM, preserving received-mail form.

        Strategy:
        1) Open the original .msg via Session.OpenSharedItem and modify it, then SaveAs.
           This preserves message flags so the output opens in read mode (no "Send").
        2) Fallback: create a new mail item and SaveAs (best-effort).
        """
        if not self.outlook_available:
            return False

        # Prefer copying from the original to preserve "received mail" flags.
        if self._create_msg_from_original_via_outlook(input_path, output_path, subject, body):
            return True

        # Fallback: create a new mail item (may open as a draft depending on Outlook).
        content = self._get_cached_content(input_path)
        to = content.get('to', '') if isinstance(content, dict) else ''
        cc = content.get('cc', '') if isinstance(content, dict) else ''
        return self._create_new_msg_via_outlook(output_path, subject, body, to=to, cc=cc)

    def _clear_unsent_flag_best_effort(self, mail: Any) -> bool:
        """Best-effort: clear MSGFLAG_UNSENT so saved .msg opens in read mode.

        Outlook draft-like .msg files are typically marked with MSGFLAG_UNSENT (0x8)
        in PR_MESSAGE_FLAGS (0x0E07). Clearing this flag helps avoid opening the
        output in the compose UI with a "Send" button.
        """
        try:
            accessor = getattr(mail, 'PropertyAccessor', None)
            if accessor is None:
                return False

            # PR_MESSAGE_FLAGS (PT_LONG): http://schemas.microsoft.com/mapi/proptag/0x0E070003
            prop_tag = "http://schemas.microsoft.com/mapi/proptag/0x0E070003"
            flags = accessor.GetProperty(prop_tag)
            if not isinstance(flags, int):
                return False

            MSGFLAG_UNSENT = 0x00000008
            if not (flags & MSGFLAG_UNSENT):
                return True

            new_flags = flags & ~MSGFLAG_UNSENT
            accessor.SetProperty(prop_tag, new_flags)

            # Verify (best-effort). If verification fails, treat as not cleared.
            verified = accessor.GetProperty(prop_tag)
            return isinstance(verified, int) and not (verified & MSGFLAG_UNSENT)
        except Exception:
            # Ignore: not all Outlook configurations allow writing message flags.
            return False

    def _create_msg_from_original_via_outlook(
        self,
        input_path: Path,
        output_path: Path,
        subject: str,
        body: str,
    ) -> bool:
        """
        Create a translated .msg by opening the original .msg and saving a modified copy.

        Args:
            input_path: Path to the original .msg file
            output_path: Path for the output .msg file
            subject: Email subject
            body: Email body text

        Returns:
            True if successful, False otherwise

        Note:
            Call Close() after SaveAs to avoid leaving Outlook in reply state.
        """
        mail = None
        outlook = None
        try:
            import win32com.client

            outlook = win32com.client.Dispatch("Outlook.Application")
            # OpenSharedItem preserves received-mail message flags (no Send button).
            mail = outlook.Session.OpenSharedItem(str(input_path))
            if mail is None:
                return False

            mail.Subject = subject
            mail.Body = body
            self._clear_unsent_flag_best_effort(mail)

            # Save as .msg file
            # 3 = olMSG format
            mail.SaveAs(str(output_path), 3)

            logger.info("MSG file created via Outlook (preserve received form): %s", output_path)
            return True

        except Exception as e:
            logger.warning("Failed to create MSG via Outlook (from original): %s", e)
            return False

        finally:
            # Ensure COM objects are released.
            if mail is not None:
                try:
                    # olDiscard = 1: close without saving changes.
                    mail.Close(1)
                except Exception:
                    pass
                # Explicitly delete COM objects to avoid leaks.
                del mail
            if outlook is not None:
                del outlook
            gc.collect()

    def _create_new_msg_via_outlook(
        self,
        output_path: Path,
        subject: str,
        body: str,
        to: str = "",
        cc: str = "",
    ) -> bool:
        """Fallback: create a new .msg file using Outlook COM.

        This may open as a draft depending on Outlook, so we try to clear
        MSGFLAG_UNSENT as a best-effort mitigation.
        """
        mail = None
        outlook = None
        try:
            import win32com.client

            outlook = win32com.client.Dispatch("Outlook.Application")
            mail = outlook.CreateItem(0)  # 0 = olMailItem

            mail.Subject = subject
            mail.Body = body
            if to:
                mail.To = self._normalize_recipients(to)
            if cc:
                mail.CC = self._normalize_recipients(cc)

            if not self._clear_unsent_flag_best_effort(mail):
                logger.info(
                    "Could not clear MSGFLAG_UNSENT; falling back to safe text output"
                )
                return False

            # Save as .msg file
            # 3 = olMSG format
            mail.SaveAs(str(output_path), 3)

            logger.info("MSG file created via Outlook (new item): %s", output_path)
            return True

        except Exception as e:
            logger.warning("Failed to create MSG via Outlook (new item): %s", e)
            return False

        finally:
            if mail is not None:
                try:
                    mail.Close(1)
                except Exception:
                    pass
                del mail
            if outlook is not None:
                del outlook
            gc.collect()

    def _normalize_recipients(self, raw: str) -> str:
        """Normalize recipients to avoid Outlook name-check failures.

        Outlook fails to resolve entries like "email <email>" when the
        display name contains an '@'. Also avoid breaking display names
        that include commas by not splitting on commas unless needed.
        """
        if not raw:
            return ""

        normalized = raw.replace('\r\n', '\n').replace('\r', '\n').strip()
        if not normalized:
            return ""

        tokens = self._split_recipient_tokens(normalized)

        cleaned: list[str] = []
        for token in tokens:
            cleaned.extend(self._parse_recipient_token(token))

        if not cleaned:
            return raw.strip()

        # Remove duplicates while preserving order.
        unique = list(dict.fromkeys(cleaned))
        return '; '.join(unique)

    def _split_recipient_tokens(self, raw: str) -> list[str]:
        """Split recipient string into tokens using Outlook-style separators."""
        if ';' in raw or '\n' in raw:
            return [t.strip() for t in _RECIPIENT_SPLIT_PATTERN.split(raw) if t.strip()]
        return [raw.strip()]

    def _parse_recipient_token(self, token: str) -> list[str]:
        """Parse a single recipient token into normalized entries."""
        token = token.strip()
        if not token:
            return []

        angle_matches = list(_ANGLE_ADDR_FIND_PATTERN.finditer(token))
        if angle_matches:
            recipients: list[str] = []
            for match in angle_matches:
                name = match.group('name').strip().strip('"').strip(' ,;')
                address = match.group('address').strip()
                recipients.append(self._format_recipient(name, address))
            return [r for r in recipients if r]

        paren_match = _PAREN_ADDR_PATTERN.match(token)
        if paren_match:
            name = paren_match.group('name').strip().strip('"')
            address = paren_match.group('address').strip()
            return [self._format_recipient(name, address)]

        addresses = _EMAIL_PATTERN.findall(token)
        if len(addresses) > 1:
            parts = [p.strip() for p in token.split(',') if p.strip()]
            recipients: list[str] = []
            for part in parts:
                recipients.extend(self._parse_recipient_token(part))
            return recipients

        if addresses:
            address = addresses[0]
            name = token.replace(address, '')
            name = name.replace('<', '').replace('>', '').strip().strip('"')
            name = name.strip(' ,;()')
            return [self._format_recipient(name, address)]

        return [token]

    def _format_recipient(self, name: str, address: str) -> str:
        """Format a recipient entry with safe quoting for Outlook."""
        name = name.strip().strip('"')
        address = address.strip()

        if not address:
            return name

        if name and ("@" in name or name.lower() == address.lower()):
            name = ""

        if name:
            if _QUOTE_NAME_PATTERN.search(name):
                name = f'"{name}"'
            return f'{name} <{address}>'

        return address

    def apply_translations(
        self,
        input_path: Path,
        output_path: Path,
        translations: dict[str, str],
        direction: str = "jp_to_en",
        settings=None,
        selected_sections: Optional[list[int]] = None,
        text_blocks=None,
    ) -> Optional[dict[str, Any]]:
        """
        Apply translations and save output file.

        On Windows with Outlook installed, saves a translated .msg file.
        Otherwise, falls back to .txt output.
        """
        translated_subject, translated_body = self._build_translated_content(
            input_path, translations
        )

        # Get original email metadata (to, cc, sender, date)
        content = self._get_cached_content(input_path)
        to = content.get('to', '')
        cc = content.get('cc', '')
        sender = content.get('sender', '')
        date = content.get('date', '')

        # Try to create .msg file via Outlook COM (Windows only)
        if self.outlook_available:
            # Ensure output has .msg extension
            msg_output_path = output_path.with_suffix('.msg')
            if self._create_msg_via_outlook(
                input_path, msg_output_path, translated_subject, translated_body
            ):
                return None
            logger.info("Failed to create MSG via Outlook, saving as .txt")
        else:
            logger.info("Outlook not available, saving as .txt")

        # Fallback: save as .txt
        txt_output_path = output_path.with_suffix('.txt')

        output_lines = []
        # Include email headers
        if sender:
            output_lines.append(f"From: {sender}")
        if to:
            output_lines.append(f"To: {to}")
        if cc:
            output_lines.append(f"CC: {cc}")
        if date:
            output_lines.append(f"Date: {date}")
        output_lines.append(f"Subject: {translated_subject}")
        output_lines.append("")
        output_lines.append(translated_body)

        txt_output_path.write_text('\n'.join(output_lines), encoding='utf-8')
        logger.info("MSG translation applied (as txt): %s -> %s", input_path, txt_output_path)

        return None

    def create_bilingual_document(
        self,
        original_path: Path,
        translated_path: Path,
        output_path: Path,
    ) -> None:
        """
        Create bilingual document with original and translated email interleaved.
        """
        # Read original MSG (use cached content)
        content = self._get_cached_content(original_path)
        original_subject = content.get('subject') or "(\u4ef6\u540d\u306a\u3057)"
        original_body = content.get('body', '')
        sender = content.get('sender') or "(\u9001\u4fe1\u8005\u4e0d\u660e)"
        to = content.get('to', '')
        cc = content.get('cc', '')
        date = content.get('date') or "(\u65e5\u4ed8\u4e0d\u660e)"

        extract_msg = _lazy_import_extract_msg()

        # Read translated content (could be .msg or .txt)
        if translated_path.suffix.lower() == '.msg':
            # Read from .msg file
            msg = extract_msg.Message(str(translated_path))
            try:
                translated_subject = msg.subject or ""
                translated_body = msg.body or ""
                translated_body = translated_body.replace('\r\n', '\n').replace('\r', '\n')
            finally:
                msg.close()
        else:
            # Read from .txt file (may include headers)
            translated_content = translated_path.read_text(encoding='utf-8')
            translated_lines = translated_content.split('\n')

            translated_subject = ""
            translated_body = ""
            body_start_idx = 0

            # Parse headers until we find Subject or an empty line
            for i, line in enumerate(translated_lines):
                if line.startswith("Subject: "):
                    translated_subject = line[9:]
                    body_start_idx = i + 2  # Skip Subject line and empty line
                    break
                elif line == "":
                    # End of headers without Subject
                    body_start_idx = i + 1
                    break

            if body_start_idx < len(translated_lines):
                translated_body = '\n'.join(translated_lines[body_start_idx:])

        # Build bilingual output
        separator = "\u2500" * 50
        output_parts = []

        # Header info
        output_parts.append(f"From: {sender}")
        if to:
            output_parts.append(f"To: {to}")
        if cc:
            output_parts.append(f"CC: {cc}")
        output_parts.append(f"Date: {date}")
        output_parts.append(separator)
        output_parts.append("")

        # Subject section
        output_parts.append("\u3010\u4ef6\u540d - \u539f\u6587\u3011")
        output_parts.append(original_subject)
        output_parts.append("")
        output_parts.append("\u3010\u4ef6\u540d - \u8a33\u6587\u3011")
        output_parts.append(translated_subject)
        output_parts.append("")
        output_parts.append(separator)
        output_parts.append("")

        # Body section
        output_parts.append("\u3010\u672c\u6587 - \u539f\u6587\u3011")
        output_parts.append(original_body)
        output_parts.append("")
        output_parts.append(separator)
        output_parts.append("")
        output_parts.append("\u3010\u672c\u6587 - \u8a33\u6587\u3011")
        output_parts.append(translated_body)

        # Bilingual output is always .txt
        txt_output_path = output_path.with_suffix('.txt')
        txt_output_path.write_text('\n'.join(output_parts), encoding='utf-8')
        logger.info("Bilingual MSG document created: %s", txt_output_path)

    def export_glossary_csv(
        self,
        translations: dict[str, str],
        original_texts: dict[str, str],
        output_path: Path,
    ) -> None:
        """Export source/translation pairs as CSV."""
        import csv

        with output_path.open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["\u539f\u6587", "\u8a33\u6587"])
            for block_id, translated in translations.items():
                if block_id in original_texts:
                    writer.writerow([original_texts[block_id], translated])

        logger.info("Glossary CSV exported: %s", output_path)
