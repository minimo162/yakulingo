from __future__ import annotations

import numpy as np
import pytest

from yakulingo.processors import pdf_layout


@pytest.mark.unit
def test_detect_table_cells_parses_detresult_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeDetResult(dict):
        pass

    class FakeModel:
        def predict(self, table_img: object, threshold: float = 0.3):
            return [
                FakeDetResult(
                    {
                        "boxes": [
                            {"coordinate": [1, 2, 3, 4], "score": 0.9},
                        ]
                    }
                )
            ]

    monkeypatch.setattr(pdf_layout, "get_table_cell_model", lambda device="cpu": FakeModel())

    img = np.zeros((100, 100, 3), dtype=np.uint8)
    cells = pdf_layout.detect_table_cells(img, (10, 20, 50, 80), device="cpu", threshold=0.3)

    assert cells == [{"box": [11, 22, 13, 24], "score": 0.9}]
