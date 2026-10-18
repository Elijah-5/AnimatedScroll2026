from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from .agent import Unit, Character, Scene

class Entity(BaseModel):
    id: str = Field(min_length=1)

class Source(Entity):
    model_config = ConfigDict(extra='allow')
    title: str
    citation: str = ''
    location: str = ''
    text: str
    version: int = Field(ge=1)

class SavedCharacter(Character, Entity):
    confirmed: bool = False

class SavedUnit(Unit, Entity):
    status: Literal['pending','approved','rejected'] = 'pending'
    locked: bool = False

class SavedScene(Scene, Entity):
    units: list[SavedUnit] = Field(default_factory=list)

class Annotation(Entity):
    model_config = ConfigDict(extra='allow')
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)
    description: str
    kind: Literal['scene','character'] = 'scene'
    characterId: str = ''
    confirmed: bool = False

class Check(Entity):
    message: str
    resolved: bool = False

class Intent(BaseModel):
    theme: str = ''
    audience: str = ''
    tone: str = ''
    goal: str = ''
    fixed: str = ''
    allowed: str = ''
    forbidden: str = ''

class MaterialInputs(BaseModel):
    background: str = ''
    relationships: str = ''
    narrative: str = ''
    version: int = Field(default=1,ge=1)

class Project(Entity):
    model_config = ConfigDict(extra='allow')
    version: int = Field(ge=1)
    materialInputs: MaterialInputs = Field(default_factory=MaterialInputs)
    materialSegments: list[dict] = Field(default_factory=list)
    materialAnalysis: dict = Field(default_factory=dict)
    sceneCount: int = Field(default=3, ge=1, le=12)
    imageVersion: int = 0
    documents: list[dict] = Field(default_factory=list)
    observations: list[dict] = Field(default_factory=list)
    matches: list[dict] = Field(default_factory=list)
    title: str
    sources: list[Source]
    characters: list[SavedCharacter]
    annotations: list[Annotation]
    image: str = ''
    intent: Intent
    scenes: list[SavedScene]
    outlineConfirmed: bool = False
    checks: list[Check]
