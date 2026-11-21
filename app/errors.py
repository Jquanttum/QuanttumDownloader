"""User-friendly error translation for yt-dlp and network failures."""

from __future__ import annotations

import logging

log = logging.getLogger("quanttum.errors")


class AppError(Exception):
    """An error whose message is already written for end users."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class MissingFFmpegError(AppError):
    """FFmpeg is required for the requested operation but was not found."""

    def __init__(self) -> None:
        super().__init__(
            "FFmpeg wasn't found, and it's needed to convert audio. "
            "Install it or set its location in Settings, then try again."
        )


class DiskSpaceError(AppError):
    """Not enough free space in the download folder."""

    def __init__(self) -> None:
        super().__init__("There isn't enough free disk space in the download folder. Free some space and retry.")


class OutputFolderError(AppError):
    """The download folder cannot be created or written to."""


class DownloadCancelled(Exception):
    """Raised inside a worker when the user paused or cancelled the download."""

    def __init__(self) -> None:
        super().__init__("cancelled")
        self.partials: list[str] = []

# (substrings to look for in lower-cased message, friendly text)
_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("private video", "this video is private"),
     "This video is private. Only its owner can access it."),
    (("confirm your age", "age-restricted", "age restricted", "inappropriate for some users"),
     "This video is age-restricted and can't be accessed without signing in."),
    (("sign in to confirm", "not a bot", "login required", "log in to"),
     "This site is asking for a sign-in before it will serve this media."),
    (("members-only", "members only", "join this channel"),
     "This video is for channel members only."),
    (("video unavailable", "this video is unavailable", "has been removed", "no longer available",
      "account associated with this video has been terminated"),
     "This video is unavailable. It may have been removed or made private."),
    (("not available in your country", "blocked it in your country", "geo", "not made this video available"),
     "This video isn't available in your region."),
    (("unsupported url",),
     "This website or link type isn't supported."),
    (("copyright",),
     "This video is blocked for copyright reasons."),
    (("http error 429", "too many requests"),
     "The site is rate-limiting requests. Wait a few minutes and try again."),
    (("http error 403", "forbidden"),
     "The site refused the request (access forbidden). Try again later."),
    (("http error 404", "not found"),
     "The link points to something that doesn't exist."),
    (("requested format is not available", "requested format not available"),
     "That quality or format isn't available for this video. Pick another option."),
    (("no space left", "errno 28"),
     "Your disk is full. Free some space and try again."),
    (("errno 13", "access is denied"),
     "Permission was denied while writing to the download folder. Choose another folder."),
    (("unable to download video data", "read error", "incompleteread", "connection reset",
      "transfer closed", "retrying", "content too short"),
     "The download was interrupted by a network problem. Press Retry to continue where it stopped."),
    (("getaddrinfo", "name resolution", "name or service not known", "network is unreachable",
      "unable to download webpage", "unable to download api", "connection", "timed out", "timeout",
      "urlopen error", "ssl", "remote end closed"),
     "Couldn't reach the site. Check your internet connection and try again."),
    (("no space left", "disk full"),
     "Your disk is full. Free some space and try again."),
    (("permission denied",),
     "Permission was denied while accessing a file or folder."),
    (("ffmpeg", "ffprobe"),
     "FFmpeg is required for this operation but wasn't found. Set its location in Settings."),
)

GENERIC_MESSAGE = "Something went wrong while reading this link. The details were saved to the log."


def friendly_message(exc: BaseException) -> str:
    """Map an exception to a short message safe to show users (full detail is logged)."""
    if isinstance(exc, AppError):
        return exc.message
    text = str(exc).lower()
    for needles, message in _RULES:
        if any(n in text for n in needles):
            return message
    return GENERIC_MESSAGE
