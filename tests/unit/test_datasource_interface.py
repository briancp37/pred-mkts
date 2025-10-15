"""
Unit tests for DataSource interface and supporting types.

Tests verify that the core abstractions (RequestSpec, Page, DataSource)
work correctly and enforce interface contracts.
"""
# [CTX:PBI-0:0-1:TESTS]

import pytest

from pred_mkts.core import DataSource, Page, RequestSpec


class TestRequestSpec:
    """Tests for RequestSpec dataclass."""
    
    def test_minimal_request_spec(self):
        """Test creating a minimal RequestSpec with just a URL."""
        spec = RequestSpec(url="https://api.example.com/endpoint")
        
        assert spec.url == "https://api.example.com/endpoint"
        assert spec.method == "GET"
        assert spec.headers == {}
        assert spec.query_params == {}
        assert spec.body is None
    
    def test_full_request_spec(self):
        """Test creating a complete RequestSpec with all fields."""
        spec = RequestSpec(
            url="https://api.example.com/endpoint",
            method="POST",
            headers={"Authorization": "Bearer token123"},
            query_params={"limit": 10, "offset": 0},
            body={"key": "value"},
        )
        
        assert spec.url == "https://api.example.com/endpoint"
        assert spec.method == "POST"
        assert spec.headers == {"Authorization": "Bearer token123"}
        assert spec.query_params == {"limit": 10, "offset": 0}
        assert spec.body == {"key": "value"}
    
    def test_headers_default_factory(self):
        """Test that headers dict is independent per instance."""
        spec1 = RequestSpec(url="http://example.com/1")
        spec2 = RequestSpec(url="http://example.com/2")
        
        spec1.headers["X-Custom"] = "value1"
        
        assert "X-Custom" in spec1.headers
        assert "X-Custom" not in spec2.headers


class TestPage:
    """Tests for Page dataclass."""
    
    def test_minimal_page(self):
        """Test creating a minimal Page with just data."""
        page = Page(data=[{"id": 1}, {"id": 2}])
        
        assert page.data == [{"id": 1}, {"id": 2}]
        assert page.metadata == {}
    
    def test_page_with_metadata(self):
        """Test creating a Page with metadata."""
        page = Page(
            data=[{"market": "test"}],
            metadata={"next_cursor": "abc123", "total": 100},
        )
        
        assert page.data == [{"market": "test"}]
        assert page.metadata == {"next_cursor": "abc123", "total": 100}
    
    def test_empty_page(self):
        """Test creating an empty page."""
        page = Page(data=[])
        
        assert page.data == []
        assert page.metadata == {}


class TestDataSourceInterface:
    """Tests for DataSource abstract base class."""
    
    def test_cannot_instantiate_abstract_datasource(self):
        """Test that DataSource cannot be instantiated directly."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            DataSource()  # type: ignore
    
    def test_datasource_requires_name_property(self):
        """Test that subclasses must implement name property."""
        class IncompleteSource(DataSource):
            def prepare_request(self, endpoint, params=None):
                pass
            def paginate(self, endpoint, params=None, paginator=None):
                pass
        
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            IncompleteSource()  # type: ignore
    
    def test_datasource_requires_prepare_request(self):
        """Test that subclasses must implement prepare_request."""
        class IncompleteSource(DataSource):
            @property
            def name(self):
                return "test"
            def paginate(self, endpoint, params=None, paginator=None):
                pass
        
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            IncompleteSource()  # type: ignore
    
    def test_datasource_requires_paginate(self):
        """Test that subclasses must implement paginate."""
        class IncompleteSource(DataSource):
            @property
            def name(self):
                return "test"
            def prepare_request(self, endpoint, params=None):
                pass
        
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            IncompleteSource()  # type: ignore
    
    def test_complete_datasource_can_be_instantiated(self):
        """Test that a complete DataSource implementation can be instantiated."""
        class CompleteSource(DataSource):
            @property
            def name(self):
                return "complete"
            
            def prepare_request(self, endpoint, params=None):
                return RequestSpec(url=f"http://api.example.com{endpoint}")
            
            def paginate(self, endpoint, params=None, paginator=None):
                yield Page(data=[])
        
        source = CompleteSource()
        assert source.name == "complete"
    
    def test_auth_default_implementation(self):
        """Test default auth implementation returns copy of headers."""
        class MinimalSource(DataSource):
            @property
            def name(self):
                return "minimal"
            
            def prepare_request(self, endpoint, params=None):
                return RequestSpec(url="http://example.com")
            
            def paginate(self, endpoint, params=None, paginator=None):
                yield Page(data=[])
        
        source = MinimalSource()
        
        # Test with None
        result = source.auth(None)
        assert result == {}
        
        # Test with headers
        headers = {"Content-Type": "application/json"}
        result = source.auth(headers)
        assert result == {"Content-Type": "application/json"}
        
        # Verify it's a copy
        result["X-Custom"] = "value"
        assert "X-Custom" not in headers

