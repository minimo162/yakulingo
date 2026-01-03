from __future__ import annotations

import pytest

from yakulingo.processors.excel_processor import ExcelProcessor


class _FakeDim:
    def __init__(self, count: int | None, *, raises: bool = False) -> None:
        self._count = count
        self._raises = raises

    @property
    def count(self) -> int:  # noqa: D401
        if self._raises:
            raise RuntimeError("count unavailable")
        if self._count is None:
            raise RuntimeError("count not set")
        return self._count


class _FakeApiDim:
    def __init__(self, count: int | None, *, raises: bool = False) -> None:
        self._count = count
        self._raises = raises

    @property
    def Count(self) -> int:  # noqa: N802 (Excel API style)
        if self._raises:
            raise RuntimeError("Count unavailable")
        if self._count is None:
            raise RuntimeError("Count not set")
        return self._count


class _FakeApi:
    def __init__(
        self,
        rows_count: int | None,
        cols_count: int | None,
        *,
        raises: bool = False,
        address: str | None = None,
        address_raises: bool = False,
    ) -> None:
        self.Rows = _FakeApiDim(rows_count, raises=raises)
        self.Columns = _FakeApiDim(cols_count, raises=raises)
        self._address = address
        self._address_raises = address_raises

    @property
    def Address(self) -> str | None:  # noqa: N802 (Excel API style)
        if self._address_raises:
            raise RuntimeError("Address unavailable")
        return self._address


class _FakeOptionsResult:
    def __init__(self, value):  # noqa: ANN001
        self.value = value


class _FakeUsedRange:
    def __init__(
        self,
        *,
        value,  # noqa: ANN001
        options_value=None,  # noqa: ANN001
        options_raises: bool = False,
        rows_count: int | None = None,
        cols_count: int | None = None,
        rows_raises: bool = False,
        cols_raises: bool = False,
        api_rows_count: int | None = None,
        api_cols_count: int | None = None,
        api_raises: bool = False,
        address: str | None = None,
        address_raises: bool = False,
        api_address: str | None = None,
        api_address_raises: bool = False,
    ) -> None:
        self.value = value
        self._options_value = options_value
        self._options_raises = options_raises
        self.rows = _FakeDim(rows_count, raises=rows_raises)
        self.columns = _FakeDim(cols_count, raises=cols_raises)
        self._address = address
        self._address_raises = address_raises
        self.api = _FakeApi(
            api_rows_count,
            api_cols_count,
            raises=api_raises,
            address=api_address,
            address_raises=api_address_raises,
        )

    @property
    def address(self) -> str | None:
        if self._address_raises:
            raise RuntimeError("address unavailable")
        return self._address

    def options(self, ndim: int = 2):  # noqa: ANN001
        if self._options_raises:
            raise RuntimeError("options unavailable")
        return _FakeOptionsResult(self._options_value if self._options_value is not None else self.value)


@pytest.mark.unit
def test_read_used_range_values_2d_prefers_ndim2() -> None:
    processor = ExcelProcessor()
    used_range = _FakeUsedRange(value=[1, 2, 3], options_value=[[1], [2], [3]])
    assert processor._read_used_range_values_2d(used_range) == [[1], [2], [3]]  # noqa: SLF001


@pytest.mark.unit
def test_read_used_range_values_2d_fallback_1d_single_column() -> None:
    processor = ExcelProcessor()
    used_range = _FakeUsedRange(
        value=[1, 2, 3],
        options_raises=True,
        rows_count=3,
        cols_count=1,
    )
    assert processor._read_used_range_values_2d(used_range) == [[1], [2], [3]]  # noqa: SLF001


@pytest.mark.unit
def test_read_used_range_values_2d_fallback_1d_single_row_via_api() -> None:
    processor = ExcelProcessor()
    used_range = _FakeUsedRange(
        value=[1, 2, 3],
        options_raises=True,
        rows_raises=True,
        cols_raises=True,
        api_rows_count=1,
        api_cols_count=3,
    )
    assert processor._read_used_range_values_2d(used_range) == [[1, 2, 3]]  # noqa: SLF001


@pytest.mark.unit
def test_read_used_range_values_2d_fallback_1d_unknown_defaults_to_column() -> None:
    processor = ExcelProcessor()
    used_range = _FakeUsedRange(
        value=[1, 2, 3],
        options_raises=True,
        rows_raises=True,
        cols_raises=True,
        api_raises=True,
    )
    assert processor._read_used_range_values_2d(used_range) == [[1], [2], [3]]  # noqa: SLF001


@pytest.mark.unit
def test_read_used_range_values_2d_scalar() -> None:
    processor = ExcelProcessor()
    used_range = _FakeUsedRange(value="x", options_raises=True, api_raises=True, rows_raises=True, cols_raises=True)
    assert processor._read_used_range_values_2d(used_range) == [["x"]]  # noqa: SLF001


@pytest.mark.unit
def test_read_used_range_values_2d_fallback_address_single_row() -> None:
    processor = ExcelProcessor()
    used_range = _FakeUsedRange(
        value=[1, 2, 3],
        options_raises=True,
        rows_raises=True,
        cols_raises=True,
        api_raises=True,
        address="$A$1:$C$1",
    )
    assert processor._read_used_range_values_2d(used_range) == [[1, 2, 3]]  # noqa: SLF001


@pytest.mark.unit
def test_read_used_range_values_2d_fallback_address_single_column() -> None:
    processor = ExcelProcessor()
    used_range = _FakeUsedRange(
        value=[1, 2, 3],
        options_raises=True,
        rows_raises=True,
        cols_raises=True,
        api_raises=True,
        address="Sheet1!$B$2:$B$4",
    )
    assert processor._read_used_range_values_2d(used_range) == [[1], [2], [3]]  # noqa: SLF001
