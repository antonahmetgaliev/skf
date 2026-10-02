from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


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
