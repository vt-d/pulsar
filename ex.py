import logging
from pulsar import Client, Intent
from pulsar.gateway.events import MessageCreateEvent, ReadyEvent

logging.basicConfig(level=logging.DEBUG)

TOKEN = "skibidi"
intents = [Intent.GUILDS, Intent.GUILD_MESSAGES, Intent.MESSAGE_CONTENT]
client = Client(TOKEN, intents)


@client.event
async def on_ready(event: ReadyEvent):
    print(f"Logged in as {event.user['username']}#{event.user['discriminator']}")


@client.event
async def on_message_create(event: MessageCreateEvent):
    if event.author["id"] != client.user_id:
        print(f"Message from {event.author['username']}: {event.content}")
        if event.content.lower() == "!hello":
            channel_id = event.channel_id
            await client.create_message(
                channel_id, f"Hello, {event.author['username']}!"
            )


if __name__ == "__main__":
    client.run()
