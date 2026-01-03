from pydantic import BaseModel, Field
from konnektr_graph.types import BasicDigitalTwin, BasicRelationship


class DigitalTwinMetadata(BaseModel, extra="allow"):
    """Metadata for a digital twin."""

    model: str = Field(alias="$model")


class DigitalTwin(BaseModel, extra="allow"):
    """BasicDigitalTwin with extra properties allowed. Extra properties should align with DTDL model."""

    dtId: str = Field(alias="$dtId")
    metadata: DigitalTwinMetadata = Field(alias="$metadata")

    def to_dataclass(self):
        # Convert to dict with alias keys for BasicDigitalTwin.from_dict
        data = self.model_dump(by_alias=True, mode="json", exclude_none=True)
        return BasicDigitalTwin.from_dict(data)


class Relationship(BaseModel, extra="allow"):
    """BasicRelationship with extra properties allowed. Relationship name and extra properties should align with DTDL model."""

    relationshipId: str = Field(alias="$relationshipId")
    sourceId: str = Field(alias="$sourceId")
    targetId: str = Field(alias="$targetId")
    relationshipName: str = Field(alias="$relationshipName")

    def to_dataclass(self):
        data = self.model_dump(by_alias=True, mode="json", exclude_none=True)
        return BasicRelationship.from_dict(data)
