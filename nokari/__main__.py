"""The main entry of the program"""

import asyncio
import os

from dotenv import load_dotenv

from nokari.core import Nokari

if os.name != "nt":
    import uvloop  # pylint: disable=import-error

    uvloop.install()
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

load_dotenv()

if "DISCORD_BOT_TOKEN" not in os.environ:
    raise RuntimeError("DISCORD_BOT_TOKEN env variable must be set.")

Nokari().run()
