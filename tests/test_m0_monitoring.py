from deskcare.sensors.fake import FakeActivityProvider
from deskcare.services.consent_service import MonitoringController


def test_disabled_monitoring_never_reads_provider():
    provider = FakeActivityProvider()
    controller = MonitoringController(provider)
    assert controller.read_sample_if_allowed() is None
    assert provider.read_count == 0


def test_pause_stops_provider_reads_after_consent():
    provider = FakeActivityProvider()
    controller = MonitoringController(provider)
    controller.set_enabled(True)
    assert controller.read_sample_if_allowed() is not None
    controller.set_paused(True)
    assert controller.read_sample_if_allowed() is None
    assert provider.read_count == 1

