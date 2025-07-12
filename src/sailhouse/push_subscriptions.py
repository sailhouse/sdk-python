import hmac
import hashlib
import time
from dataclasses import dataclass
from typing import Dict, Optional, Union, Literal
from .exceptions import SailhouseError


class PushSubscriptionVerificationError(SailhouseError):
    """Custom error for push subscription verification failures"""
    
    INVALID_SIGNATURE_FORMAT = "invalid_signature_format"
    MISSING_TIMESTAMP = "missing_timestamp"
    TIMESTAMP_TOO_OLD = "timestamp_too_old"
    TIMESTAMP_TOO_NEW = "timestamp_too_new"
    SIGNATURE_MISMATCH = "signature_mismatch"
    
    def __init__(self, message: str, error_code: str):
        super().__init__(message)
        self.error_code = error_code


@dataclass
class SignatureComponents:
    timestamp: int
    signature: str


@dataclass
class PushSubscriptionHeaders:
    signature: str
    
    
@dataclass
class PushSubscriptionPayload:
    raw_body: Union[str, bytes]


@dataclass
class VerificationOptions:
    tolerance: int = 300  # 5 minutes in seconds


class PushSubscriptionVerifier:
    def __init__(self, webhook_secret: str):
        self.webhook_secret = webhook_secret.encode('utf-8')
    
    def parse_signature_header(self, signature_header: str) -> SignatureComponents:
        """Parse the signature header format: 't=<timestamp>,v1=<signature>'"""
        if not signature_header:
            raise PushSubscriptionVerificationError(
                "Signature header is missing",
                PushSubscriptionVerificationError.INVALID_SIGNATURE_FORMAT
            )
        
        parts = signature_header.split(',')
        timestamp = None
        signature = None
        
        for part in parts:
            if '=' not in part:
                continue
            key, value = part.split('=', 1)
            if key == 't':
                try:
                    timestamp = int(value)
                except ValueError:
                    raise PushSubscriptionVerificationError(
                        "Invalid timestamp format",
                        PushSubscriptionVerificationError.INVALID_SIGNATURE_FORMAT
                    )
            elif key == 'v1':
                signature = value
        
        if timestamp is None:
            raise PushSubscriptionVerificationError(
                "Missing timestamp in signature header",
                PushSubscriptionVerificationError.MISSING_TIMESTAMP
            )
        
        if signature is None:
            raise PushSubscriptionVerificationError(
                "Missing signature in header",
                PushSubscriptionVerificationError.INVALID_SIGNATURE_FORMAT
            )
        
        return SignatureComponents(timestamp=timestamp, signature=signature)
    
    def validate_timestamp(self, timestamp: int, tolerance: int = 300) -> None:
        """Validate timestamp is within acceptable range"""
        current_time = int(time.time())
        
        if timestamp > current_time + tolerance:
            raise PushSubscriptionVerificationError(
                f"Timestamp is too new: {timestamp} > {current_time + tolerance}",
                PushSubscriptionVerificationError.TIMESTAMP_TOO_NEW
            )
        
        if timestamp < current_time - tolerance:
            raise PushSubscriptionVerificationError(
                f"Timestamp is too old: {timestamp} < {current_time - tolerance}",
                PushSubscriptionVerificationError.TIMESTAMP_TOO_OLD
            )
    
    def compute_signature(self, timestamp: int, payload: bytes) -> str:
        """Compute HMAC-SHA256 signature"""
        signed_payload = f"{timestamp}.".encode('utf-8') + payload
        signature = hmac.new(
            self.webhook_secret,
            signed_payload,
            hashlib.sha256
        ).hexdigest()
        return signature
    
    def constant_time_compare(self, a: str, b: str) -> bool:
        """Constant-time string comparison to prevent timing attacks"""
        if len(a) != len(b):
            return False
        
        result = 0
        for x, y in zip(a, b):
            result |= ord(x) ^ ord(y)
        return result == 0
    
    def verify(
        self,
        headers: PushSubscriptionHeaders,
        payload: PushSubscriptionPayload,
        options: Optional[VerificationOptions] = None
    ) -> bool:
        """Verify push subscription signature - raises exception on failure"""
        if options is None:
            options = VerificationOptions()
        
        # Parse signature header
        components = self.parse_signature_header(headers.signature)
        
        # Validate timestamp
        self.validate_timestamp(components.timestamp, options.tolerance)
        
        # Convert payload to bytes if needed
        if isinstance(payload.raw_body, str):
            payload_bytes = payload.raw_body.encode('utf-8')
        else:
            payload_bytes = payload.raw_body
        
        # Compute expected signature
        expected_signature = self.compute_signature(components.timestamp, payload_bytes)
        
        # Compare signatures using constant-time comparison
        if not self.constant_time_compare(expected_signature, components.signature):
            raise PushSubscriptionVerificationError(
                "Signature verification failed",
                PushSubscriptionVerificationError.SIGNATURE_MISMATCH
            )
        
        return True
    
    def verify_safe(
        self,
        headers: PushSubscriptionHeaders,
        payload: PushSubscriptionPayload,
        options: Optional[VerificationOptions] = None
    ) -> bool:
        """Safe version of verify that returns boolean instead of raising"""
        try:
            return self.verify(headers, payload, options)
        except PushSubscriptionVerificationError:
            return False


def verify_push_subscription_signature(
    webhook_secret: str,
    headers: PushSubscriptionHeaders,
    payload: PushSubscriptionPayload,
    options: Optional[VerificationOptions] = None
) -> bool:
    """One-off verification function - raises exception on failure"""
    verifier = PushSubscriptionVerifier(webhook_secret)
    return verifier.verify(headers, payload, options)


def verify_push_subscription_signature_safe(
    webhook_secret: str,
    headers: PushSubscriptionHeaders,
    payload: PushSubscriptionPayload,
    options: Optional[VerificationOptions] = None
) -> bool:
    """Safe one-off verification function - returns boolean"""
    verifier = PushSubscriptionVerifier(webhook_secret)
    return verifier.verify_safe(headers, payload, options)