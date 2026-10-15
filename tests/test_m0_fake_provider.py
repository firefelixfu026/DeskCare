from deskcare.domain.types import ActivityKind
from deskcare.sensors.fake import FakeActivityProvider


def test_fake_provider_is_explicitly_synthetic_and_bounded():
    provider = FakeActivityProvider()
    sample = provider.read_sample()
    assert provider.is_demo is True
    assert sample.observation_ok is True
    assert sample.state is ActivityKind.ACTIVE
    assert sample.app_category == "CODE"

