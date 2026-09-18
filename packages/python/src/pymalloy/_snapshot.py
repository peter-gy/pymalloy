from copy import deepcopy
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID

import msgspec

_SCALARS = (bytes, Decimal, date, datetime, time, timedelta, UUID)


def snapshot[T](value: T) -> T:
    """Copy value containers while retaining immutable Python scalar types."""
    try:
        return msgspec.to_builtins(value, builtin_types=_SCALARS)
    except TypeError:
        # Trait validation also reads unvalidated inputs, including arbitrary objects.
        return deepcopy(value)
