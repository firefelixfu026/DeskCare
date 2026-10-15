from deskcare.config import AppConfig, ConfigStore


def test_first_launch_sensitive_scopes_are_off():
    config = ConfigStore().config
    assert config.activity_monitoring_enabled is False
    assert config.app_name_stats_enabled is False
    assert config.wellness_checkin_enabled is False
    assert config.local_ai_enabled is False


def test_default_parameters_are_non_medical_product_parameters():
    config = AppConfig()
    assert config.break_candidate_minutes == 40
    assert config.max_soft_delay_minutes == 20

