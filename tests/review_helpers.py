"""Synthetic observation fixtures shared by report tests."""

import csv
import io
import json

from review_observations import paired, series


def paired_rows(groups, control, candidate):
    """Convenience for tests starting with parsed rows, not dataset series."""
    return paired({name: series(rows) for name, rows in groups.items()}, control, candidate)


def sample(configuration, block, wall_s=1, **overrides):
    row = dict(configuration=configuration, block=str(block), phase="measured",
               outcome="completed", wall_s=wall_s, exit_status=0,
               validated=True, included=True, exclude_reason="")
    row.update(overrides)
    row["id"] = overrides.get("id", f'{row["phase"]}/{block}/{configuration}')
    if "elapsed_ns" in overrides:
        row.pop("wall_s")
    return row


def jsonl(rows):
    return b"".join((json.dumps(row) + "\n").encode() for row in rows)


def csv_bytes(rows):
    fields = list(dict.fromkeys(k for row in rows for k in row))
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: str(v).lower() if type(v) is bool else v for k, v in row.items()})
    return stream.getvalue().encode()
