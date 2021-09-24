"""The main entry of the program."""
import os
import sys
from pathlib import Path

if (nokari_path := str(Path(__file__).parent / "..")) not in sys.path:
    sys.path.insert(0, nokari_path)

# pylint: disable=wrong-import-position
from nokari.core import Nokari, constants
from nokari.utils import monkey_patch

if os.name != "nt":
    import uvloop  # pylint: disable=import-error

    uvloop.install()


if browser := constants.DISCORD_BROWSER:
    monkey_patch.set_browser(constants.DISCORD_BROWSER)

Nokari().run()
