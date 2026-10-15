"""Monitoring consent and pause gate shared by M0 and M1."""

from collections.abc import Callable

from deskcare.sensors.base import ActivityProvider


class MonitoringController:
    """Owns the invariant: disabled/paused monitoring never reads a provider."""

    def __init__(self, provider: ActivityProvider, initially_enabled: bool = False) -> None:
        self._provider = provider
        self._enabled = initially_enabled
        self._paused = False
        self._listeners: list[Callable[[bool, bool], None]] = []

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def is_collecting(self) -> bool:
        return self._enabled and not self._paused

    @property
    def provider_is_demo(self) -> bool:
        """Expose only the provider mode needed for an honest UI label."""

        return bool(getattr(self._provider, "is_demo", False))

    def subscribe(self, listener: Callable[[bool, bool], None]) -> None:
        self._listeners.append(listener)

    def _notify(self) -> None:
        for listener in tuple(self._listeners):
            listener(self._enabled, self._paused)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        if not self._enabled:
            self._paused = False
        self._notify()

    def set_app_name_enabled(self, enabled: bool) -> None:
        """Configure optional app identity sampling independently."""

        configure = getattr(self._provider, "set_app_name_enabled", None)
        if configure is not None:
            configure(bool(enabled))

    def set_paused(self, paused: bool) -> None:
        self._paused = bool(paused) if self._enabled else False
        self._notify()

    def toggle_paused(self) -> None:
        self.set_paused(not self._paused)

    def read_sample_if_allowed(self):
        """Read only after explicit consent and while not paused."""

        if not self.is_collecting:
            return None
        return self._provider.read_sample()

