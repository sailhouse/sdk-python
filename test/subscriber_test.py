import pytest
import asyncio
from unittest.mock import AsyncMock, Mock, patch

from sailhouse import SailhouseClient, SailhouseSubscriber, SubscriberOptions, Event


@pytest.fixture
def client():
    return SailhouseClient(token="test-token")


@pytest.fixture
def mock_event(client):
    event = Event(
        id="test-event-id",
        data={"message": "test"},
        _topic="test-topic",
        _subscription="test-sub",
        _client=client
    )
    event.ack = AsyncMock()
    return event


def test_subscriber_options_creation():
    options = SubscriberOptions(per_subscription_processors=5)
    assert options.per_subscription_processors == 5


def test_subscriber_options_default():
    options = SubscriberOptions()
    assert options.per_subscription_processors == 1


def test_subscriber_creation_through_client(client):
    subscriber = client.subscriber()
    
    assert isinstance(subscriber, SailhouseSubscriber)
    assert subscriber.client is client
    assert subscriber.options.per_subscription_processors == 1
    assert len(subscriber.subscriptions) == 0
    assert not subscriber._running


def test_subscriber_creation_with_options(client):
    options = SubscriberOptions(per_subscription_processors=3)
    subscriber = client.subscriber(options)
    
    assert isinstance(subscriber, SailhouseSubscriber)
    assert subscriber.options.per_subscription_processors == 3


def test_subscriber_direct_creation(client):
    options = SubscriberOptions(per_subscription_processors=2)
    subscriber = SailhouseSubscriber(client, options)
    
    assert subscriber.client is client
    assert subscriber.options.per_subscription_processors == 2


def test_subscribe_method(client):
    subscriber = client.subscriber()
    handler = AsyncMock()
    
    subscriber.subscribe("test-topic", "test-subscription", handler)
    
    assert len(subscriber.subscriptions) == 1
    subscription = subscriber.subscriptions[0]
    assert subscription.topic == "test-topic"
    assert subscription.subscription == "test-subscription"
    assert subscription.handler is handler


def test_subscribe_multiple_subscriptions(client):
    subscriber = client.subscriber()
    handler1 = AsyncMock()
    handler2 = AsyncMock()
    
    subscriber.subscribe("topic1", "sub1", handler1)
    subscriber.subscribe("topic2", "sub2", handler2)
    
    assert len(subscriber.subscriptions) == 2
    assert subscriber.subscriptions[0].topic == "topic1"
    assert subscriber.subscriptions[1].topic == "topic2"


@pytest.mark.asyncio
async def test_start_and_stop_subscriber(client):
    subscriber = client.subscriber()
    handler = AsyncMock()
    
    subscriber.subscribe("test-topic", "test-sub", handler)
    
    # Mock pull to return None (no events)
    with patch.object(client, 'pull', new_callable=AsyncMock) as mock_pull:
        mock_pull.return_value = None
        
        # Start the subscriber
        start_task = asyncio.create_task(subscriber.start())
        
        # Give it a moment to start
        await asyncio.sleep(0.1)
        assert subscriber._running is True
        assert len(subscriber._tasks) == 1  # One processor per subscription
        
        # Stop the subscriber
        await subscriber.stop()
        assert subscriber._running is False
        assert len(subscriber._tasks) == 0
        
        # Clean up the start task
        start_task.cancel()
        try:
            await start_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_subscriber_processes_events(client, mock_event):
    subscriber = client.subscriber()
    handler = AsyncMock()
    
    subscriber.subscribe("test-topic", "test-sub", handler)
    
    with patch.object(client, 'pull', new_callable=AsyncMock) as mock_pull:
        # Return one event, then None
        mock_pull.side_effect = [mock_event, None]
        
        # Start subscriber in background
        start_task = asyncio.create_task(subscriber.start())
        
        # Wait for event processing
        await asyncio.sleep(0.2)
        
        # Verify handler was called
        handler.assert_called_once_with(mock_event)
        # Verify event was acknowledged
        mock_event.ack.assert_called_once()
        
        # Stop subscriber
        await subscriber.stop()
        start_task.cancel()
        try:
            await start_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_subscriber_multiple_processors(client, mock_event):
    options = SubscriberOptions(per_subscription_processors=3)
    subscriber = client.subscriber(options)
    handler = AsyncMock()
    
    subscriber.subscribe("test-topic", "test-sub", handler)
    
    with patch.object(client, 'pull', new_callable=AsyncMock) as mock_pull:
        mock_pull.return_value = None
        
        # Start subscriber
        start_task = asyncio.create_task(subscriber.start())
        
        # Give it a moment to start
        await asyncio.sleep(0.1)
        
        # Should have 3 processor tasks (3 processors per subscription)
        assert len(subscriber._tasks) == 3
        
        # Stop subscriber
        await subscriber.stop()
        start_task.cancel()
        try:
            await start_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_subscriber_multiple_subscriptions_multiple_processors(client):
    options = SubscriberOptions(per_subscription_processors=2)
    subscriber = client.subscriber(options)
    handler1 = AsyncMock()
    handler2 = AsyncMock()
    
    subscriber.subscribe("topic1", "sub1", handler1)
    subscriber.subscribe("topic2", "sub2", handler2)
    
    with patch.object(client, 'pull', new_callable=AsyncMock) as mock_pull:
        mock_pull.return_value = None
        
        start_task = asyncio.create_task(subscriber.start())
        await asyncio.sleep(0.1)
        
        # Should have 4 processor tasks (2 subscriptions × 2 processors each)
        assert len(subscriber._tasks) == 4
        
        await subscriber.stop()
        start_task.cancel()
        try:
            await start_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_subscriber_handler_exception_no_ack(client, mock_event):
    subscriber = client.subscriber()
    handler = AsyncMock()
    handler.side_effect = Exception("Handler failed")
    
    subscriber.subscribe("test-topic", "test-sub", handler)
    
    with patch.object(client, 'pull', new_callable=AsyncMock) as mock_pull:
        # Return one event, then None
        mock_pull.side_effect = [mock_event, None]
        
        start_task = asyncio.create_task(subscriber.start())
        await asyncio.sleep(0.2)
        
        # Handler was called but failed
        handler.assert_called_once_with(mock_event)
        # Event should NOT be acknowledged when handler fails
        mock_event.ack.assert_not_called()
        
        await subscriber.stop()
        start_task.cancel()
        try:
            await start_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_subscriber_pull_exception_continues(client):
    subscriber = client.subscriber()
    handler = AsyncMock()
    
    subscriber.subscribe("test-topic", "test-sub", handler)
    
    with patch.object(client, 'pull', new_callable=AsyncMock) as mock_pull:
        # Multiple calls: first raises exception, then returns None repeatedly
        mock_pull.side_effect = [Exception("Pull failed")] + [None] * 10
        
        start_task = asyncio.create_task(subscriber.start())
        await asyncio.sleep(1.5)  # Give more time for retries
        
        # Should have attempted pull multiple times despite first failure
        assert mock_pull.call_count >= 2
        # Handler should not have been called
        handler.assert_not_called()
        
        await subscriber.stop()
        start_task.cancel()
        try:
            await start_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_subscriber_start_when_already_running(client):
    subscriber = client.subscriber()
    handler = AsyncMock()
    subscriber.subscribe("test-topic", "test-sub", handler)
    
    with patch.object(client, 'pull', new_callable=AsyncMock) as mock_pull:
        mock_pull.return_value = None
        
        # Start first time
        start_task1 = asyncio.create_task(subscriber.start())
        await asyncio.sleep(0.1)
        
        initial_task_count = len(subscriber._tasks)
        
        # Start again - should not create duplicate tasks
        start_task2 = asyncio.create_task(subscriber.start())
        await asyncio.sleep(0.1)
        
        assert len(subscriber._tasks) == initial_task_count
        
        await subscriber.stop()
        start_task1.cancel()
        start_task2.cancel()
        try:
            await asyncio.gather(start_task1, start_task2)
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_subscriber_continuous_processing(client):
    subscriber = client.subscriber()
    handler = AsyncMock()
    
    subscriber.subscribe("test-topic", "test-sub", handler)
    
    # Create multiple mock events
    events = [
        Event("id1", {"msg": "1"}, "test-topic", "test-sub", client),
        Event("id2", {"msg": "2"}, "test-topic", "test-sub", client),
        None  # No more events
    ]
    
    for event in events[:-1]:  # Add ack mock to real events
        event.ack = AsyncMock()
    
    with patch.object(client, 'pull', new_callable=AsyncMock) as mock_pull:
        mock_pull.side_effect = events
        
        start_task = asyncio.create_task(subscriber.start())
        await asyncio.sleep(0.3)  # Give time to process events
        
        # Should have processed both events
        assert handler.call_count >= 2
        
        await subscriber.stop()
        start_task.cancel()
        try:
            await start_task
        except asyncio.CancelledError:
            pass