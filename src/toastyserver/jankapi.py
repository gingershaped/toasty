from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag
from aiohttp import ClientSession, CookieJar
from quart import Blueprint, abort
from quart_schema import (
    validate_request,
    validate_response,
    RequestSchemaValidationError,
    DataSource,
)

from toastyserver.models import (
    RoomListRequest,
    RoomListResponse,
    MiniRoom,
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
        self.blueprint.errorhandler(RequestSchemaValidationError)(
            self.handleValidationError
        )
        self.blueprint.route("/ownedrooms", ["POST"])(
            self.usermanager.requireUser(Role.USER)(self.userOwnedRoomsEndpoint)
        )

    async def handleValidationError(self, error):
        if isinstance(error.validation_error, TypeError):
            return {
                "errors": str(error.validation_error),
            }, 400
        else:
            return {
                "errors": error.validation_error.json(),
            }, 400

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
                soup = BeautifulSoup(await response.read(), features="html.parser")
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

    async def getRoomDetails(self, ident: int, server: str) -> RoomDetails:
        async with ClientSession() as session:
            async with session.get(urljoin(server, f"/rooms/info/{ident}")) as response:
                soup = BeautifulSoup(await response.read(), features="html.parser")
        assert isinstance(card := soup.find(class_="roomcard-xxl"), Tag)
        assert isinstance(header := card.find("h1"), Tag)
        assert isinstance(description := card.find("p"), Tag)
        return RoomDetails(
            ident, header.text.strip(), "\n".join(description.stripped_strings)
        )

    @validate_request(RoomListRequest)
    @validate_response(RoomListResponse)
    async def userOwnedRoomsEndpoint(self, user: User, data: RoomListRequest):
        return RoomListResponse(
            [
                MiniRoom(ident, name)
                async for ident, name in self.getUserOwnedRooms(user, data.server.value)
            ]
        )
