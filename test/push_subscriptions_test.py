import pytest
import time
import hmac
import hashlib
from unittest.mock import patch

from sailhouse import (
    SailhouseClient, 
    PushSubscriptionVerifier,
    PushSubscriptionVerificationError,
    SignatureComponents,
    PushSubscriptionHeaders,
    PushSubscriptionPayload,
    VerificationOptions,
    verify_push_subscription_signature,
    verify_push_subscription_signature_safe
)


@pytest.fixture
def webhook_secret():
    return "test_webhook_secret_key"


@pytest.fixture
def test_payload():
    return '{"event": "user.created", "data": {"id": 123, "name": "John"}}'


@pytest.fixture
def verifier(webhook_secret):
    return PushSubscriptionVerifier(webhook_secret)


def create_valid_signature(webhook_secret: str, timestamp: int, payload: str) -> str:
    """Helper to create a valid signature for testing"""
    signed_payload = f"{timestamp}.{payload}".encode('utf-8')
    signature = hmac.new(
        webhook_secret.encode('utf-8'),
        signed_payload,
        hashlib.sha256
    ).hexdigest()
    return f"t={timestamp},v1={signature}"


def test_verification_options_creation():
    options = VerificationOptions(tolerance=600)
    assert options.tolerance == 600


def test_verification_options_default():
    options = VerificationOptions()
    assert options.tolerance == 300


def test_push_subscription_headers_creation():
    headers = PushSubscriptionHeaders(signature="t=123,v1=abc")
    assert headers.signature == "t=123,v1=abc"


def test_push_subscription_payload_creation():
    payload = PushSubscriptionPayload(raw_body="test body")
    assert payload.raw_body == "test body"


def test_verifier_initialization(webhook_secret):
    verifier = PushSubscriptionVerifier(webhook_secret)
    assert verifier.webhook_secret == webhook_secret.encode('utf-8')


def test_parse_signature_header_valid(verifier):
    signature_header = "t=1640995200,v1=abc123def456"
    components = verifier.parse_signature_header(signature_header)
    
    assert components.timestamp == 1640995200
    assert components.signature == "abc123def456"


def test_parse_signature_header_multiple_parts(verifier):
    signature_header = "t=1640995200,v1=abc123,v2=def456"
    components = verifier.parse_signature_header(signature_header)
    
    assert components.timestamp == 1640995200
    assert components.signature == "abc123"  # Takes first v1


def test_parse_signature_header_missing_timestamp(verifier):
    signature_header = "v1=abc123def456"
    
    with pytest.raises(PushSubscriptionVerificationError) as exc_info:
        verifier.parse_signature_header(signature_header)
    
    assert exc_info.value.error_code == PushSubscriptionVerificationError.MISSING_TIMESTAMP


def test_parse_signature_header_missing_signature(verifier):
    signature_header = "t=1640995200"
    
    with pytest.raises(PushSubscriptionVerificationError) as exc_info:
        verifier.parse_signature_header(signature_header)
    
    assert exc_info.value.error_code == PushSubscriptionVerificationError.INVALID_SIGNATURE_FORMAT


def test_parse_signature_header_invalid_timestamp(verifier):
    signature_header = "t=invalid,v1=abc123"
    
    with pytest.raises(PushSubscriptionVerificationError) as exc_info:
        verifier.parse_signature_header(signature_header)
    
    assert exc_info.value.error_code == PushSubscriptionVerificationError.INVALID_SIGNATURE_FORMAT


def test_parse_signature_header_empty(verifier):
    with pytest.raises(PushSubscriptionVerificationError) as exc_info:
        verifier.parse_signature_header("")
    
    assert exc_info.value.error_code == PushSubscriptionVerificationError.INVALID_SIGNATURE_FORMAT


def test_validate_timestamp_valid(verifier):
    current_time = int(time.time())
    # Should not raise
    verifier.validate_timestamp(current_time, tolerance=300)
    verifier.validate_timestamp(current_time - 100, tolerance=300)
    verifier.validate_timestamp(current_time + 100, tolerance=300)


def test_validate_timestamp_too_old(verifier):
    current_time = int(time.time())
    old_timestamp = current_time - 400  # 400 seconds ago
    
    with pytest.raises(PushSubscriptionVerificationError) as exc_info:
        verifier.validate_timestamp(old_timestamp, tolerance=300)
    
    assert exc_info.value.error_code == PushSubscriptionVerificationError.TIMESTAMP_TOO_OLD


def test_validate_timestamp_too_new(verifier):
    current_time = int(time.time())
    future_timestamp = current_time + 400  # 400 seconds in future
    
    with pytest.raises(PushSubscriptionVerificationError) as exc_info:
        verifier.validate_timestamp(future_timestamp, tolerance=300)
    
    assert exc_info.value.error_code == PushSubscriptionVerificationError.TIMESTAMP_TOO_NEW


def test_compute_signature(verifier, test_payload):
    timestamp = 1640995200
    signature = verifier.compute_signature(timestamp, test_payload.encode('utf-8'))
    
    # Verify it's a valid hex string of correct length (SHA256 = 64 chars)
    assert len(signature) == 64
    assert all(c in '0123456789abcdef' for c in signature)


def test_constant_time_compare(verifier):
    # Same strings
    assert verifier.constant_time_compare("abc123", "abc123") is True
    
    # Different strings same length
    assert verifier.constant_time_compare("abc123", "def456") is False
    
    # Different lengths
    assert verifier.constant_time_compare("abc", "abcdef") is False
    
    # Empty strings
    assert verifier.constant_time_compare("", "") is True


def test_verify_valid_signature(verifier, webhook_secret, test_payload):
    current_time = int(time.time())
    signature_header = create_valid_signature(webhook_secret, current_time, test_payload)
    
    headers = PushSubscriptionHeaders(signature=signature_header)
    payload = PushSubscriptionPayload(raw_body=test_payload)
    
    # Should not raise and return True
    result = verifier.verify(headers, payload)
    assert result is True


def test_verify_with_bytes_payload(verifier, webhook_secret, test_payload):
    current_time = int(time.time())
    signature_header = create_valid_signature(webhook_secret, current_time, test_payload)
    
    headers = PushSubscriptionHeaders(signature=signature_header)
    payload = PushSubscriptionPayload(raw_body=test_payload.encode('utf-8'))
    
    result = verifier.verify(headers, payload)
    assert result is True


def test_verify_invalid_signature(verifier, test_payload):
    current_time = int(time.time())
    # Create signature with wrong secret
    wrong_signature = create_valid_signature("wrong_secret", current_time, test_payload)
    
    headers = PushSubscriptionHeaders(signature=wrong_signature)
    payload = PushSubscriptionPayload(raw_body=test_payload)
    
    with pytest.raises(PushSubscriptionVerificationError) as exc_info:
        verifier.verify(headers, payload)
    
    assert exc_info.value.error_code == PushSubscriptionVerificationError.SIGNATURE_MISMATCH


def test_verify_old_timestamp(verifier, webhook_secret, test_payload):
    old_timestamp = int(time.time()) - 400  # 400 seconds ago
    signature_header = create_valid_signature(webhook_secret, old_timestamp, test_payload)
    
    headers = PushSubscriptionHeaders(signature=signature_header)
    payload = PushSubscriptionPayload(raw_body=test_payload)
    
    with pytest.raises(PushSubscriptionVerificationError) as exc_info:
        verifier.verify(headers, payload)
    
    assert exc_info.value.error_code == PushSubscriptionVerificationError.TIMESTAMP_TOO_OLD


def test_verify_with_custom_tolerance(verifier, webhook_secret, test_payload):
    old_timestamp = int(time.time()) - 400  # 400 seconds ago
    signature_header = create_valid_signature(webhook_secret, old_timestamp, test_payload)
    
    headers = PushSubscriptionHeaders(signature=signature_header)
    payload = PushSubscriptionPayload(raw_body=test_payload)
    options = VerificationOptions(tolerance=500)  # Allow 500 seconds
    
    # Should not raise with larger tolerance
    result = verifier.verify(headers, payload, options)
    assert result is True


def test_verify_safe_valid_signature(verifier, webhook_secret, test_payload):
    current_time = int(time.time())
    signature_header = create_valid_signature(webhook_secret, current_time, test_payload)
    
    headers = PushSubscriptionHeaders(signature=signature_header)
    payload = PushSubscriptionPayload(raw_body=test_payload)
    
    result = verifier.verify_safe(headers, payload)
    assert result is True


def test_verify_safe_invalid_signature(verifier, test_payload):
    current_time = int(time.time())
    wrong_signature = create_valid_signature("wrong_secret", current_time, test_payload)
    
    headers = PushSubscriptionHeaders(signature=wrong_signature)
    payload = PushSubscriptionPayload(raw_body=test_payload)
    
    # Should return False instead of raising
    result = verifier.verify_safe(headers, payload)
    assert result is False


def test_one_off_verify_function(webhook_secret, test_payload):
    current_time = int(time.time())
    signature_header = create_valid_signature(webhook_secret, current_time, test_payload)
    
    headers = PushSubscriptionHeaders(signature=signature_header)
    payload = PushSubscriptionPayload(raw_body=test_payload)
    
    result = verify_push_subscription_signature(webhook_secret, headers, payload)
    assert result is True


def test_one_off_verify_safe_function(webhook_secret, test_payload):
    current_time = int(time.time())
    wrong_signature = create_valid_signature("wrong_secret", current_time, test_payload)
    
    headers = PushSubscriptionHeaders(signature=wrong_signature)
    payload = PushSubscriptionPayload(raw_body=test_payload)
    
    result = verify_push_subscription_signature_safe(webhook_secret, headers, payload)
    assert result is False


def test_client_verify_push_subscription():
    client = SailhouseClient(token="test-token")
    webhook_secret = "test_secret"
    test_payload = '{"test": "data"}'
    current_time = int(time.time())
    signature_header = create_valid_signature(webhook_secret, current_time, test_payload)
    
    result = client.verify_push_subscription(
        webhook_secret=webhook_secret,
        signature_header=signature_header,
        raw_body=test_payload
    )
    assert result is True


def test_client_verify_push_subscription_safe():
    client = SailhouseClient(token="test-token")
    webhook_secret = "test_secret"
    test_payload = '{"test": "data"}'
    current_time = int(time.time())
    wrong_signature = create_valid_signature("wrong_secret", current_time, test_payload)
    
    result = client.verify_push_subscription_safe(
        webhook_secret=webhook_secret,
        signature_header=wrong_signature,
        raw_body=test_payload
    )
    assert result is False


def test_client_verify_push_subscription_with_custom_tolerance():
    client = SailhouseClient(token="test-token")
    webhook_secret = "test_secret"
    test_payload = '{"test": "data"}'
    old_timestamp = int(time.time()) - 400
    signature_header = create_valid_signature(webhook_secret, old_timestamp, test_payload)
    
    result = client.verify_push_subscription(
        webhook_secret=webhook_secret,
        signature_header=signature_header,
        raw_body=test_payload,
        tolerance=500  # Allow 500 seconds
    )
    assert result is True


def test_error_code_constants():
    # Verify error code constants exist and are correct
    assert PushSubscriptionVerificationError.INVALID_SIGNATURE_FORMAT == "invalid_signature_format"
    assert PushSubscriptionVerificationError.MISSING_TIMESTAMP == "missing_timestamp"
    assert PushSubscriptionVerificationError.TIMESTAMP_TOO_OLD == "timestamp_too_old"
    assert PushSubscriptionVerificationError.TIMESTAMP_TOO_NEW == "timestamp_too_new"
    assert PushSubscriptionVerificationError.SIGNATURE_MISMATCH == "signature_mismatch"


def test_real_world_webhook_scenario(webhook_secret):
    """Test a realistic webhook verification scenario"""
    # Simulate a real webhook payload
    webhook_payload = '''{
        "event": "subscription.created",
        "data": {
            "id": "sub_123",
            "status": "active",
            "created_at": "2024-01-01T00:00:00Z"
        },
        "timestamp": "2024-01-01T00:00:00Z"
    }'''
    
    current_time = int(time.time())
    signature_header = create_valid_signature(webhook_secret, current_time, webhook_payload)
    
    verifier = PushSubscriptionVerifier(webhook_secret)
    headers = PushSubscriptionHeaders(signature=signature_header)
    payload = PushSubscriptionPayload(raw_body=webhook_payload)
    
    # Should verify successfully
    result = verifier.verify(headers, payload)
    assert result is True
    
    # Should also work with safe version
    safe_result = verifier.verify_safe(headers, payload)
    assert safe_result is True