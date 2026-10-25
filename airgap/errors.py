"""Errors that the CLI reports as a one-line message instead of a traceback."""


class AirgapError(Exception):
    """A problem the user can fix: bad config, missing URL or tool, ..."""
