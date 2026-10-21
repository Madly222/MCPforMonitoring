from src.core.config import SERVICES_DIR, VALID_SERVICE_TYPES
from src.services.registry import SERVICE_HANDLERS


def test_registry_config_list_and_yaml_files_agree():
    assert set(SERVICE_HANDLERS) == set(VALID_SERVICE_TYPES)
    for service_type in SERVICE_HANDLERS:
        assert (SERVICES_DIR / f"{service_type}.yaml").exists(), service_type
