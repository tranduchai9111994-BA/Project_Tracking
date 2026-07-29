"""Task 19: unit test cho analyzer/palette.py."""
from analyzer.palette import (
    progress_color, status_color, categorical_colors, diverging_color,
    PROGRESS_TIERED, STATUS, CATEGORICAL,
)


class TestProgressColor:
    def test_low(self):
        assert progress_color(0) == PROGRESS_TIERED["low"]
        assert progress_color(29.9) == PROGRESS_TIERED["low"]

    def test_mid(self):
        assert progress_color(30) == PROGRESS_TIERED["mid"]
        assert progress_color(69.9) == PROGRESS_TIERED["mid"]

    def test_high(self):
        assert progress_color(70) == PROGRESS_TIERED["high"]
        assert progress_color(100) == PROGRESS_TIERED["high"]

    def test_custom_thresholds(self):
        # Override threshold: (50, 90) → 30 giờ low, 60 mid, 95 high
        assert progress_color(30, thresholds=(50, 90)) == PROGRESS_TIERED["low"]
        assert progress_color(60, thresholds=(50, 90)) == PROGRESS_TIERED["mid"]
        assert progress_color(95, thresholds=(50, 90)) == PROGRESS_TIERED["high"]

    def test_dark_mode(self):
        light = progress_color(50)
        dark = progress_color(50, dark=True)
        assert light != dark   # dark variant khác light


class TestStatusColor:
    def test_known(self):
        assert status_color("Closed") == STATUS["Closed"]
        assert status_color("In-progress") == STATUS["In-progress"]
        assert status_color("Overdue") == STATUS["Overdue"]

    def test_unknown_fallback(self):
        # Không match → dùng Open
        assert status_color("Xyz") == STATUS["Open"]
        assert status_color("") == STATUS["Open"]
        assert status_color(None) == STATUS["Open"]


class TestCategorical:
    def test_length(self):
        assert len(categorical_colors(5)) == 5
        assert len(categorical_colors(10)) == 10

    def test_cycle(self):
        # n > len(CATEGORICAL) → cycle
        assert len(categorical_colors(15)) == 15
        colors = categorical_colors(15)
        assert colors[0] == colors[10]  # cycle back to index 0
        assert colors[1] == colors[11]

    def test_zero(self):
        assert categorical_colors(0) == []


class TestDiverging:
    def test_zero(self):
        # value=0 → zero color
        from analyzer.palette import DIVERGING
        assert diverging_color(0, -100, 100) == DIVERGING["zero"]

    def test_negative(self):
        from analyzer.palette import DIVERGING
        # -100 (min) → neg_strong; -10 (mild) → neg_mid
        assert diverging_color(-100, -100, 100) == DIVERGING["neg_strong"]
        assert diverging_color(-10, -100, 100) == DIVERGING["neg_mid"]

    def test_positive(self):
        from analyzer.palette import DIVERGING
        assert diverging_color(100, -100, 100) == DIVERGING["pos_strong"]
        assert diverging_color(10, -100, 100) == DIVERGING["pos_mid"]
