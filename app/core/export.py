import csv
import io
from collections.abc import Iterable, Sequence
from typing import Any

from fastapi import Response

FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _cell(value: Any) -> Any:
    # a food called "=HYPERLINK(...)" would run as a formula in excel
    if isinstance(value, str) and value.startswith(FORMULA_START):
        return "'" + value
    if value is None:
        return ""
    return value


def csv_response(filename: str, header: Sequence[str], rows: Iterable[Sequence[Any]]) -> Response:
    buffer = io.StringIO()
    # the BOM makes excel open it as utf-8, otherwise bangla names come out garbled
    buffer.write("﻿")
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows([_cell(value) for value in row] for row in rows)
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
