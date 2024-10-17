from typing import Optional
from datetime import datetime
from enum import IntEnum
from dataclasses import dataclass
from sechat import Server

from odmantic import Model, EmbeddedModel, Field, Reference
from pydantic import BaseModel, Field as PDField

DEFAULTMSG = "Toasty Antifreeze triggered! Last message was sent {days} days ago."


class Role(IntEnum):
    LOCKED = 0
    USER = 1
    MODERATOR = 2
    DEVELOPER = 3


class User(Model):
    ident: int = Field(primary_field=True)
    chatIdent: int
    name: str
    role: Role = Role.USER
    created: datetime


class Token(Model):
    token: str = Field(primary_field=True)
    issued: datetime
    expiry: datetime
    user: User = Reference()


class AntifreezeResult(IntEnum):
    OK = 0
    ANTIFREEZED = 1
    ERROR = 2


class AntifreezeRun(EmbeddedModel):
    result: AntifreezeResult
    ranAt: datetime
    mostRecentMessage: Optional[datetime]
    error: Optional[str]


class AntifreezeRoom(Model):
    roomId: int = Field(primary_field=True)
    server: Server
    name: str
    active: bool = True
    locked: bool = False
    pendingErrors: int = 0
    message: str = DEFAULTMSG
    runs: list[AntifreezeRun] = []
    owners: list[int] = []
    addedBy: int  # Why isn't this a reference? Becase odmantic doesn't support querying across references for SOME REASON


# forms
class NewRoomForm(BaseModel):
    server: Server
    room: int = PDField(alias="room-id")
    message: str
    active: bool = False
    locked: bool = False


class EditRoomForm(BaseModel):
    room: int = PDField(alias="room-id")
    message: str
    active: bool = False
    locked: bool = False


class EditUserForm(BaseModel):
    username: str
    role: Role


# other stuff
@dataclass
class RoomDetails:
    ident: int
    name: str
    description: str
