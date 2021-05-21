import os
import pathlib
import subprocess
import sys
import typing


def install(*opts: str, package: str) -> None:
    subprocess.check_call([sys.executable, "-m", "pip", "install", *opts, package])


if __name__ == "__main__":
    HERE = pathlib.Path(__file__).parent
    deps = (HERE / "requirements.txt").read_text("utf-8").splitlines()
    dev_deps = (HERE / "requirements-dev.txt").read_text("utf-8").splitlines()

    for dep in [*deps, *dev_deps]:
        opts: typing.List[str] = []

        # omit env markers
        package, *_ = dep.partition(";")

        if package.startswith("#"):
            # skip comments
            continue

        if not package or package.isspace():
            # skip empty lines
            continue

        if os.name == "nt" and package == "uvloop":
            continue

        if package.startswith("git+"):
            opts.extend(["--exists-action", "w"])

            if "hikari-lightbulb" in package:
                # ignore dependencies
                # otherwise it'll take ages resolving non-existent version
                opts.append("--no-deps")

            opts.append("-e")

        install(*opts, package=package)
