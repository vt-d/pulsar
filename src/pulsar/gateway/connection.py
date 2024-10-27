import asyncio
import json
import logging
from typing import Any, Callable, Dict, List, Optional

import aiohttp

from .events import Intent, OpCode, Event, create_event

# dont ask me why i document hidden methods

logger = logging.getLogger(__name__)


class GatewayConnection:
    """
    Manages the WebSocket connection to the Discord Gateway.

    This class handles connecting to the gateway, sending and receiving messages,
    and maintaining the connection through heartbeats.
    """

    def __init__(self, token: str, intents: List[Intent]):
        self.token = token
        self.intents = intents
        self.session_id: Optional[str] = None
        self.sequence: Optional[int] = None
        self.heartbeat_interval: Optional[float] = None
        self.ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.heartbeat_task: Optional[asyncio.Task] = None
        self.event_handlers: Dict[str, List[Callable[[Event], None]]] = {}
        self.user_id: Optional[str] = None
        self.session: Optional[aiohttp.ClientSession] = None

    @classmethod
    async def create(cls, token: str, intents: List[Intent]):
        connection = cls(token, intents)
        connection.session = aiohttp.ClientSession()
        return connection

    async def connect(self):
        """Establish a connection to the Discord Gateway."""
        if not self.session:
            raise RuntimeError(
                "GatewayConnection not initialized. Use 'create' method."
            )

        gateway_url = "wss://gateway.discord.gg/?v=10&encoding=json"
        async with self.session.ws_connect(gateway_url) as ws:
            self.ws = ws
            logger.info("Connected to Gateway")
            await self._handle_messages()

    async def _handle_messages(self):
        """Handle incoming messages from the gateway."""
        async for msg in self.ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                await self._process_message(data)
            elif msg.type == aiohttp.WSMsgType.CLOSED:
                logger.warning(f"WebSocket closed with code {self.ws.close_code}")
                break
            elif msg.type == aiohttp.WSMsgType.ERROR:
                logger.error(f"WebSocket error: {self.ws.exception()}")
                break

    async def _process_message(self, data: Dict[str, Any]):
        """Process a message received from the gateway."""
        try:
            op = OpCode(data["op"])
            logger.debug(f"Received opcode: {op}")
            if op == OpCode.HELLO:
                await self._handle_hello(data)
            elif op == OpCode.DISPATCH:
                await self._handle_dispatch(data)
            elif op == OpCode.HEARTBEAT:
                await self._send_heartbeat()
            elif op == OpCode.RECONNECT:
                await self._handle_reconnect()
            elif op == OpCode.INVALID_SESSION:
                await self._handle_invalid_session(data)
            elif op == OpCode.HEARTBEAT_ACK:
                logger.debug("Received HEARTBEAT_ACK")
            else:
                logger.warning(f"Unhandled opcode: {op}")
        except Exception as e:
            logger.exception(f"Error processing message: {e}")

    async def _handle_hello(self, data: Dict[str, Any]):
        """Handle the HELLO opcode by starting heartbeat and identifying."""
        try:
            self.heartbeat_interval = data["d"]["heartbeat_interval"] / 1000
            logger.debug(
                f"Received heartbeat interval: {self.heartbeat_interval} seconds"
            )
            self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            logger.debug("Starting heartbeat loop")
            await self._identify()
            logger.debug("Sent IDENTIFY payload")
        except Exception as e:
            logger.exception(f"Error handling HELLO: {e}")

    async def _handle_dispatch(self, data: Dict[str, Any]):
        """Handle dispatch events."""
        try:
            self.sequence = data["s"]
            event_name = data["t"]
            logger.debug(f"Received dispatch event: {event_name}")
            event = create_event(event_name, data["d"])
            if event_name == "READY":
                self.user_id = event.user["id"]
            self._dispatch_event(event_name, event)
        except Exception as e:
            logger.exception(f"Error handling dispatch: {e}")

    async def _identify(self):
        """Send the IDENTIFY payload to the gateway."""
        payload = {
            "op": OpCode.IDENTIFY.value,
            "d": {
                "token": self.token,
                "intents": sum(intent.value for intent in self.intents),
                "properties": {
                    "$os": "linux",
                    "$browser": "pulsar",
                    "$device": "pulsar",
                },
                "compress": False,
                "large_threshold": 250,
            },
        }
        logger.debug(
            f"Sending IDENTIFY payload with intents: {sum(intent.value for intent in self.intents)}"
        )
        await self._send_json(payload)

        # Wait for READY or INVALID_SESSION event
        try:
            async with asyncio.timeout(30):  # Set a timeout for waiting
                async for msg in self.ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        logger.debug(f"Received message during IDENTIFY: {data}")
                        op = OpCode(data["op"])
                        if op == OpCode.DISPATCH and data["t"] == "READY":
                            logger.info("Received READY event")
                            self.session_id = data["d"]["session_id"]
                            return
                        elif op == OpCode.INVALID_SESSION:
                            logger.warning("Received INVALID_SESSION")
                            await self._handle_invalid_session(data)
                            return
                        else:
                            logger.debug(
                                f"Received unexpected opcode during IDENTIFY: {op}"
                            )
                    elif msg.type == aiohttp.WSMsgType.CLOSED:
                        logger.error(
                            f"WebSocket closed during IDENTIFY with code {self.ws.close_code}"
                        )
                        break
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        logger.error(
                            f"WebSocket error during IDENTIFY: {self.ws.exception()}"
                        )
                        break
        except asyncio.TimeoutError:
            logger.error("Timed out waiting for READY or INVALID_SESSION")
        except Exception as e:
            logger.exception(f"Error during IDENTIFY: {e}")

        # If we reach here, something went wrong
        raise ConnectionError("Failed to complete IDENTIFY process")

    async def _send_heartbeat(self):
        """Send a heartbeat to the gateway."""
        payload = {"op": OpCode.HEARTBEAT.value, "d": self.sequence}
        await self._send_json(payload)

    async def _heartbeat_loop(self):
        """Continuously send heartbeats at the specified interval."""
        while True:
            await asyncio.sleep(self.heartbeat_interval)
            await self._send_heartbeat()

    async def _send_json(self, data: Dict[str, Any]):
        """Send a JSON payload to the gateway."""
        try:
            await self.ws.send_json(data)
            logger.debug(f"Sent payload: {data['op']}")
        except Exception as e:
            logger.exception(f"Error sending JSON: {e}")

    async def _handle_disconnect(self):
        """Handle disconnection from the gateway."""
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
        logger.info("Disconnected from Gateway")
        if self.ws:
            await self.ws.close()

    async def _handle_reconnect(self):
        """Handle a RECONNECT request from the gateway."""
        logger.info("Received RECONNECT request")
        await self._handle_disconnect()
        await self.connect()

    async def _handle_invalid_session(self, data: Dict[str, Any]):
        """Handle an INVALID_SESSION opcode."""
        can_resume = data.get("d", False)
        if can_resume:
            logger.info("Attempting to resume session")
            await self._resume()
        else:
            logger.info("Cannot resume session, reconnecting...")
            self.session_id = None
            self.sequence = None
            await asyncio.sleep(1)
            await self._identify()

    async def _resume(self):
        """Send a RESUME payload to the gateway."""
        if not self.session_id:
            logger.warning("No session ID available for resume, identifying instead")
            await self._identify()
            return

        payload = {
            "op": OpCode.RESUME.value,
            "d": {
                "token": self.token,
                "session_id": self.session_id,
                "seq": self.sequence,
            },
        }
        logger.debug("Sending RESUME payload")
        await self._send_json(payload)

    def add_event_handler(self, event_name: str, handler: Callable[[Event], None]):
        """Add an event handler for a specific event."""
        if event_name not in self.event_handlers:
            self.event_handlers[event_name] = []
        self.event_handlers[event_name].append(handler)

    def _dispatch_event(self, event_name: str, event: Event):
        """Dispatch an event to all registered handlers."""
        handlers = self.event_handlers.get(event_name, [])
        for handler in handlers:
            try:
                asyncio.create_task(handler(event))
            except Exception as e:
                logger.exception(f"Error in event handler for {event_name}: {e}")

    async def close(self):
        """Close the gateway connection."""
        if self.ws:
            await self.ws.close()
        if self.session:
            await self.session.close()
