"""Consistent display units without changing the recorded numerical model."""


def time_unit(values):
    """Choose one unit for a table or axis, not independently for each cell."""
    largest = max((abs(v) for v in values if v is not None), default=0)
    if largest == 0 or largest >= 1:
        return 1, "s"
    if largest >= .001:
        return 1_000, "ms"
    if largest >= .000001:
        return 1_000_000, "µs"
    return 1_000_000_000, "ns"


def number(value, scale=1, signed=False):
    if value is None:
        return "—"
    # Significant digits retain small nonzero spreads even beside large medians.
    return format(value * scale, "+.4g" if signed else ".4g")


def duration(value):
    if value is None:
        return "—"
    scale, unit = time_unit([value])
    return f"{number(value, scale)} {unit}"
