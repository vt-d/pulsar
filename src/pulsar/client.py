import asyncio
import logging
import re
from typing import List, Callable, Optional, Dict, Any
import signal
import aiohttp

from .gateway.connection import GatewayConnection
from .gateway.events import Intent, Event

logger = logging.getLogger(__name__)

class Client:
    """
    The main client class for interacting with the Discord API.

    This class manages the connection to the Discord Gateway and provides
    an interface for adding event handlers and starting the client.
    """

    def __init__(self, token: str, intents: List[Intent]):
        self.token = token
        self.intents = intents
        self.gateway: Optional[GatewayConnection] = None
        self._loop = asyncio.get_event_loop()
        self._running = False
        self.session: Optional[aiohttp.ClientSession] = None
        self.base_url = "https://discord.com/api/v10"
        self._event_handlers: Dict[str, List[Callable[[Event], None]]] = {}

    async def _init_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()

    def run(self):
        """Run the client and connect to the Discord Gateway."""
        try:
            logger.info("Starting client")
            self._loop.run_until_complete(self.start())
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt")
        except Exception as e:
            logger.exception(f"Unexpected error: {e}")
        finally:
            logger.info("Shutting down client")
            self._loop.run_until_complete(self.close())
            self._loop.close()

    async def start(self):
        """Start the client and connect to the Discord Gateway."""
        self._validate_token_and_intents()
        await self._init_session()
        self._running = True
        for sig in (signal.SIGINT, signal.SIGTERM):
            self._loop.add_signal_handler(sig, self._signal_handler)
        logger.info("Connecting to Gateway")
        retry_interval = 1
        max_retry_interval = 60
        while self._running:
            try:
                if not self.gateway:
                    self.gateway = await GatewayConnection.create(self.token, self.intents)
                    self._register_stored_event_handlers()
                await self.gateway.connect()
            except ConnectionError as e:
                logger.error(f"Connection error: {e}")
            except Exception as e:
                logger.exception(f"Unexpected error in gateway connection: {e}")
            
            if self._running:
                logger.info(f"Reconnecting in {retry_interval} seconds...")
                await asyncio.sleep(retry_interval)
                retry_interval = min(retry_interval * 2, max_retry_interval)
            else:
                break

    def _signal_handler(self):
        """Handle termination signals."""
        self._running = False
        asyncio.create_task(self.close())

    async def close(self):
        """Close the connection to the Discord Gateway."""
        if self.gateway:
            await self.gateway.close()
        if self.session and not self.session.closed:
            await self.session.close()
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        [task.cancel() for task in tasks]
        await asyncio.gather(*tasks, return_exceptions=True)

    def event(self, coro: Callable[[Event], None]):
        """
        A decorator that registers an event handler.

        Usage:
            @client.event
            async def on_message_create(event: MessageCreateEvent):
                print(f"Received message: {event.content}")
        """
        event_name = coro.__name__[3:].upper()
        if event_name not in self._event_handlers:
            self._event_handlers[event_name] = []
        self._event_handlers[event_name].append(coro)
        return coro

    def _register_stored_event_handlers(self):
        """Register stored event handlers to the GatewayConnection."""
        if self.gateway:
            for event_name, handlers in self._event_handlers.items():
                for handler in handlers:
                    self.gateway.add_event_handler(event_name, handler)

    def _validate_token_and_intents(self):
        if not self.token or len(self.token) < 50:  # Simple length check
            raise ValueError("Invalid bot token: Token seems too short")
        
        required_intents = [Intent.GUILDS, Intent.GUILD_MESSAGES, Intent.MESSAGE_CONTENT]
        missing_intents = [intent for intent in required_intents if intent not in self.intents]
        if missing_intents:
            raise ValueError(f"Missing required intents: {missing_intents}")

    @property
    def user_id(self) -> Optional[str]:
        return self.gateway.user_id if self.gateway else None

    async def _request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        await self._init_session()
        headers = {
            "Authorization": f"Bot {self.token}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/{endpoint}"
        
        async with self.session.request(method, url, headers=headers, **kwargs) as response:
            response.raise_for_status()
            return await response.json()

    async def get_user(self, user_id: str) -> Dict[str, Any]:
        return await self._request("GET", f"users/{user_id}")

    async def create_message(self, channel_id: str, content: str) -> Dict[str, Any]:
        payload = {"content": content}
        return await self._request("POST", f"channels/{channel_id}/messages", json=payload)

    async def connect_gateway(self):
        if not self.gateway:
            self.gateway = await GatewayConnection.create(self.token, self.intents)
            self._register_stored_event_handlers()
        await self.gateway.connect()

    # Add more API methods as needed
