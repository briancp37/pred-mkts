"""
DataSource interface and supporting types.

This module defines the core abstraction for data sources that fetch data from
prediction market exchanges. Each source provides request preparation, authentication,
and pagination capabilities.
"""
# [CTX:PBI-0:0-1:IFACE]

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class RequestSpec:
    """
    Specification for an HTTP request.
    
    Attributes:
        url: Full URL to request
        method: HTTP method (GET, POST, etc.)
        headers: HTTP headers as key-value pairs
        query_params: Query string parameters
        body: Optional request body for POST/PUT requests
    """
    url: str
    method: str = "GET"
    headers: dict[str, str] = field(default_factory=dict)
    query_params: dict[str, Any] = field(default_factory=dict)
    body: dict[str, Any] | None = None


@dataclass
class Page:
    """
    A single page of results from a paginated API.
    
    Attributes:
        data: The actual data records in this page
        metadata: Additional metadata (cursor, page number, etc.)
    """
    data: list[dict[str, Any]]
    metadata: dict[str, Any] = field(default_factory=dict)


# Type alias for paginator callback
# Takes (current_page, total_fetched) and returns whether to continue
Paginator = Callable[[Page, int], bool]


class DataSource(ABC):
    """
    Abstract base class for all data sources.
    
    Each data source represents a prediction market exchange or API endpoint
    that provides market data. Subclasses must implement request preparation,
    authentication, and pagination logic specific to their API.
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """
        Unique identifier for this data source.
        
        Returns:
            The name of the data source (e.g., "polymarket", "kalshi")
        """
        pass
    
    @abstractmethod
    def prepare_request(self, endpoint: str, params: dict[str, Any] | None = None) -> RequestSpec:
        """
        Prepare an HTTP request specification for the given endpoint.
        
        Args:
            endpoint: API endpoint path (relative to base URL)
            params: Optional parameters to include in the request
            
        Returns:
            A RequestSpec with url, method, headers, and query parameters
        """
        pass
    
    def auth(self, initial_headers: dict[str, str] | None = None) -> dict[str, str]:
        """
        Authentication hook to add auth headers to a request.
        
        Default implementation returns headers unchanged. Override to add
        API keys, OAuth tokens, or other authentication.
        
        Args:
            initial_headers: Existing headers to augment
            
        Returns:
            Headers dict with authentication added
        """
        return initial_headers.copy() if initial_headers else {}
    
    @abstractmethod
    def paginate(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        paginator: Paginator | None = None,
    ) -> Iterator[Page]:
        """
        Iterate through pages of results from an endpoint.
        
        Args:
            endpoint: API endpoint path
            params: Optional parameters for the request
            paginator: Optional callback to control pagination.
                       Called with (current_page, total_records_fetched).
                       Return False to stop pagination.
                       If None, fetches all available pages.
                       
        Yields:
            Page objects containing data and metadata
        """
        pass

