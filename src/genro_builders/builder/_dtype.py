# Copyright 2026 Softwell S.r.l. - SPDX-License-Identifier: Apache-2.0
"""Keep the wire dtype identity and its value domain in loaded annotations."""
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
import math


@dataclass(frozen=True)
class _DType:
    code: str
    base: type

    def __call__(self, value):
        if self.base is float:
            valid = type(value) in (int, float) and (type(value) is int or math.isfinite(value))
        elif self.base is Decimal:
            valid = isinstance(value, Decimal) and value.is_finite()
        elif self.base in (str, int, bool, date, datetime, time, bytes, type(None)):
            valid = type(value) is self.base
        else:
            valid = isinstance(value, self.base)
        if not valid:
            raise ValueError(f"Invalid value for dtype {self.code!r}")
