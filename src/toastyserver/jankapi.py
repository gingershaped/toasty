from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag
from aiohttp import ClientSession, CookieJar
from quart import Blueprint, abort, request
from sechat import Server

from toastyserver.models import (
    User,
    Role,
    RoomDetails,
)
from toastyserver.usermanager import UserManager
from toastyserver.roommanager import RoomManager


class JankApi:
    def __init__(self, usermanager: UserManager, roommanager: RoomManager):
        self.usermanager = usermanager
        self.roommanager = roommanager
        self.blueprint = Blueprint("jankapi", __name__, url_prefix="/jankapi")
        self.blueprint.route("/ownedrooms", methods=["POST"])(
            self.usermanager.requireUser(Role.USER)(self.userOwnedRoomsEndpoint)
        )

    async def getUserOwnedRooms(
        self, user: User, server: str, excludeExisting: bool = True
    ):
        addedRooms = [
            room.roomId async for room in self.roommanager.getRoomsOfUser(user)
        ]
        async with ClientSession() as session:
            async with session.get(
                urljoin(server, f"/account/{user.ident}")
            ) as response:
                soup = BeautifulSoup(await response.read(), features="lxml")
        assert isinstance(cards := soup.find(id="user-owningcards"), Tag | None)
        if cards is None:
            return
        for tag in cards.find_all(class_="roomcard"):
            if not isinstance(tag, Tag):
                continue
            if "frozen" in tag.get_attribute_list("class"):
                continue
            assert isinstance(name := tag.find("span", class_="room-name"), Tag)
            ident = int(tag.attrs["id"].removeprefix("room-"))
            if (ident in addedRooms) and excludeExisting:
                continue
            yield ident, name.attrs["title"]

    async def userOwnedRoomsEndpoint(self, user: User):
        server = Server((await request.json)["server"])
        return {"rooms": [{"ident": ident, "name": name} async for ident, name in self.getUserOwnedRooms(user, server.value)]}
