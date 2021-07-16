class NoSpotifyPresenceError(Exception):
    """Raised when the member doesn't have Spotify presence."""


class LocalFilesDetected(Exception):
    """Raised when the member is listening to local files on Spotify."""
