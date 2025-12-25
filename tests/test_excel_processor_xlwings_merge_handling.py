from __future__ import annotations

from dataclasses import dataclass

import pytest

from openpyxl.utils.cell import get_column_letter

from yakulingo.processors.excel_processor import ExcelProcessor
from yakulingo.processors.font_manager import FontManager


@dataclass
class _CellStyle:
    font_name: str | None = None
    font_size: float | None = None


class _FakeMergeArea:
    def __init__(self, sheet: "_FakeSheet", bounds: tuple[int, int, int, int]) -> None:
        self._sheet = sheet
        self._bounds = bounds
        self.Row = bounds[0]
        self.Column = bounds[1]
        self.Font = _FakeFont(sheet, bounds, is_merge_area=True)


class _FakeFont:
    def __init__(
        self,
        sheet: "_FakeSheet",
        bounds: tuple[int, int, int, int],
        *,
        is_merge_area: bool = False,
    ) -> None:
        self._sheet = sheet
        self._bounds = bounds
        self._is_merge_area = is_merge_area

    @property
    def Name(self) -> str | None:  # noqa: N802 (Excel API style)
        (r1, c1, _r2, _c2) = self._bounds
        return self._sheet.styles.get((r1, c1), _CellStyle()).font_name

    @Name.setter
    def Name(self, value: str) -> None:  # noqa: N802 (Excel API style)
        (r1, c1, r2, c2) = self._bounds

        # Simulate Excel being picky: setting Font.Name on a merged single-cell range
        # can fail unless you format the MergeArea. Our production code uses MergeArea
        # for merged cells, so this should only trigger if we regress.
        if not self._is_merge_area:
            for r in range(r1, r2 + 1):
                for c in range(c1, c2 + 1):
                    merge_bounds = self._sheet.find_merge_bounds(r, c)
                    if merge_bounds is not None:
                        raise RuntimeError("Cannot format part of a merged cell")

        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                style = self._sheet.styles.get((r, c), _CellStyle())
                style.font_name = value
                self._sheet.styles[(r, c)] = style

    @property
    def Size(self) -> float | None:  # noqa: N802 (Excel API style)
        (r1, c1, _r2, _c2) = self._bounds
        return self._sheet.styles.get((r1, c1), _CellStyle()).font_size

    @Size.setter
    def Size(self, value: float) -> None:  # noqa: N802 (Excel API style)
        (r1, c1, r2, c2) = self._bounds
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                style = self._sheet.styles.get((r, c), _CellStyle())
                style.font_size = value
                self._sheet.styles[(r, c)] = style


class _FakeApiRange:
    def __init__(self, sheet: "_FakeSheet", bounds: tuple[int, int, int, int]) -> None:
        self._sheet = sheet
        self._bounds = bounds
        self.Font = _FakeFont(sheet, bounds)

    @property
    def MergeCells(self) -> bool:  # noqa: N802 (Excel API style)
        (r1, c1, r2, c2) = self._bounds
        if (r1, c1) != (r2, c2):
            return any(self._sheet.find_merge_bounds(r1, c) for c in range(c1, c2 + 1))
        return self._sheet.find_merge_bounds(r1, c1) is not None

    @property
    def MergeArea(self) -> _FakeMergeArea:  # noqa: N802 (Excel API style)
        (r1, c1, r2, c2) = self._bounds
        if (r1, c1) != (r2, c2):
            raise RuntimeError("MergeArea requested for multi-cell range")
        merge_bounds = self._sheet.find_merge_bounds(r1, c1)
        if merge_bounds is None:
            raise RuntimeError("MergeArea requested for unmerged cell")
        return _FakeMergeArea(self._sheet, merge_bounds)


class _FakeRange:
    def __init__(self, sheet: "_FakeSheet", bounds: tuple[int, int, int, int]) -> None:
        self._sheet = sheet
        self._bounds = bounds
        self.api = _FakeApiRange(sheet, bounds)

    @property
    def value(self):  # noqa: ANN001
        (r1, c1, r2, c2) = self._bounds
        if (r1, c1) == (r2, c2):
            return self._sheet.values.get((r1, c1))
        raise NotImplementedError

    @value.setter
    def value(self, v):  # noqa: ANN001
        (r1, c1, r2, c2) = self._bounds
        if (r1, c1) == (r2, c2):
            merge_bounds = self._sheet.find_merge_bounds(r1, c1)
            if merge_bounds is not None and (r1, c1) != (merge_bounds[0], merge_bounds[1]):
                raise RuntimeError("Cannot change part of a merged cell")
            self._sheet.values[(r1, c1)] = v
            return

        # Simulate Excel raising on batched writes that intersect merged cells.
        if r1 != r2:
            raise RuntimeError("Only single-row batch writes supported in fake")
        for c in range(c1, c2 + 1):
            if self._sheet.find_merge_bounds(r1, c) is not None:
                raise RuntimeError("Cannot batch-write across merged cells")

        if not isinstance(v, list):
            raise RuntimeError("Batch write expects list")
        if len(v) != (c2 - c1 + 1):
            raise RuntimeError("Batch write list length mismatch")
        for idx, c in enumerate(range(c1, c2 + 1)):
            self._sheet.values[(r1, c)] = v[idx]


class _FakeSheet:
    def __init__(self, name: str, merged_areas: list[tuple[int, int, int, int]] | None = None) -> None:
        self.name = name
        self._merged_areas = merged_areas or []
        self.values: dict[tuple[int, int], str] = {}
        self.styles: dict[tuple[int, int], _CellStyle] = {}
        self.range_calls: list[tuple[int, int, int, int]] = []

    def find_merge_bounds(self, row: int, col: int) -> tuple[int, int, int, int] | None:
        for (r1, c1, r2, c2) in self._merged_areas:
            if r1 <= row <= r2 and c1 <= col <= c2:
                return (r1, c1, r2, c2)
        return None

    def range(self, *args):  # noqa: ANN001
        if len(args) == 2 and all(isinstance(a, int) for a in args):
            row, col = args
            bounds = (row, col, row, col)
        elif (
            len(args) == 2
            and isinstance(args[0], tuple)
            and isinstance(args[1], tuple)
            and len(args[0]) == 2
            and len(args[1]) == 2
        ):
            (r1, c1) = args[0]
            (r2, c2) = args[1]
            bounds = (r1, c1, r2, c2)
        else:
            raise TypeError(f"Unsupported range call: {args!r}")

        self.range_calls.append(bounds)
        return _FakeRange(self, bounds)


@pytest.mark.unit
def test_xlwings_apply_maps_merged_non_topleft_to_topleft(monkeypatch: pytest.MonkeyPatch) -> None:
    processor = ExcelProcessor()
    sheet = _FakeSheet("Sheet1", merged_areas=[(1, 1, 1, 3)])  # A1:C1 merged

    merged_map = {"A1:C1": (1, 1, 1, 3)}
    monkeypatch.setattr(processor, "_get_merged_cells_map", lambda _sheet: merged_map)

    # Intentionally insert non-top-left first to verify "top-left wins" when both exist.
    cell_translations = {
        (1, 2): ("T_B1", "B1"),  # inside merge area
        (1, 1): ("T_A1", "A1"),  # top-left
        (1, 4): ("T_D1", "D1"),  # normal cell
    }

    processor._apply_cell_translations_xlwings_batch(  # noqa: SLF001 (unit test)
        sheet, "Sheet1", cell_translations, FontManager("jp_to_en")
    )

    assert sheet.values[(1, 1)] == "T_A1"
    assert sheet.values[(1, 4)] == "T_D1"
    assert (1, 2) not in sheet.values  # should never write to non-top-left merged cell


@pytest.mark.unit
def test_xlwings_apply_avoids_batch_ops_when_merge_in_range(monkeypatch: pytest.MonkeyPatch) -> None:
    processor = ExcelProcessor()
    sheet = _FakeSheet("Sheet1", merged_areas=[(1, 1, 2, 1)])  # A1:A2 merged (vertical)

    merged_map = {"A1:A2": (1, 1, 2, 1)}
    monkeypatch.setattr(processor, "_get_merged_cells_map", lambda _sheet: merged_map)

    # A1 (merged) and B1 are contiguous: a naive implementation would attempt a batched range write.
    cell_translations = {
        (1, 1): ("T_A1", "A1"),
        (1, 2): ("T_B1", "B1"),
    }

    processor._apply_cell_translations_xlwings_batch(  # noqa: SLF001 (unit test)
        sheet, "Sheet1", cell_translations, FontManager("jp_to_en")
    )

    assert sheet.values[(1, 1)] == "T_A1"
    assert sheet.values[(1, 2)] == "T_B1"

    # Ensure we never requested a multi-cell range (tuple-based) during value/font application.
    assert all((r1, c1) == (r2, c2) for (r1, c1, r2, c2) in sheet.range_calls)


@pytest.mark.unit
def test_xlwings_apply_batches_range_ops_for_dense_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    processor = ExcelProcessor()
    sheet = _FakeSheet("Sheet1")

    monkeypatch.setattr(processor, "_get_merged_cells_map", lambda _sheet: {})

    rows = 100
    cols = 10
    cell_translations: dict[tuple[int, int], tuple[str, str]] = {}
    for row in range(1, rows + 1):
        for col in range(1, cols + 1):
            cell_ref = f"{get_column_letter(col)}{row}"
            cell_translations[(row, col)] = (f"T{row}_{col}", cell_ref)

    processor._apply_cell_translations_xlwings_batch(  # noqa: SLF001 (unit test)
        sheet, "Sheet1", cell_translations, FontManager("jp_to_en")
    )

    # For dense tables with no merged cells, operations should be range-based:
    # roughly two range calls per row (values + font), not per-cell.
    assert len(sheet.range_calls) <= rows * 2 + 2
    assert all((r1, c1) != (r2, c2) for (r1, c1, r2, c2) in sheet.range_calls)
