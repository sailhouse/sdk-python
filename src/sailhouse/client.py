from dataclasses import dataclass
from typing import Generic, List, Optional, Dict, Any, Callable, TypeVar
from .exceptions import SailhouseError
from datetime import datetime
from contextlib import asynccontextmanager

import requests
import websockets
import asyncio
import json

T = TypeVar('T')


@dataclass
class Event(Generic[T]):
    id: str
    data: Dict[str, Any]
    _topic: str
    _subscription: str
    _client: 'SailhouseClient'

    def as_type(self, cls: type[T]) -> T:
        """Convert event data to specified type"""
        return cls(**self.data)

    async def ack(self) -> None:
        """Acknowledge the event"""
        await self._client.acknowledge_message(
            self._topic,
            self._subscription,
            self.id
        )


@dataclass
class GetEventsResponse:
    events: List[Event]
    offset: int
    limit: int


class SailhouseClient:
    BASE_URL = "https://api.sailhouse.dev"

    def __init__(
        self,
        token: str,
        timeout: float = 5.0,
        base_url: Optional[str] = None
    ):
        self.token = token
        self.timeout = timeout
        self.base_url = base_url or self.BASE_URL
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": token,
            "x-source": "sailhouse-python"
        })

    async def get_events(
        self,
        topic: str,
        subscription: str,
        *,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        time_window: Optional[str] = None
    ) -> GetEventsResponse:
        """Fetch events for a topic/subscription pair"""
        params = {}
        if limit is not None:
            params['limit'] = limit
        if offset is not None:
            params['offset'] = offset
        if time_window is not None:
            params['time_window'] = time_window

        url = f"{self.BASE_URL}/topics/{topic}/subscriptions/{subscription}/events"

        response = self.session.get(url, params=params, timeout=self.timeout)
        if response.status_code != 200:
            raise SailhouseError(
                f"Failed to get events: {response.status_code}")

        data = response.json()
        events = [
            Event(
                id=e['id'],
                data=e['data'],
                _topic=topic,
                _subscription=subscription,
                _client=self
            )
            for e in data['events']
        ]

        return GetEventsResponse(
            events=events,
            offset=data.get('offset', 0),
            limit=data.get('limit', 0)
        )

    async def publish(
        self,
        topic: str,
        data: Dict[str, Any],
        *,
        scheduled_time: Optional[datetime] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Publish an event to a topic"""
        url = f"{self.BASE_URL}/topics/{topic}/events"

        body = {"data": data}
        if scheduled_time:
            body["send_at"] = scheduled_time.isoformat()
        if metadata:
            body["metadata"] = metadata

        response = self.session.post(
            url,
            json=body,
            timeout=self.timeout
        )

        if response.status_code != 201:
            raise SailhouseError(
                f"Failed to publish message: {response.status_code} - {response.text}"
            )

    async def acknowledge_message(
        self,
        topic: str,
        subscription: str,
        event_id: str
    ) -> None:
        """Acknowledge a message"""
        url = f"{self.BASE_URL}/topics/{topic}/subscriptions/{subscription}/events/{event_id}"

        response = self.session.post(url, timeout=self.timeout)
        if response.status_code not in (200, 204):
            raise SailhouseError(
                f"Failed to acknowledge message: {response.status_code}")

    async def subscribe(
        self,
        topic: str,
        subscription: str,
        handler: Callable[[Event], None],
        *,
        polling_interval: float = 5.0,
        on_error: Optional[Callable[[Exception], None]] = None,
        exit_on_error: bool = False
    ):
        """Subscribe to events with polling"""
        while True:
            try:
                events = await self.get_events(topic, subscription)
                for event in events.events:
                    await handler(event)
                await asyncio.sleep(polling_interval)
            except Exception as e:
                if on_error:
                    on_error(e)
                if exit_on_error:
                    break
                continue
