"""
REPL input classification.

Free text is never interpreted by its first word. Something only becomes a command when it
starts with "/", when the whole input is exactly a harmless bare keyword ("help", "exit"),
or — while a job is waiting at a gate — when the whole input is exactly a gate shortcut.
"""

from dataclasses import dataclass
from enum import Enum


class InputKind(str, Enum):
    EMPTY = "EMPTY"
    COMMAND = "COMMAND"
    ISSUE = "ISSUE"


@dataclass(frozen=True)
class ParsedInput:
    kind: InputKind
    command: str = ""  # e.g. "/approve"
    arg: str = ""


# Whole-input keywords that are always safe: they read state or leave the shell.
BARE_COMMANDS = {
    "help": "/help",
    "status": "/status",
    "diff": "/diff",
    "jobs": "/jobs",
    "clear": "/clear",
    "exit": "/exit",
    "quit": "/quit",
}

# Whole-input shortcuts that act on a job; honoured only while a gate is pending.
GATE_SHORTCUTS = {
    "a": "/approve",
    "approve": "/approve",
    "p": "/publish",
    "publish": "/publish",
    "r": "/reject",
    "reject": "/reject",
    "d": "/diff",
}


def parse_input(raw: str, gate_pending: bool) -> ParsedInput:
    """Classifies one line of REPL input as a command, an issue description, or nothing."""
    text = raw.strip()
    if not text:
        return ParsedInput(InputKind.EMPTY)

    if text.startswith("/"):
        head, _, arg = text.partition(" ")
        return ParsedInput(InputKind.COMMAND, head.lower(), arg.strip())

    word = text.lower()
    if word in BARE_COMMANDS:
        return ParsedInput(InputKind.COMMAND, BARE_COMMANDS[word])
    if gate_pending and word in GATE_SHORTCUTS:
        return ParsedInput(InputKind.COMMAND, GATE_SHORTCUTS[word])

    return ParsedInput(InputKind.ISSUE, arg=text)
