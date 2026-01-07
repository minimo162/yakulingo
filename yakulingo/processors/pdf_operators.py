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
import re
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
        import threading

        self.font_registry = font_registry
        # Thread-safe set for tracking warned CID fonts (avoid duplicate warnings)
        self._warned_cid_fonts: set[str] = set()
        self._warned_cid_fonts_lock = threading.Lock()

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
        # Thread-safe check if we've already warned about this font
        with self._warned_cid_fonts_lock:
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
            # Non-Identity CMap detected - warn user (thread-safe)
            with self._warned_cid_fonts_lock:
                if font_id not in self._warned_cid_fonts:
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
            # Use surrogatescape to ensure round-trip compatibility
            content = stream.decode('latin-1', errors='surrogatepass')
        except (UnicodeDecodeError, AttributeError) as e:
            # If decoding fails, return empty stream to prevent text duplication
            # Do NOT return original stream as it would preserve text operators
            logger.error(
                "Failed to decode content stream: %s. "
                "Returning empty stream to prevent text duplication.",
                e
            )
            return b""

        # Debug: count BT/ET in original
        bt_count = content.count('BT')
        et_count = content.count('ET')
        logger.info(
            "parse_and_filter: original_len=%d, BT_count=%d, ET_count=%d, preview='%s'",
            len(content), bt_count, et_count,
            content[:300].replace('\n', '\\n').replace('\r', '\\r')
        )

        tokens = self._tokenize(content)

        # Debug: count token types
        operator_tokens = [t for t in tokens if t[0] == 'operator']
        bt_tokens = sum(1 for t in operator_tokens if t[1] == 'BT')
        et_tokens = sum(1 for t in operator_tokens if t[1] == 'ET')
        logger.info(
            "parse_and_filter: total_tokens=%d, operators=%d, BT_tokens=%d, ET_tokens=%d",
            len(tokens), len(operator_tokens), bt_tokens, et_tokens
        )

        filtered = self._filter_tokens(tokens)
        result = self._reconstruct(filtered)

        # Debug: compare sizes and check for remaining BT/ET
        result_bt = result.count('BT')
        result_et = result.count('ET')
        logger.info(
            "parse_and_filter: result_len=%d (reduction=%d%%), BT_in_result=%d, ET_in_result=%d",
            len(result),
            int((1 - len(result) / len(content)) * 100) if content else 0,
            result_bt, result_et
        )

        try:
            # Use surrogatepass to ensure round-trip compatibility with decode
            return result.encode('latin-1', errors='surrogatepass')
        except (UnicodeEncodeError, LookupError) as e:
            # If encoding fails, return empty stream to prevent text duplication
            # Do NOT return original stream as it would preserve text operators
            logger.error(
                "Failed to encode filtered content stream: %s. "
                "Returning empty stream to prevent text duplication.",
                e
            )
            return b""

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

            # Single-character text operators: ' and "
            # These are PDF text showing operators and must be treated as standalone
            # ' - move to next line and show text
            # " - set word/char spacing, move to next line and show text
            if c in "'\"":
                tokens.append(('operator', c))
                i += 1
                continue

            # Operator (keyword)
            # Note: * is part of compound operators like b*, B*, f*, T*
            if c.isalpha() or c == '*':
                j = i
                while j < n and (content[j].isalnum() or content[j] == '*'):
                    j += 1
                tokens.append(('operator', content[i:j]))
                i = j
                continue

            # Unknown - include as-is
            tokens.append(('unknown', c))
            i += 1

        return tokens

    # Text operators to skip globally (PDFMathTranslate pdfinterp.py compatible)
    # This set includes all operators that start with 'T' plus text-related operators
    TEXT_OPS_TO_SKIP = frozenset({
        # Text block boundaries
        'BT', 'ET',
        # Text showing operators
        'Tj', 'TJ', "'", '"',
        # Text state operators
        'Tc', 'Tw', 'Tz', 'TL', 'Tf', 'Tr', 'Ts',
        # Text positioning operators
        'Td', 'TD', 'Tm', 'T*',
    })

    def _filter_tokens(self, tokens: list[tuple[str, str]]) -> list[tuple[str, str]]:
        """
        Filter out text operators and their operands.

        PDFMathTranslate pdfinterp.py compatible:
        Removes ALL text-related operators globally, not just inside BT...ET blocks.
        This is more robust than BT/ET detection alone.

        The key insight from PDFMathTranslate:
        - Filter condition: `if not (name[0] == "T" or name in ['"', "'", ...])`
        - This removes operators starting with 'T' everywhere in the stream
        - More reliable than tracking BT/ET state which can fail on malformed PDFs
        """
        result = []
        i = 0
        n = len(tokens)
        operand_stack = []

        # Debug counters
        filtered_ops_count = 0
        filtered_operands_count = 0
        kept_ops_count = 0

        while i < n:
            token_type, token_value = tokens[i]

            if token_type == 'whitespace':
                # Always preserve whitespace for readability
                result.append((token_type, token_value))
                i += 1
                continue

            if token_type == 'operator':
                # PDFMathTranslate approach: skip operators starting with 'T'
                # or in the TEXT_OPS_TO_SKIP set
                is_text_op = (
                    token_value in self.TEXT_OPS_TO_SKIP or
                    (len(token_value) > 0 and token_value[0] == 'T')
                )

                if is_text_op:
                    # Skip this text operator and discard its operands
                    filtered_ops_count += 1
                    filtered_operands_count += len(operand_stack)
                    operand_stack = []  # Discard operands for text operator
                    i += 1
                    continue

                # Non-text operator: keep it with its operands
                result.extend(operand_stack)
                result.append((token_type, token_value))
                operand_stack = []
                kept_ops_count += 1
                i += 1
                continue

            # Operand (number, name, string, array, dict)
            # Accumulate until we see the operator
            operand_stack.append((token_type, token_value))
            i += 1

        # Add any remaining operands (edge case: stream ends without operator)
        if operand_stack:
            logger.debug(
                "_filter_tokens: %d trailing operands at stream end",
                len(operand_stack)
            )
            result.extend(operand_stack)

        # Debug output
        logger.info(
            "_filter_tokens (PDFMathTranslate mode): "
            "filtered_ops=%d, filtered_operands=%d, kept_ops=%d, result_tokens=%d",
            filtered_ops_count, filtered_operands_count, kept_ops_count, len(result)
        )

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

    def parse_and_filter_selective(
        self,
        stream: bytes,
        target_bboxes: list[tuple[float, float, float, float]],
        tolerance: float = 5.0,
    ) -> bytes:
        """
        Parse content stream and selectively remove text operators.

        Only removes text at positions that match target_bboxes.
        Text at other positions is preserved.

        Args:
            stream: Raw PDF content stream bytes
            target_bboxes: List of (x0, y0, x1, y1) bboxes to remove (PDF coordinates)
            tolerance: Position matching tolerance in points (default 5.0)

        Returns:
            Filtered content stream with only target text removed
        """
        if not target_bboxes:
            # No targets - return original stream unchanged
            return stream

        try:
            content = stream.decode('latin-1')
        except (UnicodeDecodeError, AttributeError):
            logger.warning("Failed to decode content stream, returning original")
            return stream

        tokens = self._tokenize(content)
        filtered = self._filter_tokens_selective(tokens, target_bboxes, tolerance)
        result = self._reconstruct(filtered)

        logger.info(
            "parse_and_filter_selective: original_len=%d, result_len=%d, "
            "target_bboxes=%d, tolerance=%.1f",
            len(content), len(result), len(target_bboxes), tolerance
        )

        try:
            # Use surrogatepass to ensure round-trip compatibility with decode
            return result.encode('latin-1', errors='surrogatepass')
        except (UnicodeEncodeError, LookupError) as e:
            # If encoding fails, return empty stream to prevent text duplication
            logger.error(
                "Failed to encode filtered content stream: %s. "
                "Returning empty stream to prevent text duplication.",
                e
            )
            return b""

    def _filter_tokens_selective(
        self,
        tokens: list[tuple[str, str]],
        target_bboxes: list[tuple[float, float, float, float]],
        tolerance: float = 5.0,
    ) -> list[tuple[str, str]]:
        """
        Filter text operators selectively based on position.

        Tracks text position using Tm/Td/TD operators and only removes
        text operators (Tj/TJ/'/") when the position matches a target bbox.

        Args:
            tokens: Tokenized content stream
            target_bboxes: List of (x0, y0, x1, y1) bboxes to remove
            tolerance: Position matching tolerance in points

        Returns:
            Filtered tokens with only target text removed
        """
        result = []
        i = 0
        n = len(tokens)
        in_text_block = False
        operand_stack = []

        # Text state tracking
        current_x = 0.0
        current_y = 0.0
        text_line_matrix = [1, 0, 0, 1, 0, 0]  # Identity matrix
        text_leading = 0.0

        # Pending text block tokens (may be kept or removed)
        pending_text_tokens = []
        pending_has_target = False  # Whether pending tokens contain target text

        # Debug counters
        removed_count = 0
        preserved_count = 0

        def _is_in_target_bbox(x: float, y: float) -> bool:
            """Check if position is within any target bbox."""
            for x0, y0, x1, y1 in target_bboxes:
                # Check if point is within bbox (with tolerance)
                if (x0 - tolerance <= x <= x1 + tolerance and
                    y0 - tolerance <= y <= y1 + tolerance):
                    return True
            return False

        def _parse_number(token_value: str) -> float:
            """Parse a number token to float."""
            try:
                return float(token_value)
            except (ValueError, TypeError):
                return 0.0

        while i < n:
            token_type, token_value = tokens[i]

            if token_type == 'whitespace':
                if in_text_block:
                    pending_text_tokens.append((token_type, token_value))
                else:
                    result.append((token_type, token_value))
                i += 1
                continue

            if token_type == 'operator':
                if token_value == 'BT':
                    # Enter text block
                    in_text_block = True
                    pending_text_tokens = [('operator', 'BT')]
                    pending_has_target = False
                    # Reset text state
                    current_x = 0.0
                    current_y = 0.0
                    text_line_matrix = [1, 0, 0, 1, 0, 0]
                    operand_stack = []
                    i += 1
                    continue

                if token_value == 'ET':
                    # Exit text block
                    pending_text_tokens.append(('operator', 'ET'))

                    if pending_has_target:
                        # This block contained target text - need selective filtering
                        # Re-process pending tokens to remove only target text
                        filtered_block = self._filter_text_block_selective(
                            pending_text_tokens, target_bboxes, tolerance
                        )
                        result.extend(filtered_block)
                        removed_count += 1
                    else:
                        # No target text in this block - keep entirely
                        result.extend(pending_text_tokens)
                        preserved_count += 1

                    in_text_block = False
                    pending_text_tokens = []
                    operand_stack = []
                    i += 1
                    continue

                if in_text_block:
                    # Track text position operators
                    if token_value == 'Tm' and len(operand_stack) >= 6:
                        # Text matrix: a b c d e f Tm
                        # e = x translation, f = y translation
                        e = _parse_number(operand_stack[-2][1])
                        f = _parse_number(operand_stack[-1][1])
                        text_line_matrix = [
                            _parse_number(operand_stack[-6][1]),
                            _parse_number(operand_stack[-5][1]),
                            _parse_number(operand_stack[-4][1]),
                            _parse_number(operand_stack[-3][1]),
                            e, f
                        ]
                        current_x = e
                        current_y = f

                    elif token_value in ('Td', 'TD') and len(operand_stack) >= 2:
                        # Move text position: tx ty Td/TD
                        tx = _parse_number(operand_stack[-2][1])
                        ty = _parse_number(operand_stack[-1][1])
                        current_x = text_line_matrix[4] + tx
                        current_y = text_line_matrix[5] + ty
                        text_line_matrix[4] = current_x
                        text_line_matrix[5] = current_y
                        if token_value == 'TD':
                            text_leading = -ty

                    elif token_value == "T*":
                        # Move to start of next line
                        current_x = text_line_matrix[4]
                        current_y = text_line_matrix[5] - text_leading

                    elif token_value == 'TL' and len(operand_stack) >= 1:
                        # Set text leading: leading TL
                        text_leading = _parse_number(operand_stack[-1][1])

                    # Check if this is a text showing operator
                    if token_value in ('Tj', 'TJ', "'", '"'):
                        if _is_in_target_bbox(current_x, current_y):
                            pending_has_target = True

                    # Add operator and operands to pending
                    pending_text_tokens.extend(operand_stack)
                    pending_text_tokens.append((token_type, token_value))
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
            # Accumulate operands until we see an operator
            operand_stack.append((token_type, token_value))
            i += 1

        # Add any remaining operands
        result.extend(operand_stack)

        logger.info(
            "_filter_tokens_selective: removed_blocks=%d, preserved_blocks=%d",
            removed_count, preserved_count
        )

        return result

    def _filter_text_block_selective(
        self,
        tokens: list[tuple[str, str]],
        target_bboxes: list[tuple[float, float, float, float]],
        tolerance: float,
    ) -> list[tuple[str, str]]:
        """
        Filter a single BT...ET block to remove only target text.

        Args:
            tokens: Tokens from BT to ET (inclusive)
            target_bboxes: Target bboxes to remove
            tolerance: Position matching tolerance

        Returns:
            Filtered tokens (may be empty if all text removed)
        """
        result = []
        i = 0
        n = len(tokens)
        operand_stack = []

        # Text state tracking
        current_x = 0.0
        current_y = 0.0
        text_line_matrix = [1, 0, 0, 1, 0, 0]
        text_leading = 0.0

        # Track if we've output any text operators
        has_remaining_text = False

        def _is_in_target_bbox(x: float, y: float) -> bool:
            for x0, y0, x1, y1 in target_bboxes:
                if (x0 - tolerance <= x <= x1 + tolerance and
                    y0 - tolerance <= y <= y1 + tolerance):
                    return True
            return False

        def _parse_number(token_value: str) -> float:
            try:
                return float(token_value)
            except (ValueError, TypeError):
                return 0.0

        while i < n:
            token_type, token_value = tokens[i]

            if token_type == 'whitespace':
                operand_stack.append((token_type, token_value))
                i += 1
                continue

            if token_type == 'operator':
                if token_value == 'BT':
                    result.append((token_type, token_value))
                    operand_stack = []
                    i += 1
                    continue

                if token_value == 'ET':
                    if has_remaining_text:
                        result.append((token_type, token_value))
                    else:
                        # No text remaining - remove entire BT...ET
                        result = []
                    i += 1
                    continue

                # Track position operators
                if token_value == 'Tm' and len(operand_stack) >= 6:
                    nums = [t for t in operand_stack if t[0] == 'number']
                    if len(nums) >= 6:
                        e = _parse_number(nums[-2][1])
                        f = _parse_number(nums[-1][1])
                        text_line_matrix[4] = e
                        text_line_matrix[5] = f
                        current_x = e
                        current_y = f

                elif token_value in ('Td', 'TD'):
                    nums = [t for t in operand_stack if t[0] == 'number']
                    if len(nums) >= 2:
                        tx = _parse_number(nums[-2][1])
                        ty = _parse_number(nums[-1][1])
                        current_x = text_line_matrix[4] + tx
                        current_y = text_line_matrix[5] + ty
                        text_line_matrix[4] = current_x
                        text_line_matrix[5] = current_y

                elif token_value == "T*":
                    current_x = text_line_matrix[4]
                    current_y = text_line_matrix[5] - text_leading

                elif token_value == 'TL':
                    nums = [t for t in operand_stack if t[0] == 'number']
                    if nums:
                        text_leading = _parse_number(nums[-1][1])

                # Check if this is a text showing operator
                if token_value in ('Tj', 'TJ', "'", '"'):
                    if _is_in_target_bbox(current_x, current_y):
                        # Target text - skip this operator and its operands
                        logger.debug(
                            "Removing text at (%.1f, %.1f): op=%s",
                            current_x, current_y, token_value
                        )
                        operand_stack = []
                        i += 1
                        continue
                    else:
                        # Non-target text - keep it
                        has_remaining_text = True

                # Keep this operator and its operands
                result.extend(operand_stack)
                result.append((token_type, token_value))
                operand_stack = []
                i += 1
                continue

            # Operand
            operand_stack.append((token_type, token_value))
            i += 1

        return result

    def filter_page_contents_selective(
        self,
        doc,
        page,
        target_bboxes: list[tuple[float, float, float, float]],
        tolerance: float = 5.0,
    ) -> bytes:
        """
        Get and selectively filter content streams for a page.

        Only removes text at positions matching target_bboxes.

        Args:
            doc: PyMuPDF document
            page: PyMuPDF page
            target_bboxes: List of (x0, y0, x1, y1) bboxes to remove
            tolerance: Position matching tolerance

        Returns:
            Filtered content stream
        """
        filtered_parts = []
        contents = page.get_contents()
        if not contents:
            return b""

        for xref in contents:
            try:
                stream = doc.xref_stream(xref)
                if stream:
                    filtered = self.parse_and_filter_selective(
                        stream, target_bboxes, tolerance
                    )
                    filtered_parts.append(filtered)
            except (RuntimeError, ValueError, KeyError, OSError) as e:
                # IMPORTANT: Do NOT use original stream as fallback - it would preserve
                # text operators and cause text duplication. Skip this stream instead.
                logger.error(
                    "Failed to filter content stream xref %d: %s. "
                    "Skipping stream to prevent text duplication.",
                    xref, e
                )
                # Append empty bytes to maintain structure but prevent text duplication
                filtered_parts.append(b"")

        return b" ".join(filtered_parts)

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
            logger.debug("filter_page_contents: no content streams for page %d", page.number)
            return b""

        total_original_size = 0
        total_filtered_size = 0

        for xref in contents:
            try:
                stream = doc.xref_stream(xref)
                if stream:
                    original_size = len(stream)
                    filtered = self.parse_and_filter(stream)
                    filtered_size = len(filtered)
                    filtered_parts.append(filtered)
                    total_original_size += original_size
                    total_filtered_size += filtered_size
            except (RuntimeError, ValueError, KeyError, OSError) as e:
                # RuntimeError: PyMuPDF internal errors
                # ValueError: invalid stream data
                # KeyError: missing xref entry
                # OSError: file access issues
                # IMPORTANT: Do NOT use original stream as fallback - it would preserve
                # text operators and cause text duplication. Skip this stream instead.
                logger.error(
                    "Failed to filter content stream xref %d: %s. "
                    "Skipping stream to prevent text duplication.",
                    xref, e
                )
                # Append empty bytes to maintain structure but prevent text duplication
                filtered_parts.append(b"")

        result = b" ".join(filtered_parts)
        logger.debug(
            "filter_page_contents: page=%d, streams=%d, original_size=%d, "
            "filtered_size=%d, result_size=%d",
            page.number, len(contents), total_original_size,
            total_filtered_size, len(result)
        )
        return result


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

    def set_base_stream(
        self,
        page,
        target_bboxes: Optional[list[tuple[float, float, float, float]]] = None,
        tolerance: float = 5.0,
        skip_xobject_filtering: bool = False,
        allowed_xrefs: Optional[set[int]] = None,
    ) -> 'ContentStreamReplacer':
        """
        Capture and filter the original content stream for this page.

        This removes text operators while preserving graphics/images.
        Also filters text from Form XObjects referenced by this page.
        Must be called before adding new text operators.

        Args:
            page: PyMuPDF page object
            target_bboxes: If provided, only remove text at these positions.
                          If None, remove all text (default behavior).
                          Format: list of (x0, y0, x1, y1) in PDF coordinates.
            tolerance: Position matching tolerance for selective removal (default 5.0)
            skip_xobject_filtering: If True, skip Form XObject filtering.
                          Use this when filter_all_document_xobjects() has already
                          been called to avoid redundant processing.
            allowed_xrefs: Optional set of XObject xrefs to filter. When provided,
                           only these XObjects are filtered.

        Returns:
            self for chaining
        """
        if not self._preserve_graphics or not self._parser:
            return self

        # Filter Form XObjects first (they can contain embedded text).
        #
        # IMPORTANT:
        # - In "remove all text" mode (target_bboxes is None), we filter XObjects too,
        #   because we'll redraw all text anyway.
        # - In selective mode, do NOT filter XObjects. Filtering them entirely would
        #   delete unrelated text and break layout when we are only redrawing a subset.
        # - If skip_xobject_filtering is True, skip this step (document-wide filtering
        #   has already been done via filter_all_document_xobjects()).
        if target_bboxes is None and not skip_xobject_filtering:
            # Note: Form XObjects are filtered completely for now
            # (selective filtering of XObjects is more complex)
            self._filter_form_xobjects(page, allowed_xrefs)

        if target_bboxes is not None:
            # Selective filtering: only remove text at target positions
            self._filtered_base_stream = self._parser.filter_page_contents_selective(
                self.doc, page, target_bboxes, tolerance
            )
            logger.info(
                "set_base_stream: selective mode with %d target bboxes, tolerance=%.1f",
                len(target_bboxes), tolerance
            )
        else:
            # Default: remove all text
            self._filtered_base_stream = self._parser.filter_page_contents(self.doc, page)

        return self

    def _filter_form_xobjects(self, page, allowed_xrefs: Optional[set[int]] = None) -> None:
        """
        Filter text from Form XObjects referenced by this page.

        Form XObjects (also called XForms) can contain text that is rendered
        via the 'Do' operator. This method filters text operators from all
        Form XObjects referenced by this page, including inherited ones
        and nested XObjects (yomitoku-style recursive processing).

        Uses PyMuPDF's get_xobjects() for reliable detection of all XObjects,
        including those defined in parent Resources or referenced indirectly.

        Args:
            page: PyMuPDF page object
            allowed_xrefs: Optional set of XObject xrefs to filter. When provided,
                only these XObjects are filtered.
        """
        try:
            # Use PyMuPDF's get_xobjects() for reliable XObject detection
            # This handles inherited resources and complex PDF structures
            xobjects = page.get_xobjects()
            logger.info(
                "_filter_form_xobjects: page=%d, get_xobjects() returned %d items: %s",
                page.number, len(xobjects),
                [(x[0], x[1]) for x in xobjects[:10]]  # (xref, name) for first 10
            )

            if not xobjects:
                logger.info("_filter_form_xobjects: no XObjects on page %d", page.number)
                return

            filtered_count = 0
            processed_xrefs = set()  # Track processed xrefs to avoid duplicates

            # Collect all XObject xrefs for recursive processing
            xref_queue = [(xobj[0], xobj[1]) for xobj in xobjects]

            while xref_queue:
                xref, name = xref_queue.pop(0)

                # Skip if already processed (avoid nested duplicates)
                if xref in processed_xrefs:
                    continue
                if allowed_xrefs is not None and xref not in allowed_xrefs:
                    continue
                processed_xrefs.add(xref)

                try:
                    # Get object definition to check type
                    obj_str = self.doc.xref_object(xref)

                    # Check if this is a Form XObject
                    is_form = '/Subtype /Form' in obj_str or '/Subtype/Form' in obj_str
                    if not is_form:
                        logger.debug(
                            "_filter_form_xobjects: /%s (xref=%d) is not Form: %s",
                            name, xref, obj_str[:80]
                        )
                        continue

                    # Get the stream content
                    stream = self.doc.xref_stream(xref)
                    if not stream:
                        logger.debug("_filter_form_xobjects: /%s (xref=%d) has no stream", name, xref)
                        continue

                    # Filter text operators from the stream
                    original_size = len(stream)
                    filtered_stream = self._parser.parse_and_filter(stream)
                    filtered_size = len(filtered_stream)

                    logger.info(
                        "_filter_form_xobjects: Form /%s xref=%d, original=%d, filtered=%d",
                        name, xref, original_size, filtered_size
                    )

                    # Only update if we actually removed something
                    if filtered_size < original_size:
                        self.doc.update_stream(xref, filtered_stream)
                        filtered_count += 1
                        logger.info(
                            "_filter_form_xobjects: FILTERED Form XObject /%s (xref=%d): %d -> %d bytes",
                            name, xref, original_size, filtered_size
                        )

                    # yomitoku-style: Check for nested XObjects in this Form's Resources
                    # Form XObjects can have their own /Resources with nested XObjects
                    self._find_nested_xobjects(xref, obj_str, xref_queue, processed_xrefs)

                except (RuntimeError, ValueError, KeyError, OSError) as e:
                    logger.debug("Could not filter Form XObject /%s (xref=%d): %s", name, xref, e)
                    continue

            logger.info(
                "_filter_form_xobjects: page=%d, filtered %d Form XObjects",
                page.number, filtered_count
            )

        except (RuntimeError, ValueError, KeyError, AttributeError, OSError) as e:
            # Non-critical error - page may not have XObjects
            logger.debug("Form XObject filtering skipped for page %d: %s", page.number, e)

    # Pre-compiled regex patterns for XObject detection (performance optimization)
    _RE_XOBJECT_DICT = re.compile(r'/XObject\s*<<([^>]*)>>')
    _RE_XOBJECT_REF = re.compile(r'/(\w+)\s+(\d+)\s+0\s+R')
    _RE_RESOURCES_REF = re.compile(r'/Resources\s+(\d+)\s+0\s+R')

    def _find_nested_xobjects(
        self,
        parent_xref: int,
        obj_str: str,
        xref_queue: list,
        processed_xrefs: set,
    ) -> None:
        """
        Find nested XObjects in a Form XObject's Resources.

        yomitoku-style recursive XObject discovery.
        Form XObjects can have their own /Resources dictionary containing
        additional XObjects that need to be processed.

        Args:
            parent_xref: xref of the parent Form XObject
            obj_str: Object definition string of the parent
            xref_queue: Queue of xrefs to process
            processed_xrefs: Set of already processed xrefs
        """
        try:
            # Look for /Resources in the object definition
            if '/Resources' not in obj_str:
                return

            # Pattern 1: Inline XObject dictionary /XObject << /Name N 0 R >>
            match = self._RE_XOBJECT_DICT.search(obj_str)
            if match:
                xobj_dict = match.group(1)
                # Find all references to XObjects (format: /Name N 0 R)
                for name_match in self._RE_XOBJECT_REF.finditer(xobj_dict):
                    nested_name = name_match.group(1)
                    nested_xref = int(name_match.group(2))

                    if nested_xref not in processed_xrefs:
                        logger.debug(
                            "_find_nested_xobjects: Found nested XObject /%s (xref=%d) in parent xref=%d",
                            nested_name, nested_xref, parent_xref
                        )
                        xref_queue.append((nested_xref, nested_name))

            # Pattern 2: Indirect reference to Resources /Resources N 0 R
            resources_match = self._RE_RESOURCES_REF.search(obj_str)
            if resources_match:
                resources_xref = int(resources_match.group(1))
                # Prevent infinite recursion by checking if already processed
                if resources_xref in processed_xrefs:
                    return
                processed_xrefs.add(resources_xref)
                try:
                    resources_obj = self.doc.xref_object(resources_xref)
                    # Recursively search for XObjects in the Resources dictionary
                    self._find_nested_xobjects(resources_xref, resources_obj, xref_queue, processed_xrefs)
                except (RuntimeError, ValueError, KeyError) as e:
                    logger.debug("Could not resolve Resources xref=%d: %s", resources_xref, e)

        except (ValueError, AttributeError, re.error) as e:
            logger.debug("Could not find nested XObjects in xref=%d: %s", parent_xref, e)

    def filter_all_document_xobjects(self) -> int:
        """
        Filter text from ALL Form XObjects in the entire document.

        This is more thorough than per-page filtering and catches XObjects
        that may be shared across multiple pages or nested deeply.

        Based on yomitoku's approach of scanning the entire document structure.

        Returns:
            Number of Form XObjects that were filtered
        """
        if not self._parser:
            return 0

        filtered_count = 0
        processed_xrefs = set()

        # Scan all xrefs in the document
        xref_count = self.doc.xref_length()
        logger.info(
            "filter_all_document_xobjects: scanning %d xrefs in document",
            xref_count
        )

        for xref in range(1, xref_count):
            if xref in processed_xrefs:
                continue

            try:
                # Get object definition
                obj_str = self.doc.xref_object(xref)
                if not obj_str:
                    continue

                # Check if this is a Form XObject
                is_form = '/Subtype /Form' in obj_str or '/Subtype/Form' in obj_str
                if not is_form:
                    continue

                processed_xrefs.add(xref)

                # Get the stream content
                stream = self.doc.xref_stream(xref)
                if not stream:
                    continue

                # Filter text operators from the stream
                original_size = len(stream)
                filtered_stream = self._parser.parse_and_filter(stream)
                filtered_size = len(filtered_stream)

                # Only update if we actually removed something
                if filtered_size < original_size:
                    self.doc.update_stream(xref, filtered_stream)
                    filtered_count += 1
                    logger.info(
                        "filter_all_document_xobjects: FILTERED Form XObject xref=%d: %d -> %d bytes",
                        xref, original_size, filtered_size
                    )

            except (RuntimeError, ValueError, KeyError, OSError) as e:
                logger.debug("Could not process xref=%d: %s", xref, e)
                continue

        logger.info(
            "filter_all_document_xobjects: filtered %d Form XObjects in document",
            filtered_count
        )
        return filtered_count

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

    def add_white_background(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        margin: float = 1.0,
    ) -> 'ContentStreamReplacer':
        """
        Add white background rectangle to cover original text.

        PDFMathTranslate compliant: Draws a white rectangle before text
        to ensure original text is completely hidden. This provides a
        fallback when content stream filtering is incomplete.

        Args:
            x0: Left edge in PDF coordinates
            y0: Bottom edge in PDF coordinates
            x1: Right edge in PDF coordinates
            y1: Top edge in PDF coordinates
            margin: Extra margin around the rectangle (default 1.0pt)

        Returns:
            self for chaining
        """
        # Close any open text block before drawing graphics
        if self._in_text_block:
            self.end_text()

        # Apply margin
        x0 = x0 - margin
        y0 = y0 - margin
        x1 = x1 + margin
        y1 = y1 + margin

        width = x1 - x0
        height = y1 - y0

        # Draw white filled rectangle
        # q: save graphics state
        # 1 1 1 rg: set fill color to white (RGB)
        # x y w h re: draw rectangle
        # f: fill
        # Q: restore graphics state
        op = f"q 1 1 1 rg {x0:f} {y0:f} {width:f} {height:f} re f Q "
        self.operators.append(op)

        logger.debug(
            "add_white_background: x0=%.1f, y0=%.1f, x1=%.1f, y1=%.1f",
            x0, y0, x1, y1
        )

        return self

    def begin_clipped_region(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        margin: float = 0.5,
    ) -> 'ContentStreamReplacer':
        """
        Begin a clipped drawing region (q ... W n).

        This is used to prevent translated text from painting over table borders
        or cell background colors when the translated text does not fully fit
        inside the target bounding box.
        """
        if self._in_text_block:
            self.end_text()

        # Normalize coordinates
        if x0 > x1:
            x0, x1 = x1, x0
        if y0 > y1:
            y0, y1 = y1, y0

        # Apply margin (expand slightly to avoid cutting glyph edges)
        if margin:
            x0 -= margin
            y0 -= margin
            x1 += margin
            y1 += margin

        width = x1 - x0
        height = y1 - y0
        if width <= 0 or height <= 0:
            return self

        # q: save graphics state, re: rectangle, W n: set clipping path
        op = f"q {x0:f} {y0:f} {width:f} {height:f} re W n "
        self.operators.append(op)
        return self

    def end_clipped_region(self) -> 'ContentStreamReplacer':
        """End a clipped drawing region (Q)."""
        if self._in_text_block:
            self.end_text()
        self.operators.append("Q ")
        return self

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

            # Enhanced debug: Check for remaining text operators (PDFMathTranslate mode)
            filtered_str = self._filtered_base_stream.decode('latin-1', errors='replace')

            # Check for text-related operators that should have been removed
            # Use word boundary patterns to avoid false positives
            import re
            text_ops_pattern = r'\b(BT|ET|Tj|TJ|Tf|Td|TD|Tm|T\*|Tc|Tw|Tz|TL|Tr|Ts)\b'
            remaining_text_ops = re.findall(text_ops_pattern, filtered_str)

            logger.info(
                "build_combined: filtered_base_len=%d, combined_len=%d, "
                "remaining_text_ops=%d",
                len(self._filtered_base_stream), len(combined),
                len(remaining_text_ops)
            )

            if remaining_text_ops:
                # Count each operator type
                op_counts = {}
                for op in remaining_text_ops:
                    op_counts[op] = op_counts.get(op, 0) + 1
                logger.error(
                    "CRITICAL: filtered_base still contains text operators! "
                    "This will cause text duplication. Operators found: %s. "
                    "Check ContentStreamParser._filter_tokens implementation.",
                    op_counts
                )

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

        # Debug: Show original Contents before replacement
        page_xref = page.xref
        original_contents = self.doc.xref_get_key(page_xref, "Contents")
        logger.info(
            "apply_to_page: page=%d, original_contents=%s",
            page.number, original_contents
        )

        # Create new stream object
        new_xref = self.doc.get_new_xref()
        # Initialize xref as PDF dict before updating stream
        # (get_new_xref only allocates xref number, doesn't create dict object)
        self.doc.update_object(new_xref, "<< >>")
        self.doc.update_stream(new_xref, stream_bytes)

        # REPLACE page Contents (not append)
        # This ensures original text is removed
        self.doc.xref_set_key(page_xref, "Contents", f"{new_xref} 0 R")

        # Debug: Verify replacement
        new_contents = self.doc.xref_get_key(page_xref, "Contents")
        logger.info(
            "apply_to_page: page=%d, new_contents=%s, new_xref=%d, stream_len=%d",
            page.number, new_contents, new_xref, len(stream_bytes)
        )

        # Update font resources dictionary for used fonts
        # This is critical for PDF viewers to recognize the embedded fonts
        self._update_font_resources(page)

    def _update_font_resources(self, page) -> None:
        """
        Update page's font resources dictionary with used fonts.

        PDFMathTranslate high_level.py compliant.
        Adds font references to /Resources/Font dictionary.

        IMPORTANT: Handles inherited Resources correctly. When a page inherits
        Resources from its parent, we must copy the inherited Resources to the
        page before modifying, to preserve XObject and other resource references.
        """
        if not self._used_fonts:
            return

        page_xref = page.xref

        # Get or create Resources dictionary
        resources_info = self.doc.xref_get_key(page_xref, "Resources")

        if resources_info[0] == "null" or resources_info[1] == "null":
            # Resources might be inherited from parent - need to copy it first
            # Try to get resolved Resources using page object method
            inherited_resources = self._get_inherited_resources(page)
            if inherited_resources:
                # Copy inherited Resources to this page
                resources_xref = self.doc.get_new_xref()
                self.doc.update_object(resources_xref, inherited_resources)
                self.doc.xref_set_key(page_xref, "Resources", f"{resources_xref} 0 R")
                resources_info = ("xref", f"{resources_xref} 0 R")
                logger.debug(
                    "_update_font_resources: copied inherited Resources to page %d (xref=%d)",
                    page.number, resources_xref
                )
            else:
                # No inherited resources found, create new
                resources_xref = self.doc.get_new_xref()
                self.doc.update_object(resources_xref, "<< >>")
                self.doc.xref_set_key(page_xref, "Resources", f"{resources_xref} 0 R")
                resources_info = ("xref", f"{resources_xref} 0 R")

        # Resolve resources xref
        if resources_info[0] == "xref":
            resources_xref = int(resources_info[1].split()[0])
        elif resources_info[0] == "dict":
            # Resources is inline dict - convert to reference for proper Font handling
            # This is necessary because we cannot add nested keys (Resources/Font)
            # directly to an inline dictionary through xref_set_key.
            # Create a new xref for Resources and move the inline dict there.
            existing_resources = resources_info[1]
            resources_xref = self.doc.get_new_xref()
            self.doc.update_object(resources_xref, existing_resources)
            self.doc.xref_set_key(page_xref, "Resources", f"{resources_xref} 0 R")
            logger.debug(
                "_update_font_resources: converted inline Resources to xref=%d",
                resources_xref
            )
        else:
            # Unexpected type - create new Resources
            logger.warning(
                "_update_font_resources: unexpected Resources type '%s', creating new",
                resources_info[0]
            )
            resources_xref = self.doc.get_new_xref()
            self.doc.update_object(resources_xref, "<< >>")
            self.doc.xref_set_key(page_xref, "Resources", f"{resources_xref} 0 R")

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
            existing = font_dict_info[1].strip()  # Strip whitespace to fix endswith check
            # Remove closing ">>" and add new entries
            if existing.endswith(">>"):
                new_dict = existing[:-2] + " " + " ".join(font_entries) + " >>"
            else:
                # Malformed dict - try to parse and preserve existing entries
                logger.warning(
                    "_update_font_resources: Font dict doesn't end with '>>', "
                    "attempting to preserve existing entries: %s",
                    existing[:100]
                )
                # Extract existing font entries using regex
                import re
                existing_entries = re.findall(r'/\w+\s+\d+\s+\d+\s+R', existing)
                all_entries = existing_entries + font_entries
                new_dict = "<< " + " ".join(all_entries) + " >>"
            self.doc.xref_set_key(resources_xref, "Font", new_dict)

        elif font_dict_info[0] == "xref":
            # Font dict is a reference - update that object
            font_xref_num = int(font_dict_info[1].split()[0])
            existing_obj = self.doc.xref_object(font_xref_num).strip()  # Strip whitespace
            if existing_obj.endswith(">>"):
                new_obj = existing_obj[:-2] + " " + " ".join(font_entries) + " >>"
            else:
                # Malformed dict - try to parse and preserve existing entries
                logger.warning(
                    "_update_font_resources: Font xref object doesn't end with '>>', "
                    "attempting to preserve existing entries: %s",
                    existing_obj[:100]
                )
                import re
                existing_entries = re.findall(r'/\w+\s+\d+\s+\d+\s+R', existing_obj)
                all_entries = existing_entries + font_entries
                new_obj = "<< " + " ".join(all_entries) + " >>"
            self.doc.update_object(font_xref_num, new_obj)

        else:
            # No font dict yet - create new one
            new_dict = "<< " + " ".join(font_entries) + " >>"
            self.doc.xref_set_key(resources_xref, "Font", new_dict)

    def _get_inherited_resources(self, page) -> Optional[str]:
        """
        Get inherited Resources dictionary from page's parent.

        When a page doesn't have its own Resources, it inherits from parent.
        This method traces the parent chain to find the inherited Resources.

        Args:
            page: PyMuPDF page object

        Returns:
            Resources dictionary string if found, None otherwise
        """
        try:
            # Try to get parent reference from page object
            parent_info = self.doc.xref_get_key(page.xref, "Parent")
            if parent_info[0] != "xref":
                return None

            parent_xref = int(parent_info[1].split()[0])

            # Check parent for Resources (may need to recurse up the tree)
            # Limit recursion to prevent infinite loops
            max_depth = 10
            for _ in range(max_depth):
                parent_resources = self.doc.xref_get_key(parent_xref, "Resources")

                if parent_resources[0] == "dict":
                    logger.debug(
                        "_get_inherited_resources: found inline Resources in parent xref=%d",
                        parent_xref
                    )
                    return parent_resources[1]

                elif parent_resources[0] == "xref":
                    # Resources is a reference - get the actual object
                    res_xref = int(parent_resources[1].split()[0])
                    res_obj = self.doc.xref_object(res_xref)
                    logger.debug(
                        "_get_inherited_resources: found Resources xref=%d in parent xref=%d",
                        res_xref, parent_xref
                    )
                    return res_obj

                # Resources not found at this level, try grandparent
                grandparent_info = self.doc.xref_get_key(parent_xref, "Parent")
                if grandparent_info[0] != "xref":
                    break
                parent_xref = int(grandparent_info[1].split()[0])

            logger.debug("_get_inherited_resources: no inherited Resources found")
            return None

        except (ValueError, KeyError, RuntimeError) as e:
            logger.debug("_get_inherited_resources: error tracing parent chain: %s", e)
            return None

    def clear(self) -> None:
        """Clear operator list."""
        self.operators = []
        self._in_text_block = False
        self._used_fonts.clear()
