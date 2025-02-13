import asyncio
import os
from sailhouse import SailhouseClient


async def main():
    client = SailhouseClient(os.getenv("SAILHOUSE_TOKEN"))

    # Send a message to a topic
    await client.publish(
        topic="quick-test",
        data={"message": "Hello, World!", "number": 42}
    )

    print("🚀 Message sent! 📭")

    await asyncio.sleep(1)

    events = await client.get_events(
        topic="quick-test",
        subscription="test-python-sub"
    )
    for event in events.events:
        print(f"🎉 Received event: {event.data} 📫")

        await event.ack()

if __name__ == "__main__":
    asyncio.run(main())
