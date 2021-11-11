"""Re-export things."""
from functools import partial

from lightbulb import add_checks, implements, option
from lightbulb.commands import OptionModifier

from .bot import *
from .cache import *
from .commands import *
from .context import *
from .cooldowns import *

greedy_option = partial(option, modifier=OptionModifier.GREEDY)
consume_rest_option = partial(option, modifier=OptionModifier.CONSUME_REST)
