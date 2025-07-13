import pytest
from unittest.mock import patch
import json

from sailhouse import SailhouseClient, SailhouseError
from sailhouse.admin import AdminClient, FilterCondition, ComplexFilter, RegisterResult


@pytest.fixture
def client():
    return SailhouseClient(token="test-token")


@pytest.fixture
def mock_response():
    class MockResponse:
        def __init__(self, status_code, json_data=None):
            self.status_code = status_code
            self._json_data = json_data
            self.text = json.dumps(json_data) if json_data else ""

        def json(self):
            if self._json_data is None:
                raise ValueError("No JSON data available")
            return self._json_data

    return MockResponse


def test_admin_client_initialization(client):
    assert hasattr(client, 'admin')
    assert isinstance(client.admin, AdminClient)
    assert client.admin._client is client


def test_filter_condition_creation():
    condition = FilterCondition(path="data.type", condition="eq", value="user")
    assert condition.path == "data.type"
    assert condition.condition == "eq"
    assert condition.value == "user"


def test_complex_filter_creation():
    condition1 = FilterCondition(path="data.type", condition="eq", value="user")
    condition2 = FilterCondition(path="data.status", condition="eq", value="active")
    
    complex_filter = ComplexFilter(conditions=[condition1, condition2], operator="and")
    assert len(complex_filter.conditions) == 2
    assert complex_filter.operator == "and"


def test_complex_filter_default_operator():
    condition = FilterCondition(path="data.type", condition="eq", value="user")
    complex_filter = ComplexFilter(conditions=[condition])
    assert complex_filter.operator == "and"


def test_register_push_subscription_basic(client, mock_response):
    response_data = {"outcome": "created"}
    
    with patch.object(client.session, 'post', return_value=mock_response(201, response_data)):
        result = client.admin.register_push_subscription(
            topic="test-topic",
            subscription="test-sub",
            endpoint="https://example.com/webhook"
        )
        
        assert isinstance(result, RegisterResult)
        assert result.outcome == "created"


def test_register_push_subscription_with_boolean_filter(client, mock_response):
    response_data = {"outcome": "updated"}
    
    with patch.object(client.session, 'post', return_value=mock_response(200, response_data)) as mock_post:
        result = client.admin.register_push_subscription(
            topic="test-topic",
            subscription="test-sub",
            endpoint="https://example.com/webhook",
            filter_condition=True
        )
        
        assert result.outcome == "updated"
        
        # Verify the request body
        call_args = mock_post.call_args
        body = call_args[1]['json']
        assert body['filter'] is True


def test_register_push_subscription_with_none_filter(client, mock_response):
    response_data = {"outcome": "none"}
    
    with patch.object(client.session, 'post', return_value=mock_response(200, response_data)) as mock_post:
        result = client.admin.register_push_subscription(
            topic="test-topic",
            subscription="test-sub",
            endpoint="https://example.com/webhook",
            filter_condition=None
        )
        
        assert result.outcome == "none"
        
        # Verify the request body
        call_args = mock_post.call_args
        body = call_args[1]['json']
        assert body['filter'] is None


def test_register_push_subscription_with_complex_filter(client, mock_response):
    condition1 = FilterCondition(path="data.type", condition="eq", value="user")
    condition2 = FilterCondition(path="data.status", condition="eq", value="active")
    complex_filter = ComplexFilter(conditions=[condition1, condition2], operator="or")
    
    response_data = {"outcome": "created"}
    
    with patch.object(client.session, 'post', return_value=mock_response(201, response_data)) as mock_post:
        result = client.admin.register_push_subscription(
            topic="test-topic",
            subscription="test-sub",
            endpoint="https://example.com/webhook",
            filter_condition=complex_filter
        )
        
        assert result.outcome == "created"
        
        # Verify the request body
        call_args = mock_post.call_args
        body = call_args[1]['json']
        expected_filter = {
            "conditions": [
                {"path": "data.type", "condition": "eq", "value": "user"},
                {"path": "data.status", "condition": "eq", "value": "active"}
            ],
            "operator": "or"
        }
        assert body['filter'] == expected_filter


def test_register_push_subscription_with_rate_limit_and_deduplication(client, mock_response):
    response_data = {"outcome": "updated"}
    
    with patch.object(client.session, 'post', return_value=mock_response(200, response_data)) as mock_post:
        result = client.admin.register_push_subscription(
            topic="test-topic",
            subscription="test-sub",
            endpoint="https://example.com/webhook",
            rate_limit=100,
            deduplication=True
        )
        
        assert result.outcome == "updated"
        
        # Verify the request body
        call_args = mock_post.call_args
        body = call_args[1]['json']
        assert body['rate_limit'] == 100
        assert body['deduplication'] is True


def test_register_push_subscription_with_all_options(client, mock_response):
    condition = FilterCondition(path="data.priority", condition="gte", value=5)
    complex_filter = ComplexFilter(conditions=[condition])
    
    response_data = {"outcome": "created"}
    
    with patch.object(client.session, 'post', return_value=mock_response(201, response_data)) as mock_post:
        result = client.admin.register_push_subscription(
            topic="notifications",
            subscription="high-priority",
            endpoint="https://api.example.com/webhooks/notifications",
            filter_condition=complex_filter,
            rate_limit=50,
            deduplication=False
        )
        
        assert result.outcome == "created"
        
        # Verify the request was made to the correct URL
        call_args = mock_post.call_args
        url = call_args[0][0]
        assert url == "https://api.sailhouse.dev/admin/topics/notifications/subscriptions/high-priority/push"
        
        # Verify the complete request body
        body = call_args[1]['json']
        expected_body = {
            "endpoint": "https://api.example.com/webhooks/notifications",
            "filter": {
                "conditions": [
                    {"path": "data.priority", "condition": "gte", "value": 5}
                ],
                "operator": "and"
            },
            "rate_limit": 50,
            "deduplication": False
        }
        assert body == expected_body


def test_register_push_subscription_failure(client, mock_response):
    with patch.object(client.session, 'post', return_value=mock_response(400, {})):
        with pytest.raises(SailhouseError) as exc_info:
            client.admin.register_push_subscription(
                topic="test-topic",
                subscription="test-sub",
                endpoint="https://example.com/webhook"
            )
        
        assert "Failed to register push subscription" in str(exc_info.value)


def test_register_push_subscription_server_error(client, mock_response):
    with patch.object(client.session, 'post', return_value=mock_response(500, {})):
        with pytest.raises(SailhouseError) as exc_info:
            client.admin.register_push_subscription(
                topic="test-topic",
                subscription="test-sub",
                endpoint="https://example.com/webhook"
            )
        
        assert "Failed to register push subscription: 500" in str(exc_info.value)


def test_register_result_default_outcome(client, mock_response):
    # Test when response doesn't include outcome field
    response_data = {}
    
    with patch.object(client.session, 'post', return_value=mock_response(200, response_data)):
        result = client.admin.register_push_subscription(
            topic="test-topic",
            subscription="test-sub",
            endpoint="https://example.com/webhook"
        )
        
        assert result.outcome == "none"