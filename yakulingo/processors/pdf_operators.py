# yakulingo/processors/pdf_operators.py
"""
PDF Operator Generation for YakuLingo.

Based on PDFMathTranslate low-level PDF operators.

Features:
- Text operator generation with proper encoding
- Content stream parsing and filtering
- Graphics preservation during text replacement
"""

import logging
from typing import Optional

from .pdf_font_manager import FontRegistry, FontType

# Module logger
logger = logging.getLogger(__name__)


# =============================================================================
# PDF Operator Generator (PDFMathTranslate compliant)
# =============================================================================
class PdfOperatorGenerator:
    """
    Low-level PDF operator generator.

    PDFMathTranslate converter.py:384-385 compliant.
    """

    def __init__(self, font_registry: FontRegistry):
        self.font_registry = font_registry

    def gen_op_txt(
        self,
        font_id: str,
        size: float,
        x: float,
        y: float,
        rtxt: str,
    ) -> str:
        """
        Generate text drawing operator.

        PDFMathTranslate converter.py:384-385 compliant.

        Args:
            font_id: Font ID (F1, F2, ...)
            size: Font size (pt)
            x: X coordinate (PDF coordinate system)
            y: Y coordinate (PDF coordinate system)
            rtxt: Hex-encoded text

        Returns:
            PDF operator string
        """
        return f"/{font_id} {size:f} Tf 1 0 0 1 {x:f} {y:f} Tm [<{rtxt}>] TJ "

    def raw_string(self, font_id: str, text: str) -> str:
        """
        Encode text for PDF text operators.

        PDFMathTranslate converter.py compliant:
        - EMBEDDED fonts: use has_glyph() for glyph indices (4-digit hex)
        - CID fonts: use ord(c) for Unicode code points (4-digit hex)
        - SIMPLE fonts: use ord(c) for character codes (2-digit hex)

        Args:
            font_id: Font ID
            text: Text to encode

        Returns:
            Hex-encoded string
        """
        font_type = self.font_registry.get_font_type(font_id)

        if font_type == FontType.EMBEDDED:
            # Newly embedded font: use glyph indices from has_glyph()
            return self._encode_with_glyph_ids(font_id, text)
        elif font_type == FontType.CID:
            # Existing CID font: use Unicode code points (4-digit hex)
            #
            # IMPORTANT LIMITATION (PDFMathTranslate compliant):
            # This encoding assumes the existing CID font has Identity-H encoding
            # or a ToUnicode CMap that maps Unicode directly.
            # For fonts with custom CID mappings, translated text should use
            # newly embedded fonts (EMBEDDED type) instead.
            #
            # In practice, YakuLingo always embeds new fonts for translated text,
            # so this code path is primarily used for preserving original text
            # that is not translated.
            #
            # CMap validation: Check if the font might have a custom CMap
            # that could cause encoding issues. Log warning if detected.
            self._validate_cid_font_encoding(font_id, text)

            hex_result = "".join([f'{ord(c):04X}' for c in text])
            if logger.isEnabledFor(logging.DEBUG):
                preview = text[:50] + ('...' if len(text) > 50 else '')
                logger.debug(
                    "Encoding text (CID): font=%s, chars=%d, text='%s' "
                    "(Note: CID encoding assumes Identity-H or Unicode-compatible CMap)",
                    font_id, len(text), preview
                )
            return hex_result
        else:
            # Existing simple font: use character codes (2-digit hex)
            hex_result = "".join([f'{ord(c):02X}' for c in text])
            if logger.isEnabledFor(logging.DEBUG):
                preview = text[:50] + ('...' if len(text) > 50 else '')
                logger.debug(
                    "Encoding text (SIMPLE): font=%s, chars=%d, text='%s'",
                    font_id, len(text), preview
                )
            return hex_result

    def _encode_with_glyph_ids(self, font_id: str, text: str) -> str:
        """
        Encode text using glyph indices for embedded fonts.

        PyMuPDF's insert_font embeds fonts with Identity-H encoding but
        WITHOUT a CIDToGIDMap. This means CID values in the content stream
        are interpreted directly as glyph indices.

        Args:
            font_id: Font ID
            text: Text to encode

        Returns:
            Hex-encoded string of glyph indices (4-digit hex per character)
        """
        hex_parts = []
        missing_glyphs = []

        for char in text:
            glyph_idx = self.font_registry.get_glyph_id(font_id, char)
            if glyph_idx == 0 and char not in ('\0', '\x00'):
                missing_glyphs.append(char)
            hex_parts.append(f'{glyph_idx:04X}')

        hex_result = ''.join(hex_parts)

        # Log encoding details for debugging (only for first 50 chars to avoid spam)
        if logger.isEnabledFor(logging.DEBUG):
            preview = text[:50] + ('...' if len(text) > 50 else '')
            hex_preview = hex_result[:100] + ('...' if len(hex_result) > 100 else '')
            logger.debug(
                "Encoding text (EMBEDDED): font=%s, chars=%d, glyphs=%d, "
                "text='%s', hex='%s'",
                font_id, len(text), len(hex_parts),
                preview, hex_preview
            )
            if missing_glyphs:
                logger.debug(
                    "Missing glyphs in font %s: %s",
                    font_id, missing_glyphs[:10]
                )

        return hex_result

    def _validate_cid_font_encoding(self, font_id: str, text: str) -> None:
        """
        Validate CID font encoding and warn about potential issues.

        Checks if the CID font might have a non-Identity-H CMap that could
        cause text encoding issues. This is a best-effort check since we
        cannot always determine the exact CMap used.

        Args:
            font_id: Font ID to validate
            text: Text being encoded (for logging)
        """
        # Check if we've already warned about this font
        if not hasattr(self, '_warned_cid_fonts'):
            self._warned_cid_fonts = set()

        if font_id in self._warned_cid_fonts:
            return

        # Try to get pdfminer font object for CMap analysis
        pdfminer_font = self.font_registry._pdfminer_fonts.get(font_id)
        if not pdfminer_font:
            return

        # Check CMap type if available
        cmap_name = None
        if hasattr(pdfminer_font, 'cmap'):
            cmap = pdfminer_font.cmap
            if hasattr(cmap, 'cmap_name'):
                cmap_name = cmap.cmap_name
            elif hasattr(cmap, 'cmapname'):
                cmap_name = cmap.cmapname

        # List of known Identity-H compatible CMaps
        # These map Unicode directly to CID values
        identity_compatible_cmaps = {
            'Identity-H', 'Identity-V',
            'UniJIS-UTF16-H', 'UniJIS-UTF16-V',
            'UniCNS-UTF16-H', 'UniCNS-UTF16-V',
            'UniGB-UTF16-H', 'UniGB-UTF16-V',
            'UniKS-UTF16-H', 'UniKS-UTF16-V',
        }

        if cmap_name and cmap_name not in identity_compatible_cmaps:
            # Non-Identity CMap detected - warn user
            self._warned_cid_fonts.add(font_id)
            logger.warning(
                "CID font '%s' uses CMap '%s' which may not be Identity-H compatible. "
                "Text encoding might be incorrect. If text appears garbled, "
                "try converting the PDF with embedded fonts.",
                font_id, cmap_name
            )

    def calculate_text_width(self, font_id: str, text: str, font_size: float) -> float:
        """
        Calculate total text width using font metrics.

        Args:
            font_id: Font ID
            text: Text to measure
            font_size: Font size in points

        Returns:
            Total width in points
        """
        total_width = 0.0
        for char in text:
            total_width += self.font_registry.get_char_width(font_id, char, font_size)
        return total_width


# =============================================================================
# Content Stream Parser (PDFMathTranslate compliant)
# =============================================================================
class ContentStreamParser:
    """
    Parse PDF content stream and filter text operators.

    Based on PDFMathTranslate pdfinterp.py approach:
    - Remove text drawing operators (Tj, TJ, ', ") inside BT...ET blocks
    - Preserve graphics operators (paths, colors, images, transformations)

    This allows replacing text without affecting underlying graphics/images.
    """

    # Text operators that draw text (to be removed)
    TEXT_DRAWING_OPS = frozenset({'Tj', 'TJ', "'", '"'})

    # Text state operators (to be removed along with their operands)
    TEXT_STATE_OPS = frozenset({
        'Tc', 'Tw', 'Tz', 'TL', 'Tf', 'Tr', 'Ts',  # Text state
        'Td', 'TD', 'Tm', 'T*',  # Text positioning
    })

    # All text-related operators
    ALL_TEXT_OPS = TEXT_DRAWING_OPS | TEXT_STATE_OPS | frozenset({'BT', 'ET'})

    # Operators that take specific number of operands
    OPERAND_COUNTS = {
        # Graphics state
        'w': 1, 'J': 1, 'j': 1, 'M': 1, 'd': 2, 'ri': 1, 'i': 1, 'gs': 1,
        # Transformation
        'cm': 6,
        # Path construction
        'm': 2, 'l': 2, 'c': 6, 'v': 4, 'y': 4, 'h': 0, 're': 4,
        # Path painting
        'S': 0, 's': 0, 'f': 0, 'F': 0, 'f*': 0, 'B': 0, 'B*': 0,
        'b': 0, 'b*': 0, 'n': 0,
        # Clipping
        'W': 0, 'W*': 0,
        # Text (for reference, will be filtered)
        'BT': 0, 'ET': 0,
        'Tc': 1, 'Tw': 1, 'Tz': 1, 'TL': 1, 'Tf': 2, 'Tr': 1, 'Ts': 1,
        'Td': 2, 'TD': 2, 'Tm': 6, 'T*': 0,
        'Tj': 1, 'TJ': 1, "'": 1, '"': 3,
        # XObject
        'Do': 1,
        # Color
        'CS': 1, 'cs': 1, 'SC': -1, 'SCN': -1, 'sc': -1, 'scn': -1,
        'G': 1, 'g': 1, 'RG': 3, 'rg': 3, 'K': 4, 'k': 4,
        # Shading
        'sh': 1,
        # Inline image
        'BI': 0, 'ID': 0, 'EI': 0,
        # Marked content
        'MP': 1, 'DP': 2, 'BMC': 1, 'BDC': 2, 'EMC': 0,
        # Compatibility
        'BX': 0, 'EX': 0,
        # State
        'q': 0, 'Q': 0,
    }

    def __init__(self):
        self._in_text_block = False

    def parse_and_filter(self, stream: bytes) -> bytes:
        """
        Parse content stream and remove text operators.

        Args:
            stream: Raw PDF content stream bytes

        Returns:
            Filtered content stream with text operators removed
        """
        try:
            # Decode stream (PDF uses latin-1 for content streams)
            content = stream.decode('latin-1')
        except (UnicodeDecodeError, AttributeError):
            # If decoding fails, return original
            logger.warning("Failed to decode content stream, returning original")
            return stream

        tokens = self._tokenize(content)
        filtered = self._filter_tokens(tokens)
        result = self._reconstruct(filtered)

        return result.encode('latin-1')

    def _tokenize(self, content: str) -> list[tuple[str, str]]:
        """
        Tokenize PDF content stream.

        Returns list of (type, value) tuples where type is one of:
        - 'operator': PDF operator keyword
        - 'number': numeric value
        - 'name': /Name
        - 'string': (string) or <hexstring>
        - 'array': [...] array
        - 'dict': <<...>> dictionary
        - 'whitespace': spaces/newlines
        """
        tokens = []
        i = 0
        n = len(content)

        while i < n:
            c = content[i]

            # Whitespace
            if c in ' \t\r\n':
                j = i
                while j < n and content[j] in ' \t\r\n':
                    j += 1
                tokens.append(('whitespace', content[i:j]))
                i = j
                continue

            # Comment
            if c == '%':
                j = i
                while j < n and content[j] not in '\r\n':
                    j += 1
                # Skip comment (don't include in output)
                i = j
                continue

            # Name
            if c == '/':
                j = i + 1
                while j < n and content[j] not in ' \t\r\n/<>[]()%':
                    j += 1
                tokens.append(('name', content[i:j]))
                i = j
                continue

            # Literal string
            if c == '(':
                j = i + 1
                depth = 1
                while j < n and depth > 0:
                    if content[j] == '\\' and j + 1 < n:
                        j += 2  # Skip escaped char
                        continue
                    if content[j] == '(':
                        depth += 1
                    elif content[j] == ')':
                        depth -= 1
                    j += 1
                tokens.append(('string', content[i:j]))
                i = j
                continue

            # Hex string
            if c == '<' and (i + 1 >= n or content[i + 1] != '<'):
                j = i + 1
                while j < n and content[j] != '>':
                    j += 1
                j += 1  # Include closing >
                tokens.append(('string', content[i:j]))
                i = j
                continue

            # Dictionary
            if c == '<' and i + 1 < n and content[i + 1] == '<':
                j = i + 2
                depth = 1
                while j < n - 1 and depth > 0:
                    if content[j:j+2] == '<<':
                        depth += 1
                        j += 2
                    elif content[j:j+2] == '>>':
                        depth -= 1
                        j += 2
                    else:
                        j += 1
                tokens.append(('dict', content[i:j]))
                i = j
                continue

            # Array
            if c == '[':
                j = i + 1
                depth = 1
                while j < n and depth > 0:
                    if content[j] == '[':
                        depth += 1
                    elif content[j] == ']':
                        depth -= 1
                    elif content[j] == '(':
                        # Skip string content
                        k = j + 1
                        str_depth = 1
                        while k < n and str_depth > 0:
                            if content[k] == '\\' and k + 1 < n:
                                k += 2
                                continue
                            if content[k] == '(':
                                str_depth += 1
                            elif content[k] == ')':
                                str_depth -= 1
                            k += 1
                        j = k
                        continue
                    j += 1
                tokens.append(('array', content[i:j]))
                i = j
                continue

            # Number (including negative and decimal)
            if c.isdigit() or c == '-' or c == '+' or c == '.':
                j = i
                if content[j] in '-+':
                    j += 1
                while j < n and (content[j].isdigit() or content[j] == '.'):
                    j += 1
                if j > i and (j == i + 1 and content[i] in '-+'):
                    # Just a sign, treat as operator
                    pass
                else:
                    tokens.append(('number', content[i:j]))
                    i = j
                    continue

            # Operator (keyword)
            if c.isalpha() or c in "'\"*":
                j = i
                while j < n and (content[j].isalnum() or content[j] in "'\"*"):
                    j += 1
                tokens.append(('operator', content[i:j]))
                i = j
                continue

            # Unknown - include as-is
            tokens.append(('unknown', c))
            i += 1

        return tokens

    def _filter_tokens(self, tokens: list[tuple[str, str]]) -> list[tuple[str, str]]:
        """
        Filter out text operators and their operands.

        Removes BT...ET blocks entirely, preserving only graphics operations.
        """
        result = []
        i = 0
        n = len(tokens)
        in_text_block = False
        operand_stack = []

        while i < n:
            token_type, token_value = tokens[i]

            if token_type == 'whitespace':
                if not in_text_block:
                    result.append((token_type, token_value))
                i += 1
                continue

            if token_type == 'operator':
                if token_value == 'BT':
                    # Enter text block - start filtering
                    in_text_block = True
                    operand_stack = []
                    i += 1
                    continue

                if token_value == 'ET':
                    # Exit text block
                    in_text_block = False
                    operand_stack = []
                    i += 1
                    continue

                if in_text_block:
                    # Inside text block - skip all operators
                    operand_stack = []
                    i += 1
                    continue

                # Outside text block - keep operator and its operands
                result.extend(operand_stack)
                result.append((token_type, token_value))
                operand_stack = []
                i += 1
                continue

            # Operand (number, name, string, array, dict)
            if in_text_block:
                # Skip operands inside text block
                i += 1
                continue

            # Accumulate operands
            operand_stack.append((token_type, token_value))
            i += 1

        # Add any remaining operands (shouldn't happen in valid PDF)
        result.extend(operand_stack)

        return result

    def _reconstruct(self, tokens: list[tuple[str, str]]) -> str:
        """Reconstruct content stream from filtered tokens."""
        parts = []
        prev_type = None

        for token_type, token_value in tokens:
            # Add space between tokens if needed
            if prev_type and prev_type != 'whitespace' and token_type != 'whitespace':
                parts.append(' ')
            parts.append(token_value)
            prev_type = token_type

        return ''.join(parts)

    def filter_page_contents(self, doc, page) -> bytes:
        """
        Get and filter all content streams for a page.

        Handles both single content stream and content array.

        Args:
            doc: PyMuPDF document
            page: PyMuPDF page

        Returns:
            Combined filtered content stream
        """
        filtered_parts = []

        # Get content stream xrefs
        contents = page.get_contents()
        if not contents:
            return b""

        for xref in contents:
            try:
                stream = doc.xref_stream(xref)
                if stream:
                    filtered = self.parse_and_filter(stream)
                    filtered_parts.append(filtered)
            except (RuntimeError, ValueError, KeyError, OSError) as e:
                # RuntimeError: PyMuPDF internal errors
                # ValueError: invalid stream data
                # KeyError: missing xref entry
                # OSError: file access issues
                logger.warning("Failed to filter content stream xref %d: %s", xref, e)
                # On error, try to get original stream
                try:
                    stream = doc.xref_stream(xref)
                    if stream:
                        filtered_parts.append(stream)
                except (RuntimeError, ValueError, KeyError, OSError):
                    pass

        return b" ".join(filtered_parts)


# =============================================================================
# Content Stream Replacer (PDFMathTranslate compliant)
# =============================================================================
class ContentStreamReplacer:
    """
    PDF content stream replacer.

    PDFMathTranslate high_level.py compliant.
    Replaces text in content stream while preserving graphics/images.

    Key improvement over previous implementation:
    - Previous: Added white rectangles to cover text (hid graphics too)
    - New: Parses content stream, removes text operators, keeps graphics
    """

    def __init__(self, doc, font_registry: FontRegistry, preserve_graphics: bool = True):
        self.doc = doc
        self.font_registry = font_registry
        self.operators: list[str] = []
        self._in_text_block = False
        self._used_fonts: set[str] = set()
        self._preserve_graphics = preserve_graphics
        self._filtered_base_stream: Optional[bytes] = None
        self._parser = ContentStreamParser() if preserve_graphics else None

    def set_base_stream(self, page) -> 'ContentStreamReplacer':
        """
        Capture and filter the original content stream for this page.

        This removes text operators while preserving graphics/images.
        Must be called before adding new text operators.

        Args:
            page: PyMuPDF page object

        Returns:
            self for chaining
        """
        if not self._preserve_graphics or not self._parser:
            return self

        self._filtered_base_stream = self._parser.filter_page_contents(self.doc, page)
        return self

    def begin_text(self) -> 'ContentStreamReplacer':
        """Begin text block."""
        if not self._in_text_block:
            # Set text fill color to black before starting text block
            self.operators.append("0 0 0 rg ")
            self.operators.append("BT ")
            self._in_text_block = True
        return self

    def end_text(self) -> 'ContentStreamReplacer':
        """End text block."""
        if self._in_text_block:
            self.operators.append("ET ")
            self._in_text_block = False
        return self

    def add_text_operator(self, op: str, font_id: str = None) -> 'ContentStreamReplacer':
        """
        Add text operator (auto BT/ET management).

        Args:
            op: Operator string
            font_id: Font ID for resource registration
        """
        if not self._in_text_block:
            self.begin_text()
        self.operators.append(op)

        if font_id:
            self._used_fonts.add(font_id)

        return self

    # NOTE: add_redaction() was removed.
    # Previous implementation drew white rectangles to cover text,
    # but this also hid graphics/images underneath.
    # New approach: set_base_stream() filters out text operators from
    # original content stream, preserving graphics/images intact.

    def build(self) -> bytes:
        """Build content stream as bytes (new text operators only)."""
        if self._in_text_block:
            self.end_text()

        stream = "".join(self.operators)
        return stream.encode("latin-1")

    def build_combined(self) -> bytes:
        """
        Build combined content stream: filtered base + new text.

        PDFMathTranslate approach:
        - Base stream has text removed, graphics preserved
        - New text operators are appended
        - Result: graphics intact, text replaced
        """
        new_text = self.build()

        logger.debug(
            "build_combined: new_text_len=%d, filtered_base_len=%d, new_text_preview='%s'",
            len(new_text), len(self._filtered_base_stream) if self._filtered_base_stream else 0,
            new_text[:200].decode('latin-1', errors='replace') if new_text else ''
        )

        if self._filtered_base_stream:
            # Combine: filtered base (graphics) + new text
            # Wrap in q/Q to isolate graphics state
            combined = b"q " + self._filtered_base_stream + b" Q " + new_text
            return combined
        else:
            return new_text

    def apply_to_page(self, page) -> None:
        """
        Apply built stream to page.

        PDFMathTranslate high_level.py compliant.
        Replaces page content stream (not append) to remove original text.
        Updates font resources dictionary.
        """
        # Build combined stream (filtered base + new text)
        stream_bytes = self.build_combined()

        logger.debug(
            "apply_to_page: page=%d, stream_bytes_len=%d, operators=%d, used_fonts=%s, "
            "filtered_base_len=%d",
            page.number, len(stream_bytes) if stream_bytes else 0,
            len(self.operators), list(self._used_fonts),
            len(self._filtered_base_stream) if self._filtered_base_stream else 0
        )

        if not stream_bytes.strip():
            logger.warning("apply_to_page: stream_bytes is empty, skipping page %d", page.number)
            return

        # Create new stream object
        new_xref = self.doc.get_new_xref()
        # Initialize xref as PDF dict before updating stream
        # (get_new_xref only allocates xref number, doesn't create dict object)
        self.doc.update_object(new_xref, "<< >>")
        self.doc.update_stream(new_xref, stream_bytes)

        # REPLACE page Contents (not append)
        # This ensures original text is removed
        page_xref = page.xref
        self.doc.xref_set_key(page_xref, "Contents", f"{new_xref} 0 R")

        # Update font resources dictionary for used fonts
        # This is critical for PDF viewers to recognize the embedded fonts
        self._update_font_resources(page)

    def _update_font_resources(self, page) -> None:
        """
        Update page's font resources dictionary with used fonts.

        PDFMathTranslate high_level.py compliant.
        Adds font references to /Resources/Font dictionary.
        """
        if not self._used_fonts:
            return

        page_xref = page.xref

        # Get or create Resources dictionary
        resources_info = self.doc.xref_get_key(page_xref, "Resources")

        if resources_info[0] == "null" or resources_info[1] == "null":
            # No resources yet, create new
            resources_xref = self.doc.get_new_xref()
            self.doc.update_object(resources_xref, "<< >>")
            self.doc.xref_set_key(page_xref, "Resources", f"{resources_xref} 0 R")
            resources_info = ("xref", f"{resources_xref} 0 R")

        # Resolve resources xref
        if resources_info[0] == "xref":
            resources_xref = int(resources_info[1].split()[0])
        else:
            # Resources is inline dict - need to get its xref differently
            # For inline dicts, we'll add fonts directly to page resources
            resources_xref = page_xref

        # Get existing Font dictionary
        font_dict_info = self.doc.xref_get_key(resources_xref, "Font")

        # Build font entries for used fonts
        font_entries = []
        for font_id in self._used_fonts:
            font_xref = self.font_registry._font_xrefs.get(font_id)
            logger.debug(
                "_update_font_resources: font_id=%s, font_xref=%s, available_xrefs=%s",
                font_id, font_xref, list(self.font_registry._font_xrefs.keys())
            )
            if font_xref:
                font_entries.append(f"/{font_id} {font_xref} 0 R")

        logger.debug(
            "_update_font_resources: font_entries=%s, font_dict_info=%s",
            font_entries, font_dict_info
        )

        if not font_entries:
            logger.warning("_update_font_resources: no font entries to add")
            return

        if font_dict_info[0] == "dict":
            # Inline font dictionary - append to it
            existing = font_dict_info[1]
            # Remove closing ">>" and add new entries
            if existing.endswith(">>"):
                new_dict = existing[:-2] + " " + " ".join(font_entries) + " >>"
            else:
                new_dict = "<< " + " ".join(font_entries) + " >>"
            self.doc.xref_set_key(resources_xref, "Font", new_dict)

        elif font_dict_info[0] == "xref":
            # Font dict is a reference - update that object
            font_xref = int(font_dict_info[1].split()[0])
            existing_obj = self.doc.xref_object(font_xref)
            if existing_obj.endswith(">>"):
                new_obj = existing_obj[:-2] + " " + " ".join(font_entries) + " >>"
            else:
                new_obj = "<< " + " ".join(font_entries) + " >>"
            self.doc.update_object(font_xref, new_obj)

        else:
            # No font dict yet - create new one
            new_dict = "<< " + " ".join(font_entries) + " >>"
            self.doc.xref_set_key(resources_xref, "Font", new_dict)

    def clear(self) -> None:
        """Clear operator list."""
        self.operators = []
        self._in_text_block = False
        self._used_fonts.clear()
