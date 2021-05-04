import asyncio
import os

import hikari
from dotenv import load_dotenv

from nokari.core import Nokari

if os.name != "nt":
    import uvloop

    uvloop.install()
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

load_dotenv()

if "DISCORD_BOT_TOKEN" not in os.environ:
    raise RuntimeError("DISCORD_BOT_TOKEN env variable must be set.")

Nokari().run()
