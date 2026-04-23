"""
Shared testing constants and fixtures - randomly generated

"""
import pytest
from custom_components.onecontrol_ble.protocol import SecurityData

# Testovací klíče — vygenerované náhodně, matematicky konzistentní
TEST_LTK         = "C4F6E72CA3FC7399C8330D513C71BBFB"
TEST_RANDOM_A    = "93FD94616A8B8639"
TEST_RANDOM_B    = "315B7F0C4F4CEA1D"
TEST_SESSION_ID  = "4940CABE843D90F4"
TEST_SESSION_KEY = "2B1BB7B4BD53417E41BB938B64A5B48F"


@pytest.fixture
def security() -> SecurityData:
    return SecurityData(
        ltk=bytes.fromhex(TEST_LTK),
        session_key=bytes.fromhex(TEST_SESSION_KEY),
        session_id=bytes.fromhex(TEST_SESSION_ID),
        user_id=0,
        last_cc=100,
    )
