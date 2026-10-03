"""Splitting a command into words — only when it is a simple command.

Shared by the "always allow" rules (approval_rules.py, #113) and plan mode's read-only list
(tools/readonly.py, #114). Both must reason about *one* command, so anything that composes,
redirects or expands — `;` `&` `|` backticks, `$`, `<` `>`, parentheses, braces, a backslash or
a line break — is not split at all: the caller treats it as "not covered".
"""
import shlex

SHELL_SYNTAX = frozenset(";&|`$<>(){}\\\n\r")


def simple_words(cmd) -> list[str] | None:
    """The command's words, or None when it is not a simple command (or not a string)."""
    if not isinstance(cmd, str) or any(c in SHELL_SYNTAX for c in cmd):
        return None
    try:
        words = shlex.split(cmd)
    except ValueError:
        return None
    return words or None
