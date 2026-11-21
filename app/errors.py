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

# (substrings to look for in lower-cased message, friendly text). Order matters: first match wins.
_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    # --- cookies (checked first: their errors also mention "cookies"/"database"/"decrypt") ---
    (("could not copy", "cookies database", "failed to decrypt", "dpapi", "cookie database"),
     "Couldn't read the sign-in cookies from your browser. Close the browser and try again, "
     "or export a cookies.txt file and choose it in Settings → Sign-in cookies."),
    (("cookies file", "cookiefile", "invalid length", "does not look like a netscape"),
     "The cookies file couldn't be used. Export a fresh Netscape-format cookies.txt and choose it again in Settings."),
    # --- access problems ---
    (("drm", "widevine", "playready", "fairplay"),
     "This media is copy-protected (DRM) and can't be downloaded."),
    (("private video", "this video is private", "is private", "private account"),
     "This content is private. Only its owner can access it."),
    (("confirm your age", "age-restricted", "age restricted", "inappropriate for some users", "age verification"),
     "This content is age-restricted. Sign in (Settings → Sign-in cookies) and try again."),
    (("sign in to confirm", "not a bot", "login required", "log in to", "log in or", "sign in", "requires authentication",
      "use --cookies", "login to", "need to log in", "rate-limit reached or login required"),
     "This site wants you to sign in first. Use Settings → Sign-in cookies with your own account, then retry."),
    (("members-only", "members only", "join this channel", "subscribers only", "premium", "paid content"),
     "This content is for members or paying subscribers only. Sign in with an account that has access "
     "(Settings → Sign-in cookies)."),
    (("video unavailable", "this video is unavailable", "has been removed", "no longer available",
      "account associated with this video has been terminated", "content isn't available", "post not found",
      "does not exist", "been deleted"),
     "This content is unavailable. It may have been removed or made private."),
    (("not available in your country", "blocked it in your country", "geo", "not made this video available",
      "in your region"),
     "This content isn't available in your region."),
    (("is live", "live event will begin", "premieres in", "this live stream", "live stream recording is not available"),
     "This is a live stream or an upcoming premiere. Try again once it has finished and been published."),
    (("unsupported url",),
     "This link isn't supported. Open the page with the video itself and copy that link instead."),
    (("no video formats found", "no video could be found", "there is no video", "no media found",
      "unable to extract", "unable to find video", "unable to find"),
     "No downloadable video or audio was found on this page. Make sure the link points to the media itself."),
    (("copyright",),
     "This content is blocked for copyright reasons."),
    # --- site/network problems ---
    (("http error 429", "too many requests"),
     "The site is rate-limiting requests. Wait a few minutes and try again."),
    (("http error 403", "forbidden"),
     "The site refused the request (access forbidden). If it needs an account, use Settings → Sign-in cookies; "
     "otherwise try again later."),
    (("http error 404", "not found"),
     "The link points to something that doesn't exist."),
    (("requested format is not available", "requested format not available"),
     "That quality or format isn't available for this media. Pick another option."),
    (("no space left", "errno 28", "disk full"),
     "Your disk is full. Free some space and try again."),
    (("errno 13", "access is denied", "permission denied"),
     "Permission was denied while writing to the download folder. Choose another folder."),
    (("unable to download video data", "read error", "incompleteread", "connection reset",
      "transfer closed", "retrying", "content too short"),
     "The download was interrupted by a network problem. Press Retry to continue where it stopped."),
    (("getaddrinfo", "name resolution", "name or service not known", "network is unreachable",
      "unable to download webpage", "unable to download api", "connection", "timed out", "timeout",
      "urlopen error", "ssl", "remote end closed"),
     "Couldn't reach the site. Check your internet connection and try again."),
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
