"""
Polymarket data source implementation.

This is a minimal stub to demonstrate the DataSource interface wiring.
Full implementation will be added in subsequent tasks.
"""
# [CTX:PBI-0:0-1:POLYMARKET-STUB]

from collections.abc import Iterator
from typing import Any

from pred_mkts.core import DataSource, Page, Paginator, RequestSpec


class PolymarketDataSource(DataSource):
    """
    Minimal stub for Polymarket API integration.
    
    This is a placeholder implementation to verify the DataSource interface
    design. Real API logic will be added later.
    """
    
    BASE_URL = "https://api.polymarket.com"
    
    @property
    def name(self) -> str:
        """Return the data source name."""
        return "polymarket"
    
    def prepare_request(self, endpoint: str, params: dict[str, Any] | None = None) -> RequestSpec:
        """
        Prepare a request to the Polymarket API.
        
        Args:
            endpoint: API endpoint path (e.g., "/markets")
            params: Optional query parameters
            
        Returns:
            RequestSpec with URL, method, headers, and query params
        """
        url = f"{self.BASE_URL}{endpoint}"
        headers = self.auth()
        
        return RequestSpec(
            url=url,
            method="GET",
            headers=headers,
            query_params=params or {},
        )
    
    def paginate(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        paginator: Paginator | None = None,
    ) -> Iterator[Page]:
        """
        Paginate through Polymarket API results.
        
        Stub implementation - yields empty results.
        
        Args:
            endpoint: API endpoint path
            params: Optional query parameters
            paginator: Optional pagination control callback
            
        Yields:
            Empty Page objects (stub implementation)
        """
        # Stub: yield a single empty page
        # Real implementation will make HTTP requests and handle pagination
        yield Page(data=[], metadata={"stub": True})

