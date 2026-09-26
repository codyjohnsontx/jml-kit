"""Command-line entry point for `jml`."""

import argparse
from importlib.metadata import version


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jml",
        description="Joiner-mover-leaver automation: people as code for Okta and GitHub.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {version('jml-kit')}")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    parser.print_help()
    return 0
