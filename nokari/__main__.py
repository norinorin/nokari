"""The main entry of the program."""
import os

from dotenv import load_dotenv

from nokari.core import Nokari

if os.name != "nt":
    import uvloop  # pylint: disable=import-error

    uvloop.install()

load_dotenv()

if missing := [
    var for var in ("DISCORD_BOT_TOKEN", "POSTGRESQL_DSN") if var not in os.environ
]:
    raise RuntimeError(f"missing {', '.join(missing)} env variable{'s'*bool(missing)}")

if browser := os.getenv("DISCORD_BROWSER"):
    from nokari.utils.monkey_patch import set_browser

    set_browser(browser)


Nokari().run()
