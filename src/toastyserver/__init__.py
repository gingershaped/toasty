from datetime import datetime, timedelta
from os import environ
from urllib.parse import urlencode, urljoin, urlsplit
from http.client import responses
from asyncio import wait_for
from string import printable

from quart import Quart, g, render_template, request, redirect, abort, flash, url_for
from quart_schema import QuartSchema
from werkzeug.exceptions import HTTPException
from sechat import Bot
from odmantic import AIOEngine
from motor.motor_asyncio import AsyncIOMotorClient
from aiohttp import ClientSession
from pydantic import ValidationError

from toastyserver.antifreezer import Antifreezer
from toastyserver.roommanager import RoomManager
from toastyserver.usermanager import UserManager
from toastyserver.jankapi import JankApi
from toastyserver.models import (
    Role,
    NewRoomForm,
    User,
    AntifreezeRoom,
    EditRoomForm,
    EditUserForm,
    AntifreezeResult,
    Server,
    DEFAULTMSG
)

antifreezer, bot = None, None
app = Quart(__name__, template_folder="../../templates", static_folder="../../static")
app.config.from_pyfile(environ["TOASTY_CONFIG"])
db = AIOEngine(
    AsyncIOMotorClient(app.config["MONGO_URI"]), app.config.get("DATABASE", "toasty")
)
usermanager = UserManager(db)
roommanager = RoomManager(db)
jankapi = JankApi(usermanager, roommanager)
app.register_blueprint(jankapi.blueprint)
QuartSchema(app, openapi_path=None)


@app.before_serving
async def start():
    global antifreezer, bot
    async with ClientSession() as session:
        async with session.get(
            "https://api.stackexchange.com/2.3/sites?{}".format(
                urlencode(
                    {
                        "filter": "!b1aoo7vBeKCks8",
                        "request_key": app.config["REQUEST_KEY"],
                    }
                )
            )
        ) as response:
            g.sitemap = {
                site["site_url"]: site["api_site_parameter"]
                for site in (await response.json())["items"]
            }
    bot = Bot(logger=app.logger.getChild("Bot"))
    await bot.authenticate(
        app.config["BOT_EMAIL"], app.config["BOT_PASSWORD"], app.config["BOT_HOST"]
    )
    antifreezer = Antifreezer(
        app.config, roommanager, bot, app.logger.getChild("Antifreezer")
    )
    await antifreezer.initialSchedule()


@app.after_serving
async def shutdown():
    assert antifreezer is not None
    assert bot is not None
    antifreezer.shutdown()
    await wait_for(bot.session.close(), 3)


@app.errorhandler(HTTPException)
@usermanager.provideUser
async def error(error, *, user):
    assert isinstance(error, HTTPException)
    assert error.code is not None
    return (
        await render_template(
            "error.html", code=error.code, message=responses[error.code], user=user
        ),
        error.code,
    )


@app.route("/")
@usermanager.provideUser
async def index(user):
    return await render_template("index.html", user=user, nrooms=await roommanager.db.count(AntifreezeRoom))

@app.route("/about")
@usermanager.provideUser
async def about(user):
    return await render_template("about.html", user=user)

@app.route("/auth/login")
@usermanager.provideUser
async def login(user):
    return await render_template(
        "login.html", user=user, redirect=request.args.get("redirect")
    )


@app.route("/auth/login/se")
async def seLogin():
    return redirect(
        "https://stackoverflow.com/oauth?{}".format(
            urlencode(
                {
                    "client_id": app.config["CLIENT_ID"],
                    "scope": "",
                    "redirect_uri": urljoin(
                        app.config["DOMAIN"], url_for("finalizeSeLogin")
                    ),
                    "state": request.args.get("redirect", ""),
                }
            )
        )
    )


@app.route("/auth/login/se/finalize")
async def finalizeSeLogin():
    if "code" not in request.args:
        abort(400)
    async with ClientSession() as session:
        async with session.post(
            "https://stackoverflow.com/oauth/access_token/json",
            data={
                "client_id": app.config["CLIENT_ID"],
                "client_secret": app.config["CLIENT_SECRET"],
                "code": request.args["code"],
                "redirect_uri": urljoin(
                    app.config["DOMAIN"], url_for("finalizeSeLogin")
                ),
            },
        ) as response:
            if response.status != 200:
                abort(400)
            token = (await response.json())["access_token"]
        async with session.get(
            "https://api.stackexchange.com/2.3/me/associated?{}".format(
                urlencode(
                    {
                        "types": "main_site",
                        "access_token": token,
                        "key": app.config["REQUEST_KEY"],
                        "page_size": 100,
                        "filter": "!nNPvSNPWJ9",
                    }
                )
            )
        ) as response:
            sites = (await response.json())["items"]
            userId = sites[0]["account_id"]
        async with session.get(
            "https://api.stackexchange.com/2.3/me?{}".format(
                urlencode(
                    {
                        "access_token": token,
                        "key": app.config["REQUEST_KEY"],
                        "filter": "!AhdF6aF0yuI-5W*KWVlNz",
                        "site": "meta"
                        if "https://meta.stackexchange.com"
                        in [site["site_url"] for site in sites]
                        else g.sitemap[
                            sorted(sites, key=lambda site: site["creation_date"])[0][
                                "site_url"
                            ]
                        ],
                    }
                )
            )
        ) as response:
            userName = (await response.json())["items"][0]["display_name"][:16]
        async with session.get(
            f"https://chat.stackexchange.com/account/{userId}", allow_redirects=False
        ) as response:
            if response.status != 302:
                await flash("Failed to create account: You do not have a chat account.")
                return redirect(url_for("index"))
            chatIdent = int(
                response.headers["location"].removeprefix("/").split("/")[1]
            )

    now = datetime.now()
    isModerator = any(site["user_type"] == "moderator" for site in sites)
    async with db.session() as session:
        if not await usermanager.userExists(userId, session):
            if not any(site["reputation"] >= 200 for site in sites):
                await flash(
                    "Failed to create account: Insufficient reputation!", "error"
                )
                return redirect(url_for("index"))
            await usermanager.saveUser(
                user := User(
                    ident=userId,
                    chatIdent=chatIdent,
                    name=userName,
                    role=Role.MODERATOR if isModerator else Role.USER,
                    created=now,
                ),
                session,
            )
            await flash("Account created!", "success")
        else:
            user = await usermanager.getUser(userId, session)
            assert user is not None
            await flash("Logged in successfully.", "success")
        token = await usermanager.issueToken(user, now, now + timedelta(30))

    response = redirect(
        url_for("index")
        if "state" not in request.args
        else urljoin(url_for("index"), urlsplit(request.args["state"]).path)
    )
    response.set_cookie("token", token.token, expires=token.expiry, secure=True)
    return response


@app.route("/auth/logout")
@usermanager.provideUser
async def logout(user):
    if user is None:
        return redirect(url_for("login"))
    await usermanager.revokeToken(request.cookies["token"])
    response = redirect(url_for("index"))
    response.delete_cookie("token")
    await flash("Logged out successfully.", "success")
    return response


@app.route("/rooms/")
@usermanager.requireUser()
async def myRooms(user):
    return await render_template(
        "rooms.html",
        rooms=[room async for room in roommanager.getRoomsOfUser(user)],
        title="My rooms",
        activePage="myRooms",
        showUsers=False,
        user=user,
    )


@app.route("/rooms/all/")
@usermanager.requireUser(Role.MODERATOR)
async def allRooms(user):
    rooms = []
    users: dict[int, User] = {}
    async with db.session() as session:
        async for room in roommanager.allRooms():
            if room.addedBy not in users:
                assert (
                    roomUser := await usermanager.getUser(room.addedBy, session)
                ) is not None
                users[room.addedBy] = roomUser
            rooms.append((room, users[room.addedBy]))
    return await render_template(
        "rooms.html",
        rooms=sorted(rooms, key=lambda r: r[0].name),
        title="All rooms",
        activePage="allRooms",
        showUsers=True,
        user=user,
    )


@app.route("/rooms/<int:roomId>/")
@usermanager.requireUser()
async def roomDetails(roomId: int, user: User):
    room = await roommanager.getRoom(roomId)
    if room is None:
        abort(404)
    if user.role < Role.MODERATOR and room.addedBy != user.ident:
        abort(403)
    if user.role >= Role.MODERATOR:
        addedBy = await usermanager.getUser(room.addedBy)
    else:
        addedBy = None
    return await render_template(
        "room-details.html",
        user=user,
        room=room,
        addedBy=addedBy,
        lastChecked=room.runs[0].ranAt if len(room.runs) else None,
        lastAntifreezed=i[0].ranAt
        if len(
            i := list(
                filter(
                    lambda run: run.result == AntifreezeResult.ANTIFREEZED, room.runs
                )
            )
        )
        else None,
        form={"message": room.message, "active": room.active, "locked": room.locked},
    )


@app.route("/rooms/<int:roomId>/edit", methods=["POST"])
@usermanager.requireUser(Role.USER)
async def editRoom(roomId: int, user: User):
    room = await roommanager.getRoom(roomId)
    if room is None:
        abort(404)
    try:
        form = EditRoomForm(**(await request.form))
    except ValidationError:
        abort(400)
    if user.role < Role.MODERATOR:
        if room.locked:
            abort(403)
        allowedRooms = [
            ident
            async for ident, name in jankapi.getUserOwnedRooms(user, room.server.value, False)
        ]
        if roomId not in allowedRooms:
            abort(403)
    if len(form.message) > 128:
        abort(400)
    form.message = "".join(char for char in form.message if char in printable).strip()
    if len(form.message) <= 0:
        form.message = DEFAULTMSG
    room.message = form.message
    room.active = form.active
    room.locked = form.locked
    await roommanager.saveRoom(room)
    await flash("Room edited.", "success")
    return redirect(url_for("myRooms"))


@app.route("/rooms/<int:roomId>/delete", methods=["POST"])
@usermanager.requireUser(Role.USER)
async def deleteRoom(roomId: int, user: User):
    assert antifreezer is not None
    room = await roommanager.getRoom(roomId)
    if room is None:
        abort(404)
    try:
        form = EditRoomForm(**(await request.form))
    except ValidationError:
        abort(400)
    if user.role < Role.MODERATOR:
        if room.locked:
            abort(403)
        allowedRooms = [
            ident
            async for ident, name in jankapi.getUserOwnedRooms(user, room.server.value, False)
        ]
        if roomId not in allowedRooms:
            abort(403)
    await roommanager.deleteRoom(room)
    antifreezer.removeAntifreeze(room.roomId)
    await flash("Room deleted.", "warning")
    return redirect(url_for("myRooms"))


@app.route("/rooms/<int:roomId>/forcecheck", methods=["POST"])
@usermanager.requireUser(Role.DEVELOPER)
async def forceCheck(user: User, roomId: int):
    assert antifreezer is not None
    await antifreezer.runAntifreeze(roomId)
    return "ok"


@app.route("/rooms/<int:roomId>/clearerrors", methods=["POST"])
@usermanager.requireUser()
async def clearErrors(user: User, roomId: int):
    room = await roommanager.getRoom(roomId)
    if room is None:
        abort(404)
    room.pendingErrors = 0
    await roommanager.saveRoom(room)
    return "ok"


@app.route("/rooms/new", methods=["GET", "POST"])
@usermanager.requireUser(Role.USER)
async def newRoom(user: User):
    assert antifreezer is not None
    if request.method == "GET":
        return await render_template("add-room.html", user=user)
    else:
        try:
            form = NewRoomForm(**(await request.form))
        except ValidationError:
            abort(400)
        if form.server != Server.SE:
            abort(400) # TODO
        if user.role < Role.MODERATOR:
            allowedRooms = [
                ident
                async for ident, name in jankapi.getUserOwnedRooms(
                    user, form.server.value
                )
            ]
            if form.room not in allowedRooms:
                abort(403)
        if len(form.message) > 128:
            abort(400)
        form.message = "".join(char for char in form.message if char in printable).strip()
        if len(form.message) <= 0:
            form.message = DEFAULTMSG
        if user.role < Role.MODERATOR:
            form.locked = False
        details = await jankapi.getRoomDetails(form.room, form.server.value)
        await roommanager.saveRoom(
            AntifreezeRoom(
                roomId=form.room,
                server=form.server,
                name=details.name,
                active=form.active,
                locked=form.locked,
                addedBy=user.ident,
                message=form.message,
            )
        )
        await antifreezer.runAntifreeze(form.room)
        antifreezer.scheduleAntifreeze(form.room)
        await flash("Room added!", "success")
        return redirect(url_for("roomDetails", roomId=form.room))


@app.route("/users/")
@usermanager.requireUser(Role.MODERATOR)
async def users(user: User):
    return await render_template(
        "users.html",
        users=[user async for user in await usermanager.allUsers()],
        user=user,
    )


@app.route("/users/<int:userId>/rooms")
@usermanager.requireUser()
async def roomsOfUser(userId: int, user: User):
    if userId == user.ident:
        return redirect(url_for("myRooms"))
    if user.role < Role.MODERATOR:
        abort(403)
    if (target := await usermanager.getUser(userId)) is None:
        abort(404)
    return await render_template(
        "rooms.html",
        rooms=[room async for room in roommanager.getRoomsOfUser(target)],
        title=f"Rooms of {target.name}",
        activePage="rooms",
        showUsers=False,
        user=user,
    )


@app.route("/users/<int:userId>/")
@usermanager.requireUser()
async def userSettings(userId: int, user: User):
    if user.role < Role.MODERATOR and userId != user.ident:
        abort(403)
    if userId == user.ident:
        return await render_template("user.html", target=user, user=user)
    else:
        if (target := await usermanager.getUser(userId)) is None:
            abort(404)
        return await render_template("user.html", target=target, user=user)


@app.route("/users/<int:userId>/edit", methods=["POST"])
@usermanager.requireUser()
async def editUser(userId: int, user: User):
    if userId != user.ident and user.role < Role.MODERATOR:
        abort(403)
    try:
        form = EditUserForm(**(await request.form))
    except ValidationError:
        abort(400)
    if userId != user.ident:
        target = await usermanager.getUser(userId)
        if target is None:
            abort(404)
    else:
        target = user
    if user.role < Role.MODERATOR and form.role != target.role:
        abort(403)
    if user.role < Role.DEVELOPER and form.role != target.role and form.role > Role.USER:
        abort(403)
    if user.role < Role.MODERATOR and form.role != target.role and form.role < Role.MODERATOR:
        abort(403)
    if user.role < target.role and userId != user.ident:
        abort(403)
    if len(form.username) > 16:
        abort(400)
    form.username = "".join(char for char in form.username if char in printable).strip()
    if len(form.username) <= 0:
        abort(400)
    target.role = form.role
    target.name = form.username
    await usermanager.saveUser(target)
    await flash("User saved.", "success")
    return redirect(url_for("userSettings", userId=userId))
