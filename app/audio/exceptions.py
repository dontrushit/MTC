"""Audio processing errors."""


class MonoNotSupportedError(Exception):
    """Raised when a mono recording is passed (stereo-only until diarization stage)."""

    def __init__(self, path: str) -> None:
        super().__init__(
            f"Mono audio is not supported yet (expected stereo: ch0=manager, ch1=client): {path}"
        )
        self.path = path
