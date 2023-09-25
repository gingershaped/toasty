from typing import Optional
from datetime import datetime
from urllib.parse import urljoin

from odmantic import AIOEngine
from odmantic.session import AIOSession
from pytz import UTC
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.job import Job
from sechat import Bot
from sechat.errors import OperationFailedError
from quart import Config
from logging import Logger

from toastyserver.roommanager import RoomManager
from toastyserver.models import AntifreezeRun, AntifreezeResult, RoomDetails


class Antifreezer:
    def __init__(self, config: Config, manager: RoomManager, bot: Bot, logger: Logger):
        self.logger = logger
        self.config = config
        self.manager = manager
        self.bot = bot
        self.scheduler = AsyncIOScheduler(timezone=UTC)
        self.roomJobs: dict[int, Job] = {}

    async def initialSchedule(self):
        async for room in self.manager.allRooms():
            self.scheduleAntifreeze(room.roomId)
        self.scheduler.start()

    def shutdown(self):
        self.scheduler.shutdown()

    def scheduleAntifreeze(self, roomId: int):
        self.logger.info(f"Antifreeze scheduled for room {roomId}")
        self.roomJobs[roomId] = self.scheduler.add_job(
            self.runAntifreeze, "cron", (roomId,), hour=0, jitter=60 * 60
        )  # Antifreeze jobs will execute over a 3-hour time window

    def removeAntifreeze(self, roomId: int):
        self.logger.info(f"Antifreeze removed for room {roomId}")
        self.scheduler.remove_job(self.roomJobs[roomId].id)

    async def lastMessageInRoom(self, roomId: int) -> datetime:
        async with self.bot.session.post(
            f"https://chat.stackexchange.com/chats/{roomId}/events",
            data={"since": 0, "mode": "Messages", "msgCount": 1, "fkey": self.bot.fkey},
            headers={"Referer": "https://chat.stackexchange.com/rooms/{roomId}"},
        ) as response:
            event = (await response.json())["events"][0]
        return datetime.fromtimestamp(event["time_stamp"])

    async def getRoomDetails(self, ident: int, server: str) -> RoomDetails:
        async with self.bot.session.get(urljoin(server, f"/rooms/thumbs/{ident}")) as response:
                json = await response.json()
        return RoomDetails(
            ident=int(json["id"]),
            name=json["name"],
            description=json["description"]
        )

    async def runAntifreeze(self, roomId: int):
        logger = self.logger.getChild(str(roomId))
        logger.info(f"Checking {roomId}")
        async with self.manager.db.session() as session:
            room = await self.manager.getRoom(roomId)
            assert room is not None
            if not room.active:
                logger.info("Room is not active. Skipping.")
                return
            lastChecked = datetime.now()
            try:
                lastMessage = await self.lastMessageInRoom(room.roomId)
            except OperationFailedError as error:
                logger.warning(f"An error occured! {error.args}")
                if len(error.args) > 1:
                    message = error.args[1]
                else:
                    message = error.args[0]
                run = AntifreezeRun(
                    result=AntifreezeResult.ERROR,
                    ranAt=lastChecked,
                    mostRecentMessage=None,
                    error=message,
                )
                room.pendingErrors += 1
            else:
                details = await self.getRoomDetails(roomId, room.server)
                room.name = details.name
                logger.info(
                    f"Last sent message was at {lastMessage.strftime('%e %b %Y %H:%M:%S%p')}, which was {(lastChecked - lastMessage).days} days ago"
                )
                if not (delta := (lastChecked - lastMessage)).days >= int(
                    self.config["THRESHOLD"]
                ):
                    logger.info("Not antifreezing, below threshold.")
                    run = AntifreezeRun(
                        result=AntifreezeResult.OK,
                        ranAt=lastChecked,
                        mostRecentMessage=lastMessage,
                        error=None,
                    )
                else:
                    self.logger.info("Antifreezing room!")
                    chatRoom = await self.bot.joinRoom(room.roomId)
                    try:
                        await chatRoom.send(room.message.format(days=delta.days))
                    except OperationFailedError as error:
                        logger.warning(f"An error occured! {error.args}")
                        if len(error.args) > 1:
                            message = error.args[1]
                        else:
                            message = error.args[0]
                        run = AntifreezeRun(
                            result=AntifreezeResult.ERROR,
                            ranAt=lastChecked,
                            mostRecentMessage=None,
                            error=message,
                        )
                        room.pendingErrors += 1
                    else:
                        run = AntifreezeRun(
                            result=AntifreezeResult.ANTIFREEZED,
                            ranAt=lastChecked,
                            mostRecentMessage=lastMessage,
                            error=None,
                        )
                    finally:
                        self.bot.leaveRoom(roomId)
        room.runs.insert(0, run)
        if len(room.runs) > 32:
            room.runs = room.runs[:32]
        await self.manager.saveRoom(room)
        self.logger.info("Antifreeze completed.")
