"""
Unit tests for Polymarket data source stub.

These tests verify the minimal Polymarket stub correctly implements
the DataSource interface. Full functionality tests will come later.
"""
# [CTX:PBI-0:0-1:POLYMARKET-TESTS]

from pred_mkts.core import Page, RequestSpec
from pred_mkts.datasources import PolymarketDataSource


class TestPolymarketDataSource:
    """Tests for PolymarketDataSource stub implementation."""
    
    def test_name_property(self):
        """Test that name property returns correct value."""
        source = PolymarketDataSource()
        assert source.name == "polymarket"
    
    def test_prepare_request_basic(self):
        """Test basic request preparation."""
        source = PolymarketDataSource()
        spec = source.prepare_request("/markets")
        
        assert isinstance(spec, RequestSpec)
        assert spec.url == "https://api.polymarket.com/markets"
        assert spec.method == "GET"
        assert isinstance(spec.headers, dict)
        assert spec.query_params == {}
    
    def test_prepare_request_with_params(self):
        """Test request preparation with query parameters."""
        source = PolymarketDataSource()
        params = {"limit": 10, "offset": 20}
        spec = source.prepare_request("/markets", params)
        
        assert spec.url == "https://api.polymarket.com/markets"
        assert spec.query_params == {"limit": 10, "offset": 20}
    
    def test_prepare_request_endpoint_formats(self):
        """Test that endpoints with leading slash are formatted correctly."""
        source = PolymarketDataSource()
        
        # With leading slash
        spec1 = source.prepare_request("/markets")
        assert spec1.url == "https://api.polymarket.com/markets"
        
        # Nested endpoint
        spec2 = source.prepare_request("/markets/123")
        assert spec2.url == "https://api.polymarket.com/markets/123"
    
    def test_paginate_stub_returns_empty_page(self):
        """Test that stub pagination returns an empty page."""
        source = PolymarketDataSource()
        pages = list(source.paginate("/markets"))
        
        assert len(pages) == 1
        assert isinstance(pages[0], Page)
        assert pages[0].data == []
        assert pages[0].metadata == {"stub": True}
    
    def test_paginate_with_params(self):
        """Test pagination with parameters (stub behavior)."""
        source = PolymarketDataSource()
        params = {"limit": 5}
        pages = list(source.paginate("/markets", params))
        
        # Stub still returns single empty page
        assert len(pages) == 1
        assert pages[0].data == []
    
    def test_paginate_with_paginator_callback(self):
        """Test pagination with a paginator callback (stub behavior)."""
        source = PolymarketDataSource()
        callback_called = []
        
        def paginator(page, total):
            callback_called.append((page, total))
            return False  # Stop after first page
        
        pages = list(source.paginate("/markets", paginator=paginator))
        
        # Stub yields one page, callback not used in stub implementation
        assert len(pages) == 1
        # Note: In the stub, the callback is not actually called
        # This will be tested properly when real pagination is implemented
    
    def test_base_url_constant(self):
        """Test that BASE_URL is set correctly."""
        assert PolymarketDataSource.BASE_URL == "https://api.polymarket.com"

