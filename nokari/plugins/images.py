import time
import typing
from io import BytesIO

import hikari
import lightbulb
from lightbulb import Bot, Context, plugins
from lightbulb.errors import ConverterFailure

from nokari import core, utils
from nokari.utils import converters
from nokari.utils.spotify import NoSpotifyPresenceError, SpotifyCardGenerator


class Images(plugins.Plugin):
    def __init__(self, bot: Bot) -> None:
        super().__init__()
        self.bot = bot
        self.spotify_card_generator = SpotifyCardGenerator(bot)
        self._spotify_card_argument_parser = utils.ArgumentParser(
            {
                "s": utils.ArgumentOptions(name="style", argmax=1),
                "h": utils.ArgumentOptions(name="hidden", argmax=0),
                "c": utils.ArgumentOptions(name="card", argmax=0),
                "t": utils.ArgumentOptions(name="time", argmax=0),
                "cl": utils.ArgumentOptions(name="colour", aliases=["color"], argmax=1),
            }
        )

    @core.commands.command()
    @core.cooldown(1, 2, lightbulb.cooldowns.UserBucket)
    async def spotify(
        self, ctx: Context, *, arguments: typing.Optional[str] = None
    ) -> None:
        args = await self._spotify_card_argument_parser.parse(arguments or "")
        if args.time:
            t0 = time.perf_counter()

        try:
            member = await converters.member_converter(
                converters.WrappedArg(args.remainder, ctx)
            )
        except ConverterFailure as e:
            # re-raise the error with a text
            raise ConverterFailure(f"Member {args.remainder!r} wasn't found...") from e

        if member.is_bot:
            return await ctx.respond("I won't make a card for bots >:(")

        style_map = {
            "dynamic": "1",
            "fixed": "2",
            **{s: s for n in range(1, 3) if (s := str(n))},
        }
        style = style_map.get(args.style, "2")

        try:
            async with self.bot.rest.trigger_typing(ctx.channel_id):
                with BytesIO() as fp:
                    await self.spotify_card_generator(
                        fp, member, args.hidden, args.colour, style
                    )

                    kwargs: typing.Dict[str, typing.Any] = {
                        "attachment": hikari.Bytes(fp, f"{member}-card.png")
                    }
                    if args.time:
                        kwargs[
                            "content"
                        ] = f"That took {(time.perf_counter() - t0) * 1000}ms!"

                    # if random.randint(0, 101) < 25:
                    #     kwargs["content"] = (
                    #         kwargs.get("content") or ""
                    #     ) + "\n\nHave you tried the slash version of this command?"

                    await ctx.respond(**kwargs)

        except NoSpotifyPresenceError:
            await ctx.respond(
                f"{'You' if member == ctx.author else 'They'} have no Spotify activity"
            )


def load(bot: Bot) -> None:
    bot.add_plugin(Images(bot))


def unload(bot: Bot) -> None:
    bot.remove_plugin("Images")
