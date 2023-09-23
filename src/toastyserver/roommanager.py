from typing import Optional

from odmantic import AIOEngine
from odmantic.session import AIOSession

from toastyserver.models import AntifreezeRoom, User

class RoomManager:
    def __init__(self, db: AIOEngine):
        self.db = db

    def allRooms(self, session: Optional[AIOSession] = None):
        return self.db.find(AntifreezeRoom)

    async def getRoom(self, roomId: int, session: Optional[AIOSession] = None):
        return await self.db.find_one(AntifreezeRoom, AntifreezeRoom.roomId == roomId, session=session)

    async def deleteRoom(self, room: AntifreezeRoom, session: Optional[AIOSession] = None):
        await self.db.delete(room, session=session)

    async def saveRoom(self, room: AntifreezeRoom, session: Optional[AIOSession] = None):
        await self.db.save(room, session=session)

    def getRoomsOfUser(self, user: User, session: Optional[AIOSession] = None):
        return self.db.find(AntifreezeRoom, AntifreezeRoom.addedBy == user.ident, session=session)