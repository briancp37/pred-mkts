"""
Stub HTTP server for integration testing rate limiter behavior.
[CTX:PBI-0:0-4:STUB]

This module provides a configurable stub server that simulates API responses
with various status codes and rate limit headers for testing purposes.

Features:
- Configurable response patterns (200, 429, 500)
- Rate limit header support (X-RateLimit-*)
- Retry-After header support
- Queue-based response configuration
- Async operation for integration with pytest-asyncio
"""
import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from aiohttp import web

logger = logging.getLogger(__name__)


# [CTX:PBI-0:0-4:STUB] Response configuration
@dataclass
class StubResponse:
    """Configuration for a single stub response."""
    
    status: int = 200
    headers: Dict[str, str] = field(default_factory=dict)
    body: str = '{"status": "ok"}'
    delay: float = 0.0  # Artificial delay in seconds
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for debugging."""
        return {
            "status": self.status,
            "headers": self.headers,
            "body": self.body,
            "delay": self.delay,
        }


# [CTX:PBI-0:0-4:STUB] Stub server implementation
class StubServer:
    """
    Configurable stub HTTP server for testing.
    
    The server maintains a queue of response configurations and serves them
    in order. Once the queue is empty, it defaults to returning 200 OK.
    
    Example:
        server = StubServer(port=8888)
        await server.start()
        
        # Configure responses
        server.enqueue_response(StubResponse(status=200, headers={...}))
        server.enqueue_response(StubResponse(status=429, headers={...}))
        
        # Make requests to http://localhost:8888/...
        
        await server.stop()
    """
    
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8888,
        default_response: Optional[StubResponse] = None
    ):
        """
        Initialize stub server.
        
        Args:
            host: Host to bind to
            port: Port to bind to
            default_response: Default response when queue is empty
        """
        self.host = host
        self.port = port
        self.default_response = default_response or StubResponse(
            status=200,
            headers={
                "X-RateLimit-Limit": "100",
                "X-RateLimit-Remaining": "99",
                "X-RateLimit-Reset": str(int(asyncio.get_event_loop().time()) + 60),
            },
            body='{"status": "ok"}'
        )
        
        # Response queue
        self._response_queue: deque[StubResponse] = deque()
        self._queue_lock = asyncio.Lock()
        
        # Request tracking
        self.request_count = 0
        self.request_history: List[Dict] = []
        
        # Server state
        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
    
    async def _handle_request(self, request: web.Request) -> web.Response:
        """
        Handle incoming HTTP request.
        
        Args:
            request: aiohttp request object
            
        Returns:
            Configured response
        """
        # Track request
        self.request_count += 1
        self.request_history.append({
            "method": request.method,
            "path": request.path,
            "headers": dict(request.headers),
            "timestamp": asyncio.get_event_loop().time(),
        })
        
        logger.debug(
            f"[CTX:PBI-0:0-4:STUB] Request #{self.request_count}: "
            f"{request.method} {request.path}"
        )
        
        # Get next response from queue or use default
        async with self._queue_lock:
            if self._response_queue:
                response_config = self._response_queue.popleft()
            else:
                response_config = self.default_response
        
        # Apply artificial delay if configured
        if response_config.delay > 0:
            await asyncio.sleep(response_config.delay)
        
        logger.debug(
            f"[CTX:PBI-0:0-4:STUB] Response #{self.request_count}: "
            f"{response_config.status}"
        )
        
        # Build response
        return web.Response(
            status=response_config.status,
            headers=response_config.headers,
            text=response_config.body,
            content_type="application/json"
        )
    
    def enqueue_response(self, response: StubResponse) -> None:
        """
        Add response to queue.
        
        Args:
            response: Response configuration to enqueue
        """
        self._response_queue.append(response)
        logger.debug(
            f"[CTX:PBI-0:0-4:STUB] Enqueued response: {response.to_dict()}"
        )
    
    def enqueue_responses(self, responses: List[StubResponse]) -> None:
        """
        Add multiple responses to queue.
        
        Args:
            responses: List of response configurations
        """
        for response in responses:
            self.enqueue_response(response)
    
    def clear_queue(self) -> None:
        """Clear response queue."""
        self._response_queue.clear()
        logger.debug("[CTX:PBI-0:0-4:STUB] Cleared response queue")
    
    def reset_stats(self) -> None:
        """Reset request tracking statistics."""
        self.request_count = 0
        self.request_history.clear()
        logger.debug("[CTX:PBI-0:0-4:STUB] Reset stats")
    
    async def start(self) -> None:
        """Start the stub server."""
        if self._runner is not None:
            logger.warning("[CTX:PBI-0:0-4:STUB] Server already started")
            return
        
        # Create application
        self._app = web.Application()
        
        # Add catch-all route
        self._app.router.add_route("*", "/{tail:.*}", self._handle_request)
        
        # Start server
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        
        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()
        
        logger.info(
            f"[CTX:PBI-0:0-4:STUB] Stub server started on "
            f"http://{self.host}:{self.port}"
        )
    
    async def stop(self) -> None:
        """Stop the stub server."""
        if self._runner is None:
            logger.warning("[CTX:PBI-0:0-4:STUB] Server not started")
            return
        
        await self._runner.cleanup()
        self._runner = None
        self._site = None
        self._app = None
        
        logger.info("[CTX:PBI-0:0-4:STUB] Stub server stopped")
    
    def get_url(self, path: str = "/") -> str:
        """
        Get full URL for a path on this server.
        
        Args:
            path: Path to append
            
        Returns:
            Full URL
        """
        if not path.startswith("/"):
            path = "/" + path
        return f"http://{self.host}:{self.port}{path}"


# [CTX:PBI-0:0-4:STUB] Helper functions for common scenarios
def success_response(
    limit: int = 100,
    remaining: int = 99,
    reset_offset: int = 60
) -> StubResponse:
    """
    Create a successful response with rate limit headers.
    
    Args:
        limit: Rate limit
        remaining: Remaining requests
        reset_offset: Seconds until reset
        
    Returns:
        StubResponse configured for success
    """
    # Use a fixed timestamp for deterministic tests
    reset_time = 1000 + reset_offset
    
    return StubResponse(
        status=200,
        headers={
            "X-RateLimit-Limit": str(limit),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Reset": str(reset_time),
        },
        body='{"status": "ok", "data": []}'
    )


def throttle_response(retry_after: int = 30, include_rate_headers: bool = False) -> StubResponse:
    """
    Create a 429 throttle response.
    
    Args:
        retry_after: Retry-After value in seconds
        include_rate_headers: Whether to include X-RateLimit-* headers (may interfere with 429 handling)
        
    Returns:
        StubResponse configured for throttling
    """
    headers = {
        "Retry-After": str(retry_after),
    }
    
    # Only include rate limit headers if requested
    # Note: remaining=0 triggers exhaustion path before 429 path
    if include_rate_headers:
        headers.update({
            "X-RateLimit-Limit": "100",
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": str(1000 + retry_after),
        })
    
    return StubResponse(
        status=429,
        headers=headers,
        body='{"error": "Rate limit exceeded"}'
    )


def error_response(status: int = 500) -> StubResponse:
    """
    Create a 5xx error response.
    
    Args:
        status: Error status code (500-599)
        
    Returns:
        StubResponse configured for error
    """
    if not (500 <= status < 600):
        raise ValueError(f"Status {status} is not a 5xx error")
    
    return StubResponse(
        status=status,
        headers={},
        body='{"error": "Internal server error"}'
    )


def exhausted_response(reset_offset: int = 30) -> StubResponse:
    """
    Create a 200 response indicating rate limit exhaustion.
    
    Args:
        reset_offset: Seconds until reset
        
    Returns:
        StubResponse with remaining=0
    """
    reset_time = 1000 + reset_offset
    
    return StubResponse(
        status=200,
        headers={
            "X-RateLimit-Limit": "100",
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": str(reset_time),
        },
        body='{"status": "ok", "data": []}'
    )

