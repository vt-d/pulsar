import logging
from enum import Enum, auto
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class Intent(Enum):
    GUILDS = 1 << 0
    GUILD_MEMBERS = 1 << 1
    GUILD_BANS = 1 << 2
    GUILD_EMOJIS = 1 << 3
    GUILD_INTEGRATIONS = 1 << 4
    GUILD_WEBHOOKS = 1 << 5
    GUILD_INVITES = 1 << 6
    GUILD_VOICE_STATES = 1 << 7
    GUILD_PRESENCES = 1 << 8
    GUILD_MESSAGES = 1 << 9
    GUILD_MESSAGE_REACTIONS = 1 << 10
    GUILD_MESSAGE_TYPING = 1 << 11
    DIRECT_MESSAGES = 1 << 12
    DIRECT_MESSAGE_REACTIONS = 1 << 13
    DIRECT_MESSAGE_TYPING = 1 << 14
    MESSAGE_CONTENT = 1 << 15
    GUILD_SCHEDULED_EVENTS = 1 << 16


class OpCode(Enum):
    DISPATCH = 0
    HEARTBEAT = 1
    IDENTIFY = 2
    PRESENCE_UPDATE = 3
    VOICE_STATE_UPDATE = 4
    RESUME = 6
    RECONNECT = 7
    REQUEST_GUILD_MEMBERS = 8
    INVALID_SESSION = 9
    HELLO = 10
    HEARTBEAT_ACK = 11


class Event:
    """Base class for all gateway events."""

    def __init__(self, data: Dict[str, Any]):
        self.data = data


class ReadyEvent(Event):
    """Event received when the client has successfully connected to the gateway."""

    def __init__(self, data: Dict[str, Any]):
        super().__init__(data)
        self.v: int = data["v"]
        self.user: Dict[str, Any] = data["user"]
        self.guilds: List[Dict[str, Any]] = data["guilds"]
        self.session_id: str = data["session_id"]
        self.resume_gateway_url: str = data["resume_gateway_url"]
        self.shard: Optional[List[int]] = data.get("shard")
        self.application: Dict[str, Any] = data["application"]


class MessageCreateEvent(Event):
    """Event received when a message is created."""

    def __init__(self, data: Dict[str, Any]):
        super().__init__(data)
        self.id: str = data["id"]
        self.content: str = data["content"]
        self.author: Dict[str, Any] = data["author"]
        self.channel_id: str = data["channel_id"]
        self.guild_id: Optional[str] = data.get("guild_id")


def create_event(event_name: str, data: Dict[str, Any]) -> Event:
    """Factory function to create the appropriate event object based on the event name."""
    event_classes = {
        "READY": ReadyEvent,
        "MESSAGE_CREATE": MessageCreateEvent,
    }
    event_class = event_classes.get(event_name, Event)
    return event_class(data)


async def handle_event(event_data):
    event_type = event_data.get("t")
    data = event_data.get("d", {})

    if event_type == "READY":
        user = data.get("user", {})
        username = user.get("username")
        discriminator = user.get("discriminator")
        logger.info(f"Connected as {username}#{discriminator}")
    elif event_type == "MESSAGE_CREATE":
        content = data.get("content")
        logger.info(f"Message received: {content}")
    else:
        logger.debug(f"Unhandled event type: {event_type}")
