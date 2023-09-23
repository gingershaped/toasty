from typing import Optional, Callable
from datetime import datetime
from secrets import token_urlsafe
from urllib.parse import urlencode
from functools import wraps

from quart import abort, request, redirect, url_for, current_app
from odmantic import AIOEngine
from odmantic.session import AIOSession

from toastyserver.models import User, Token, Role

class UserManager:
    def __init__(self, db: AIOEngine):
        self.db = db

    def requireUser(self, minRole: Role = Role.LOCKED):
        def decorator(function: Callable):
            @wraps(function)
            async def callable(*args, **kwargs):
                if "token" not in request.cookies:
                    return redirect(url_for("login") + "?" + urlencode({"redirect": request.path}))
                user, token = await self.getUserByToken(request.cookies["token"])
                if user is None:
                    return redirect(url_for("login") + "?" + urlencode({"redirect": request.path}))
                assert token is not None
                if datetime.now() > token.expiry:
                    await self.db.delete(token)
                    return redirect(url_for("login") + "?" + urlencode({"redirect": request.path}))
                if user.role.value < minRole.value:
                    abort(403)
                return await function(user=user, *args, **kwargs)
            return callable
        return decorator

    def provideUser(self, func: Callable):
        @wraps(func)
        async def decorator(*args, **kwargs):
            if "token" not in request.cookies:
                user = None
            else:
                user, token = await self.getUserByToken(request.cookies["token"])
                if token is not None and datetime.now() > token.expiry:
                    await self.db.delete(token)
                    return redirect(url_for("login?{}".format(urlencode({"redirect": request.path}))))
            return await current_app.ensure_async(func)(*args, user=user, **kwargs)
        return decorator
            
    async def allUsers(self):
        return self.db.find(User)

    async def userExists(self, ident: int, session: Optional[AIOSession] = None) -> bool:
        return True if (user := await self.db.find_one(User, User.ident == ident, session=session)) is not None else False

    async def saveUser(self, user: User, session: Optional[AIOSession] = None):
        await self.db.save(user, session=session)

    async def getUserByToken(self, token: str, session: Optional[AIOSession] = None) -> tuple[Optional[User], Optional[Token]]:
        if (tokenModel := (await self.db.find_one(Token, Token.token == token))) is None:
            return None, None
        return tokenModel.user, tokenModel

    async def getUser(self, ident: int, session: Optional[AIOSession] = None) -> Optional[User]:
        return await self.db.find_one(User, User.ident == ident)

    async def issueToken(self, user: User, now: datetime, expiry: datetime, session: Optional[AIOSession] = None) -> Token:
        token = Token(token=token_urlsafe(32), issued=now, expiry=expiry, user=user)
        await self.db.save(token, session=session)
        return token

    async def revokeToken(self, token: str):
        tokenModel = await self.db.find_one(Token, Token.token == token)
        assert tokenModel is not None
        await self.db.delete(tokenModel)