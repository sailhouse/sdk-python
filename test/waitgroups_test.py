import pytest
from unittest.mock import patch
import json
from datetime import datetime

from sailhouse import SailhouseClient, SailhouseError, WaitOptions, WaitGroup


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


def test_wait_options_creation():
    options = WaitOptions(ttl=300)
    assert options.ttl == 300


def test_wait_options_default():
    options = WaitOptions()
    assert options.ttl is None


def test_wait_without_options(client):
    waitgroup = client.wait()
    
    assert isinstance(waitgroup, WaitGroup)
    assert waitgroup.instance_id is not None
    assert len(waitgroup.instance_id) > 0
    assert waitgroup.client is client


def test_wait_with_options_no_ttl(client):
    options = WaitOptions()
    waitgroup = client.wait(options)
    
    assert isinstance(waitgroup, WaitGroup)
    assert waitgroup.instance_id is not None
    assert waitgroup.client is client


def test_wait_with_ttl(client, mock_response):
    options = WaitOptions(ttl=600)
    
    with patch.object(client.session, 'post', return_value=mock_response(201, {})) as mock_post:
        waitgroup = client.wait(options)
        
        assert isinstance(waitgroup, WaitGroup)
        assert waitgroup.instance_id is not None
        assert waitgroup.client is client
        
        # Verify API call was made
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        url = call_args[0][0]
        body = call_args[1]['json']
        
        assert url == "https://api.sailhouse.dev/waitgroups"
        assert body['ttl'] == 600
        assert 'instance_id' in body


def test_wait_with_ttl_failure(client, mock_response):
    options = WaitOptions(ttl=600)
    
    with patch.object(client.session, 'post', return_value=mock_response(400, {})):
        with pytest.raises(SailhouseError) as exc_info:
            client.wait(options)
        
        assert "Failed to create waitgroup" in str(exc_info.value)


@pytest.mark.asyncio
async def test_publish_with_wait_group_instance_id(client, mock_response):
    test_data = {"message": "test"}
    wait_group_id = "test-wait-group-id"
    
    with patch.object(client.session, 'post', return_value=mock_response(201, {})) as mock_post:
        await client.publish(
            "test-topic",
            test_data,
            wait_group_instance_id=wait_group_id
        )
        
        # Verify the request body includes wait_group_instance_id
        call_args = mock_post.call_args
        body = call_args[1]['json']
        assert body['wait_group_instance_id'] == wait_group_id
        assert body['data'] == test_data


@pytest.mark.asyncio
async def test_publish_without_wait_group_instance_id(client, mock_response):
    test_data = {"message": "test"}
    
    with patch.object(client.session, 'post', return_value=mock_response(201, {})) as mock_post:
        await client.publish("test-topic", test_data)
        
        # Verify the request body does not include wait_group_instance_id
        call_args = mock_post.call_args
        body = call_args[1]['json']
        assert 'wait_group_instance_id' not in body
        assert body['data'] == test_data


@pytest.mark.asyncio
async def test_waitgroup_publish(client, mock_response):
    # Create a waitgroup
    waitgroup = client.wait()
    test_data = {"message": "test from waitgroup"}
    metadata = {"source": "waitgroup"}
    scheduled_time = datetime.now()
    
    with patch.object(client.session, 'post', return_value=mock_response(201, {})) as mock_post:
        await waitgroup.publish(
            "test-topic",
            test_data,
            metadata=metadata,
            scheduled_time=scheduled_time
        )
        
        # Verify the request includes the waitgroup instance_id
        call_args = mock_post.call_args
        body = call_args[1]['json']
        assert body['wait_group_instance_id'] == waitgroup.instance_id
        assert body['data'] == test_data
        assert body['metadata'] == metadata
        assert 'send_at' in body


@pytest.mark.asyncio
async def test_waitgroup_publish_minimal(client, mock_response):
    waitgroup = client.wait()
    test_data = {"simple": "message"}
    
    with patch.object(client.session, 'post', return_value=mock_response(201, {})) as mock_post:
        await waitgroup.publish("test-topic", test_data)
        
        call_args = mock_post.call_args
        body = call_args[1]['json']
        assert body['wait_group_instance_id'] == waitgroup.instance_id
        assert body['data'] == test_data
        assert 'metadata' not in body
        assert 'send_at' not in body


def test_multiple_waitgroups_have_different_ids(client):
    waitgroup1 = client.wait()
    waitgroup2 = client.wait()
    
    assert waitgroup1.instance_id != waitgroup2.instance_id
    assert isinstance(waitgroup1, WaitGroup)
    assert isinstance(waitgroup2, WaitGroup)


@pytest.mark.asyncio
async def test_publish_with_all_parameters_including_waitgroup(client, mock_response):
    test_data = {"complex": "message"}
    metadata = {"key": "value"}
    scheduled_time = datetime.now()
    wait_group_id = "complex-wait-group"
    
    with patch.object(client.session, 'post', return_value=mock_response(201, {})) as mock_post:
        await client.publish(
            "complex-topic",
            test_data,
            metadata=metadata,
            scheduled_time=scheduled_time,
            wait_group_instance_id=wait_group_id
        )
        
        call_args = mock_post.call_args
        body = call_args[1]['json']
        assert body['data'] == test_data
        assert body['metadata'] == metadata
        assert body['wait_group_instance_id'] == wait_group_id
        assert 'send_at' in body