from dataclasses import dataclass
import pytest
from datetime import datetime
import asyncio
from unittest.mock import AsyncMock, Mock, patch
import json

from sailhouse import SailhouseClient, Event, GetEventsResponse, SailhouseError

# Fixtures


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


def test_event_creation():
    client = SailhouseClient(token="test-token")
    event = Event(
        id="test-id",
        data={"message": "test"},
        _topic="test-topic",
        _subscription="test-sub",
        _client=client
    )

    assert event.id == "test-id"
    assert event.data == {"message": "test"}


def test_event_as_type():
    @dataclass
    class TestType:
        message: str

    client = SailhouseClient(token="test-token")
    event = Event(
        id="test-id",
        data={"message": "test"},
        _topic="test-topic",
        _subscription="test-sub",
        _client=client
    )

    converted = event.as_type(TestType)
    assert isinstance(converted, TestType)
    assert converted.message == "test"

# Test SailhouseClient


def test_client_initialization():
    client = SailhouseClient(token="test-token")
    assert client.token == "test-token"
    assert client.timeout == 5.0
    assert client.base_url == "https://api.sailhouse.dev"
    assert client.session.headers["Authorization"] == "test-token"
    assert client.session.headers["x-source"] == "sailhouse-python"


@pytest.mark.asyncio
async def test_get_events_success(client, mock_response):
    test_events = {
        "events": [
            {"id": "1", "data": {"message": "test1"}},
            {"id": "2", "data": {"message": "test2"}}
        ],
        "offset": 0,
        "limit": 10
    }

    with patch.object(client.session, 'get', return_value=mock_response(200, test_events)):
        response = await client.get_events("test-topic", "test-sub")

        assert isinstance(response, GetEventsResponse)
        assert len(response.events) == 2
        assert response.offset == 0
        assert response.limit == 10
        assert isinstance(response.events[0], Event)
        assert response.events[0].data["message"] == "test1"


@pytest.mark.asyncio
async def test_get_events_failure(client, mock_response):
    with patch.object(client.session, 'get', return_value=mock_response(400, {})):
        with pytest.raises(SailhouseError):
            await client.get_events("test-topic", "test-sub")


@pytest.mark.asyncio
async def test_publish_success(client, mock_response):
    test_data = {"message": "test"}
    scheduled_time = datetime.now()
    metadata = {"key": "value"}

    with patch.object(client.session, 'post', return_value=mock_response(201, {})):
        await client.publish(
            "test-topic",
            test_data,
            scheduled_time=scheduled_time,
            metadata=metadata
        )
        # Test passes if no exception is raised


@pytest.mark.asyncio
async def test_publish_failure(client, mock_response):
    with patch.object(client.session, 'post', return_value=mock_response(400, {})):
        with pytest.raises(SailhouseError):
            await client.publish("test-topic", {"message": "test"})


@pytest.mark.asyncio
async def test_acknowledge_message_success(client, mock_response):
    with patch.object(client.session, 'post', return_value=mock_response(204, {})):
        await client.acknowledge_message("test-topic", "test-sub", "event-id")
        # Test passes if no exception is raised


@pytest.mark.asyncio
async def test_acknowledge_message_failure(client, mock_response):
    with patch.object(client.session, 'post', return_value=mock_response(400, {})):
        with pytest.raises(SailhouseError):
            await client.acknowledge_message("test-topic", "test-sub", "event-id")


@pytest.mark.asyncio
async def test_pull_success(client, mock_response):
    test_event = {
        "id": "1",
        "data": {"message": "test1"}
    }

    with patch.object(client.session, 'get', return_value=mock_response(200, test_event)):
        event = await client.pull("test-topic", "test-sub")

        assert isinstance(event, Event)
        assert event.id == "1"
        assert event.data == {"message": "test1"}
        assert event._topic == "test-topic"
        assert event._subscription == "test-sub"


@pytest.mark.asyncio
async def test_pull_no_message(client, mock_response):
    with patch.object(client.session, 'get', return_value=mock_response(204)):
        event = await client.pull("test-topic", "test-sub")
        assert event is None


@pytest.mark.asyncio
async def test_pull_failure(client, mock_response):
    with patch.object(client.session, 'get', return_value=mock_response(400, {})):
        with pytest.raises(SailhouseError):
            await client.pull("test-topic", "test-sub")


@pytest.mark.asyncio
async def test_subscribe_handler_called(client, mock_response):
    handler = AsyncMock()

    # Mock pull to return one event and then None
    pull_mock = AsyncMock()
    pull_mock.side_effect = [
        Event(
            id="1",
            data={"message": "test1"},
            _topic="test-topic",
            _subscription="test-sub",
            _client=client
        ),
        None
    ]

    with patch.object(client, 'pull', pull_mock):
        # Create a task for the subscription
        task = asyncio.create_task(
            client.subscribe(
                "test-topic",
                "test-sub",
                handler,
                polling_interval=0.1,
                exit_on_error=True
            )
        )

        # Wait a short time to allow the handler to be called
        await asyncio.sleep(0.2)

        # Cancel the task
        task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            pass

        # Verify handler was called exactly once
        handler.assert_called_once()


@pytest.mark.asyncio
async def test_subscribe_with_error_handler(client):
    error_handler = Mock()  # Changed from AsyncMock to Mock since we're not awaiting it
    handler = AsyncMock()

    # Create a mock that raises an exception
    pull_mock = AsyncMock(side_effect=Exception("Test error"))

    with patch.object(client, 'pull', pull_mock):
        task = asyncio.create_task(
            client.subscribe(
                "test-topic",
                "test-sub",
                handler,
                polling_interval=0.1,
                on_error=error_handler,
                exit_on_error=True
            )
        )

        # Wait a short time for the error handler to be called
        await asyncio.sleep(0.2)

        # Cancel the task
        task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            pass

        # Verify error handler was called
        error_handler.assert_called_once()


@pytest.mark.asyncio
async def test_subscribe_continuous_polling(client):
    handler = AsyncMock()

    # Mock pull to return None (simulating no messages)
    pull_mock = AsyncMock(return_value=None)

    with patch.object(client, 'pull', pull_mock):
        task = asyncio.create_task(
            client.subscribe(
                "test-topic",
                "test-sub",
                handler,
                polling_interval=0.1
            )
        )

        # Wait for a few polling intervals
        await asyncio.sleep(0.3)

        # Cancel the task
        task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            pass

        # Verify handler was not called (since no messages were returned)
        handler.assert_not_called()
        # Verify pull was called multiple times
        assert pull_mock.call_count > 1
