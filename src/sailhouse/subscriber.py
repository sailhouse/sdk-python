from dataclasses import dataclass
from typing import Dict, Any, Optional, Callable, Awaitable, List
from .client import Event, SailhouseClient
import asyncio


@dataclass
class SubscriberOptions:
    per_subscription_processors: int = 1


SubscriptionHandler = Callable[[Event], Awaitable[None]]


@dataclass
class Subscription:
    topic: str
    subscription: str
    handler: SubscriptionHandler


class SailhouseSubscriber:
    def __init__(self, client: SailhouseClient, options: Optional[SubscriberOptions] = None):
        self.client = client
        self.options = options or SubscriberOptions()
        self.subscriptions: List[Subscription] = []
        self._running = False
        self._tasks: List[asyncio.Task] = []
    
    def subscribe(self, topic: str, subscription: str, handler: SubscriptionHandler) -> None:
        """Register a topic/subscription handler"""
        self.subscriptions.append(Subscription(
            topic=topic,
            subscription=subscription,
            handler=handler
        ))
    
    async def start(self) -> None:
        """Start processing events for all registered subscriptions"""
        if self._running:
            return
        
        self._running = True
        
        # Create processor tasks for each subscription
        for subscription in self.subscriptions:
            for _ in range(self.options.per_subscription_processors):
                task = asyncio.create_task(
                    self._process_subscription(subscription)
                )
                self._tasks.append(task)
        
        # Wait for all tasks to complete (they run indefinitely until stopped)
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
    
    async def stop(self) -> None:
        """Stop processing events"""
        self._running = False
        
        # Cancel all running tasks
        for task in self._tasks:
            task.cancel()
        
        # Wait for tasks to be cancelled
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        
        self._tasks.clear()
    
    async def _process_subscription(self, subscription: Subscription) -> None:
        """Process events for a single subscription"""
        while self._running:
            try:
                # Pull an event
                event = await self.client.pull(subscription.topic, subscription.subscription)
                
                if event:
                    try:
                        # Process the event with the handler
                        await subscription.handler(event)
                        # Automatically acknowledge the event
                        await event.ack()
                    except Exception as e:
                        # If handler fails, we don't acknowledge the event
                        # This allows for retry logic at the server level
                        # Log the error but continue processing
                        pass
                    
                    # Continue immediately to try to fetch another event
                    continue
                
                # No events available, wait before polling again
                await asyncio.sleep(1.0)
                
            except Exception as e:
                # Error in pulling events, wait before retrying
                await asyncio.sleep(1.0)
                continue