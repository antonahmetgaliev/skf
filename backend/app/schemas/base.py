from __future__ import annotations

from typing import Annotated, Any, TypeVar

from pydantic import BaseModel, BeforeValidator, ConfigDict, WithJsonSchema
from pydantic.alias_generators import to_camel
from pydantic.json_schema import SkipJsonSchema

T = TypeVar("T")


def _reject_null(value: Any) -> Any:
    if value is None:
        raise ValueError("may be omitted, but not null")
    return value


# A PATCH field that cannot be cleared: leave it out to keep the value, but an
# explicit ``null`` is an error. Declare it as ``name: Omittable[str] = None``,
# with any constraints inside (``Omittable[Annotated[str, Field(...)]]``).
# Fields that *can* be cleared stay ``T | None = None``.
Omittable = Annotated[T | SkipJsonSchema[None], BeforeValidator(_reject_null)]

# ISO 8601 date-time strings passed through from SimGrid and YouTube. Kept as
# ``str`` so an upstream value is never re-formatted or rejected on the way out.
IsoDateTime = Annotated[str, WithJsonSchema({"type": "string", "format": "date-time"})]

# An absolute URL in a response.
Url = Annotated[str, WithJsonSchema({"type": "string", "format": "uri"})]

# For optional response fields whose source says "no value" with an empty string.
BlankAsNone = BeforeValidator(lambda value: value or None)


class CamelModel(BaseModel):
    """Base model for every API schema: camelCase on the wire."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        # Responses always carry defaulted fields, so the OpenAPI output
        # schema (and the generated TS types) mark them required.
        json_schema_serialization_defaults_required=True,
    )

    def model_dump(self, **kwargs):  # type: ignore[override]
        kwargs.setdefault("by_alias", True)
        return super().model_dump(**kwargs)


class OrmCamelModel(CamelModel):
    model_config = ConfigDict(from_attributes=True)
