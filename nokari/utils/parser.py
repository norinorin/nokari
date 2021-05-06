from typing import (
    TYPE_CHECKING,
    Any,
    Coroutine,
    Dict,
    Final,
    List,
    Literal,
    Optional,
    Sequence,
    TypedDict,
    Union,
)

from nokari.utils.view import StringView, UnexpectedQuoteError

if TYPE_CHECKING:
    from nokari.core.context import Context

__all__: Final[List[str]] = [
    "Parsed",
    "ArgumentParser",
    "ArgumentOptions",
]


# pylint: disable=too-few-public-methods
class Parsed:
    def __init__(self, parser: "_Parser") -> None:
        data = parser.data
        _default_key = parser.parser._default_name
        data["remainder"] = data[_default_key]

        dash_keys = []
        for key in data:
            if key is None:
                continue

            if "-" in key:
                dash_keys.append(key)

        for key in dash_keys:
            data[key.replace("-", "_")] = data.pop(key)

        self.__dict__.update(**{k: v for k, v in data.items() if k is not None})

    def __repr__(self) -> str:
        attrs = " ".join(f"{k}={v!r}" for k, v in self.__dict__.items())
        return f"<{self.__class__.__name__} {attrs}>"

    def __getitem__(self, key: Any) -> Any:
        return self.__dict__[key]


# pylint: disable=too-few-public-methods
class _Parser:
    def __init__(self, parser: "ArgumentParser", argument: str):
        self.parser = parser
        self.view = StringView(argument or "")

        remainder_key = self.parser._default_key
        if remainder_key:
            self.current_dict = self.parser.params[remainder_key]
            self.current_key = self.parser._default_name
        else:
            self.current_key = None
            self.current_dict = {"name": None}

        self.data: Dict[Optional[str], Union[str, List[str], bool, Literal[None]]] = {
            self.current_key: []
        }

    def finish(self) -> Parsed:
        params = self.parser.params
        data = self.data

        if self.parser._default_key is None:
            remainder = data[None]
            if isinstance(remainder, list):
                data[None] = " ".join(remainder)

        for v in params.values():
            k = v["name"]
            if k is not None:
                k = k.replace("-", "_")
            is_flag = v.get("argmax", -1) == 0 if v else -1
            val = data.get(k, False if is_flag else None)
            if isinstance(val, list):
                data[k] = True if is_flag and val == [] else " ".join(val)
            else:
                data[k] = val

        return Parsed(self)


class ArgumentOptions(TypedDict, total=False):
    name: Optional[str]
    aliases: Sequence[str]
    argmax: int


class ArgumentParser:
    __slots__ = (
        "params",
        "force",
        "replace",
        "valid_names",
        "short_flags",
        "_default_key",
        "_default_name",
    )

    def __init__(
        self,
        params: Dict[str, ArgumentOptions],
        force: bool = False,
        replace: bool = True,
        append_remainder_to: Optional[str] = None,
    ):
        """
        Parameters
        ----------
        params: dict
            A mapping from short flag to its options.
        force: bool
            If set to False, invalid flags/options will be remainder,
            otherwise they're ignored. Defaults to False.
        replace: bool
            If set to True, it'll replace the existing key,
            otherwise it'll be remainder.
        append_remainder_to: Optional[str]
            Append the remainder to the set key. Defaults to None.
        """
        self.params = params
        self.force = force
        self.replace = replace
        self.valid_names = set()
        self.short_flags = set()
        self._default_key = append_remainder_to

        for k, v in self.params.items():
            if not v.get("name"):
                self.params[k]["name"] = k

            self.valid_names.add(v["name"])

            if not v.get("aliases"):
                self.params[k]["aliases"] = []

            for alias in self.params[k]["aliases"]:
                self.valid_names.add(alias)

            if v.get("argmax") == 0 and k != v["name"]:
                self.short_flags.add(k)

        self._default_name = (
            params[self._default_key]["name"] if self._default_key else None
        )

    # pylint: disable=too-many-branches
    def process_word(
        self, parser: _Parser, argument: str, *, allow_sf: bool = True
    ) -> bool:
        key = argument.lstrip("-").lower()
        data = parser.data
        params = self.params
        names = self.valid_names
        temp_dict: Optional[ArgumentOptions] = ArgumentOptions(name=None)
        if argument[0] == "-" and argument[1] != "-":
            if (
                (temp_dict := params.get(key))
                # case where we only want long flags
                and temp_dict["name"] != key
            ):
                if temp_dict.get("argmax", -1) == 0:
                    # return if it's just a flag
                    data[temp_dict["name"]] = True
                    return False
            elif temp_dict and temp_dict["name"] == key:
                temp_dict = dict(name=None)
            elif allow_sf and (joined_flags := self.short_flags & set(key)):
                for f in joined_flags:
                    argument = argument.replace(f, "")
                    data[params[f]["name"]] = True

                if argument == "-":
                    return False

                temp_dict = params.get(argument[1:])

        elif argument.startswith("--") and argument[2] != "-":
            if key in names:
                for _, v in params.items():
                    if key == v["name"] or key in v["aliases"]:
                        temp_dict = v
                        break

        if temp_dict is None:
            temp_dict = ArgumentOptions(name=None)

        if (temp_dict["name"] is None and not self.force) or (
            (temp_dict["name"] in data and not self.replace)
            and (lst := data[self._default_name])
        ):
            if isinstance(lst, list):
                lst.append(argument)
            return False

        parser.current_dict, parser.current_key = temp_dict, temp_dict["name"]
        if parser.current_key != self._default_name:
            data[parser.current_key] = []

        return True

    def append(self, parser: _Parser, argument: str) -> None:
        max_length = parser.current_dict.get("argmax", -1)
        data = parser.data[parser.current_key]
        if isinstance(data, list):
            data.append(argument)
            count = len(data)
            if max_length != -1 and count >= max_length:
                parser.current_key = self._default_name

    def convert(self, ctx: "Context", argument: str) -> Coroutine[Any, Any, Parsed]:
        return self.parse(argument)

    async def parse(self, argument: str) -> Parsed:
        """
        There's no reason for this method to be async.
        But it might be useful in the future.
        """
        parser = _Parser(self, argument)
        view = parser.view

        while not view.eof:
            view.skip_char(" ")

            pass_ = view.buffer[view.index : view.index + 2] == '"-'

            try:
                index = view.index
                argument = view.get_quoted_word() or ""
            except UnexpectedQuoteError:
                argument = view.buffer[index : view.index] + (
                    view.get_quoted_word() or ""
                )

            temp_argument = argument.strip()

            if (
                pass_ is False
                and temp_argument.startswith("-")
                and len(temp_argument) != 1
            ):
                if (
                    "=" in temp_argument
                    and (arguments := temp_argument.split("="))
                    and all(arguments)
                ):
                    key, *arguments = arguments
                    argument = "=".join(arguments)
                    if self.process_word(parser, key, allow_sf=False):
                        self.append(parser, argument)
                        continue

                self.process_word(parser, temp_argument)
                continue

            self.append(parser, argument)

        return parser.finish()
