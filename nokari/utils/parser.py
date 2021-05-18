from copy import deepcopy
from types import SimpleNamespace
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Coroutine,
    Dict,
    Final,
    List,
    Literal,
    Optional,
    Sequence,
    Tuple,
    TypedDict,
    Union,
)

from lightbulb.utils import find

from nokari.utils.view import StringView, UnexpectedQuoteError, _quotes

if TYPE_CHECKING:
    from nokari.core.context import Context

__all__: Final[List[str]] = [
    "ArgumentParser",
    "ArgumentOptions",
]


class Cursor:
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

    def finish(self) -> SimpleNamespace:
        params = self.parser.params
        data = self.data

        if self.parser._default_key is None:
            remainder = data.pop(None)
        else:
            remainder = data[self.parser._default_name]

        if isinstance(remainder, list):
            data["remainder"] = " ".join(remainder)

        for v in params.values():
            k = v["name"]
            is_flag = v.get("argmax", -1) == 0 if v else False
            val = data.pop(k, False if is_flag else None)

            if k is not None:
                k = k.replace("-", "_")
            if isinstance(val, list):
                data[k] = True if is_flag and val == [] else " ".join(val)
            else:
                data[k] = val

        return SimpleNamespace(**{k: v for k, v in data.items() if k is not None})


class ArgumentOptions(TypedDict, total=False):
    name: Optional[str]
    aliases: Sequence[str]
    argmax: int


class ArgumentParser:

    # pylint: disable=too-many-instance-attributes

    invalid_openings: ClassVar[Tuple[str, ...]] = tuple(f"{i}-" for i in _quotes)

    __slots__ = (
        "params",
        "force",
        "replace",
        "valid_names",
        "short_flags",
        "short_options",
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
        params: Dict[str, ArgumentOptions]
            A mapping from short flag to its options.
        force: bool
            If set to False, invalid flags/options will be remainder,
            otherwise they're ignored. Defaults to False.
        replace: bool
            If set to True, it'll replace the existing key,
            otherwise it'll get appended as remainder. Defaults to True
        append_remainder_to: Optional[str]
            Append the remainder to the set key. Defaults to None.
        """
        self.params = params
        self.force = force
        self.replace = replace
        self.valid_names = set()
        self.short_flags = set()
        self.short_options = set()
        self._default_key = append_remainder_to

        for k, v in self.params.items():
            if not v.get("name"):
                self.params[k]["name"] = k

            self.valid_names.add(v["name"])

            if not v.get("aliases"):
                self.params[k]["aliases"] = []

            for alias in self.params[k]["aliases"]:
                self.valid_names.add(alias)

            if k != v["name"]:
                if v.get("argmax") == 0:
                    self.short_flags.add(k)
                else:
                    self.short_options.add(k)

        self._default_name = (
            params[self._default_key]["name"] if self._default_key else None
        )

    def copy(self) -> "ArgumentParser":
        ret = self.__class__.__new__(self.__class__)
        for attr in self.__slots__:
            # technically we don't need to deepcopy strings, but w/e
            setattr(ret, attr, deepcopy(getattr(self, attr)))

        return ret

    # pylint: disable=too-many-branches,too-many-locals,too-many-nested-blocks
    def switch_cursor(
        self, cursor: Cursor, argument: str, *, allow_sf: bool = True
    ) -> bool:
        key = argument.lstrip("-").lower()
        data = cursor.data
        params = self.params
        names = self.valid_names
        temp_dict: Optional[ArgumentOptions] = ArgumentOptions(name=None)
        if argument[0] == "-" and argument[1] != "-":
            # it's a short flag / option
            if (temp_dict := params.get(key)) and temp_dict["name"] != key:
                # if it's a short flag, set it to True and return
                # otherwise, continue
                if temp_dict.get("argmax", -1) == 0:
                    data[temp_dict["name"]] = True
                    return False
            # if the short flag / option equals the long one, then it's invalid
            # since it's a long flag / option only, it should've started with double dash
            # so set the temp cursor to the remainder (None is remainder)
            elif temp_dict and temp_dict["name"] == key:
                temp_dict = ArgumentOptions(name=None)
            # it's a multiple short flags
            # or a short option but the argument sticks to the option,
            # e.g., -mnorizon instead of -m norizon
            elif allow_sf and find(
                self.short_flags | self.short_options, lambda i: i in argument
            ):
                argument = argument[1:]
                has_flags = False
                invalid_keys = set()
                for idx, iterable in enumerate((self.short_flags, self.short_options)):

                    # an option will only be valid if there's no flags
                    # so break it as it's a waste to iterate through the options if there's a flag
                    if idx == 1 and has_flags:
                        break

                    while argument and (
                        short_key := find(
                            iterable,
                            lambda i: i.startswith(argument[0])
                            and len(i) <= len(argument)
                            and i not in invalid_keys,
                        )
                    ):
                        invalid_keys.add(short_key)
                        name = params[short_key]["name"]
                        is_flag = params[short_key].get("argmax") == 0

                        if is_flag or not has_flags:
                            # only subtract the argument if it's a short flag
                            # or a valid option
                            argument = argument[len(short_key) :]

                        # it's a valid short flag
                        # continue to look for more short flags
                        if is_flag:
                            data[name] = True
                            has_flags = True
                            continue

                        # it's a valid short option
                        # append the argument and return
                        if not has_flags:
                            if isinstance((lst := data.get(name)), list):
                                lst.append(argument)
                            else:
                                data[name] = [argument]

                            return False

                        break

                # argument is exhausted. So, return
                if not argument:
                    return False

                # argument isn't exhausted
                # so, switch the temp cursor to the remainder
                temp_dict = ArgumentOptions(name=None)

        elif argument.startswith("--") and len(argument) > 2 and argument[2] != "-":
            if key in names:
                for v in params.values():
                    # it's a valid long key
                    if key == v["name"] or key in v["aliases"]:
                        temp_dict = v
                        break

        # no valid key was found
        # switch the temp cursor to the remainder!
        if temp_dict is None:
            temp_dict = ArgumentOptions(name=None)

        # no valid key was found and we want to append it to the remainder
        # or it's actually a valid key, but it's duplicated
        # and we want to append it to the remainder instead
        if (temp_dict["name"] is None and not self.force) or (
            (temp_dict["name"] in data and not self.replace)
        ):
            if isinstance((lst := data[self._default_name]), list):
                lst.append(argument)
            return False

        # set the current cursor and initialize the list
        cursor.current_dict, cursor.current_key = temp_dict, temp_dict["name"]
        if cursor.current_key != self._default_name:
            data[cursor.current_key] = []

        # return True to notify that we successfully switched the cursor
        return True

    def append(self, cursor: Cursor, argument: str) -> None:
        # append arguments to the current cursor
        max_length = cursor.current_dict.get("argmax", -1)
        data = cursor.data[cursor.current_key]
        if isinstance(data, list):
            data.append(argument)
            count = len(data)
            # if the current cursor can't receive more arguments
            # we set the current cursor to the remainder
            if max_length != -1 and count >= max_length:
                cursor.current_key = self._default_name

    def convert(
        self, ctx: "Context", argument: str
    ) -> Coroutine[Any, Any, SimpleNamespace]:
        return self.parse(argument)

    async def parse(self, argument: str) -> SimpleNamespace:
        """
        There's no reason for this method to be async.
        But it might be useful in the future.
        """
        cursor = Cursor(self, argument)
        view = cursor.view

        while not view.eof:
            # we only wanna skip space, not other whitespaces
            view.skip_char(" ")

            # we wanna skip it if it startswith "-
            # it'll be valid since we're gonna strip the quotes
            pass_ = view.buffer.startswith(self.invalid_openings)

            # no"rizon" by default is invalid
            # we're gonna make it valid here
            # it'll be parsed as norizon
            try:
                index = view.index
                argument = view.get_quoted_word() or ""
            except UnexpectedQuoteError:
                argument = view.buffer[index : view.index] + (
                    view.get_quoted_word() or ""
                )

            temp_argument = argument.strip()

            # it's not invalid openings
            # and at least is assumed as valid short key
            if (
                pass_ is False
                and temp_argument.startswith("-")
                and len(temp_argument) != 1
            ):
                # it's in --key=argument or -k=argument format
                if (
                    "=" in temp_argument
                    and (arguments := temp_argument.split("="))
                    and all(arguments)
                ):
                    key, *arguments = arguments
                    argument = "=".join(arguments)
                    if self.switch_cursor(cursor, key, allow_sf=False):
                        # the cursor isn't at remainder
                        # therefore, it's a valid key
                        # so, append the argument to the cursor
                        self.append(cursor, argument)
                        continue

                self.switch_cursor(cursor, temp_argument)
                continue

            # append the argument to the current cursor
            self.append(cursor, argument)

        return cursor.finish()
