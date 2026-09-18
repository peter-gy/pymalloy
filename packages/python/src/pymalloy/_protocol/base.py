from typing import dataclass_transform

from msgspec import Struct, field


@dataclass_transform(
    frozen_default=True, kw_only_default=True, field_specifiers=(field,)
)
class Record(Struct, frozen=True, forbid_unknown_fields=True, kw_only=True):
    """Immutable protocol records with strict field validation."""
