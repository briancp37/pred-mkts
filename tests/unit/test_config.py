"""
Unit tests for configuration module.

Tests cover config loading, validation, and schema parsing.
"""
# [CTX:PBI-0:0-2:CFG]

from pathlib import Path

import pytest

from pred_mkts.core import (
    BucketConfig,
    ExchangeConfig,
    HeaderConfig,
    LimitsConfig,
    load_config,
    validate_config,
)


class TestBucketConfig:
    """Test bucket configuration."""
    
    def test_bucket_pattern_matching(self):
        """Test endpoint pattern matching."""
        bucket = BucketConfig(
            key="global",
            pattern="/v.*/.*",
            share_with=[],
        )
        
        assert bucket.matches("/v1/markets")
        assert bucket.matches("/v2/orders")
        assert not bucket.matches("/api/markets")
    
    def test_bucket_with_share_with(self):
        """Test bucket with shared endpoints."""
        bucket = BucketConfig(
            key="trading",
            pattern="/v1/(orders|trades)",
            share_with=["orders", "trades"],
        )
        
        assert bucket.share_with == ["orders", "trades"]


class TestHeaderConfig:
    """Test header configuration."""
    
    def test_default_headers(self):
        """Test default header names."""
        headers = HeaderConfig()
        
        assert headers.retry_after == "Retry-After"
        assert headers.limit == "X-RateLimit-Limit"
        assert headers.remaining == "X-RateLimit-Remaining"
        assert headers.reset == "X-RateLimit-Reset"
    
    def test_custom_headers(self):
        """Test custom header names."""
        headers = HeaderConfig(
            retry_after="Custom-Retry",
            limit="Custom-Limit",
            remaining="Custom-Remaining",
            reset="Custom-Reset",
        )
        
        assert headers.retry_after == "Custom-Retry"
        assert headers.limit == "Custom-Limit"
        assert headers.remaining == "Custom-Remaining"
        assert headers.reset == "Custom-Reset"


class TestExchangeConfig:
    """Test exchange configuration."""
    
    def test_default_values(self):
        """Test default configuration values."""
        config = ExchangeConfig(host="api.example.com")
        
        assert config.host == "api.example.com"
        assert config.steady_rate == 10.0
        assert config.burst == 20
        assert config.max_concurrency == 4
        assert isinstance(config.headers, HeaderConfig)
        assert config.buckets == []
    
    def test_custom_values(self):
        """Test custom configuration values."""
        headers = HeaderConfig(retry_after="Custom-Retry")
        buckets = [BucketConfig(key="test", pattern=".*")]
        
        config = ExchangeConfig(
            host="api.example.com",
            steady_rate=5.0,
            burst=10,
            max_concurrency=2,
            headers=headers,
            buckets=buckets,
        )
        
        assert config.steady_rate == 5.0
        assert config.burst == 10
        assert config.max_concurrency == 2
        assert config.headers.retry_after == "Custom-Retry"
        assert len(config.buckets) == 1
    
    def test_from_dict(self):
        """Test creating config from dictionary."""
        data = {
            "host": "api.example.com",
            "steady_rate": 15.0,
            "burst": 30,
            "max_concurrency": 8,
            "headers": {
                "retry_after": "Retry-After",
                "limit": "X-Limit",
            },
            "buckets": [
                {
                    "key": "global",
                    "pattern": "/v.*/.*",
                    "share_with": [],
                }
            ],
        }
        
        config = ExchangeConfig.from_dict(data)
        
        assert config.host == "api.example.com"
        assert config.steady_rate == 15.0
        assert config.burst == 30
        assert config.max_concurrency == 8
        assert config.headers.limit == "X-Limit"
        assert len(config.buckets) == 1
        assert config.buckets[0].key == "global"


class TestLimitsConfig:
    """Test limits configuration."""
    
    def test_empty_config(self):
        """Test empty configuration."""
        config = LimitsConfig()
        
        assert config.exchanges == {}
    
    def test_get_exchange_config(self):
        """Test getting exchange configuration."""
        polymarket = ExchangeConfig(host="api.polymarket.com")
        config = LimitsConfig(exchanges={"polymarket": polymarket})
        
        result = config.get_exchange_config("polymarket")
        assert result is not None
        assert result.host == "api.polymarket.com"
    
    def test_get_nonexistent_exchange(self):
        """Test getting nonexistent exchange."""
        config = LimitsConfig()
        
        result = config.get_exchange_config("nonexistent")
        assert result is None
    
    def test_from_dict(self):
        """Test creating config from dictionary."""
        data = {
            "exchanges": {
                "polymarket": {
                    "host": "api.polymarket.com",
                    "steady_rate": 10.0,
                    "burst": 20,
                },
                "kalshi": {
                    "host": "api.kalshi.com",
                    "steady_rate": 5.0,
                    "burst": 10,
                },
            }
        }
        
        config = LimitsConfig.from_dict(data)
        
        assert len(config.exchanges) == 2
        assert "polymarket" in config.exchanges
        assert "kalshi" in config.exchanges
        assert config.exchanges["polymarket"].host == "api.polymarket.com"
        assert config.exchanges["kalshi"].steady_rate == 5.0


class TestLoadConfig:
    """Test configuration loading."""
    
    def test_load_default_config(self):
        """Test loading default config file."""
        config = load_config()
        
        # Should load config/limits.yml
        assert isinstance(config, LimitsConfig)
        # May or may not have exchanges depending on file
    
    def test_load_missing_config(self, tmp_path):
        """Test loading when config file doesn't exist."""
        nonexistent = tmp_path / "nonexistent.yml"
        
        config = load_config(nonexistent)
        
        # Should return empty config
        assert isinstance(config, LimitsConfig)
        assert config.exchanges == {}
    
    def test_load_custom_config(self, tmp_path):
        """Test loading custom config file."""
        config_file = tmp_path / "test_limits.yml"
        config_file.write_text("""
exchanges:
  test:
    host: api.test.com
    steady_rate: 5.0
    burst: 10
    max_concurrency: 2
""")
        
        config = load_config(config_file)
        
        assert "test" in config.exchanges
        assert config.exchanges["test"].host == "api.test.com"
        assert config.exchanges["test"].steady_rate == 5.0
    
    def test_load_empty_config_file(self, tmp_path):
        """Test loading empty config file."""
        config_file = tmp_path / "empty.yml"
        config_file.write_text("")
        
        config = load_config(config_file)
        
        # Should return empty config
        assert isinstance(config, LimitsConfig)
        assert config.exchanges == {}


class TestValidateConfig:
    """Test configuration validation."""
    
    def test_valid_config(self):
        """Test validation of valid config."""
        config = LimitsConfig(
            exchanges={
                "test": ExchangeConfig(
                    host="api.test.com",
                    steady_rate=10.0,
                    burst=20,
                    max_concurrency=4,
                )
            }
        )
        
        # Should not raise
        validate_config(config)
    
    def test_missing_host(self):
        """Test validation fails for missing host."""
        config = LimitsConfig(
            exchanges={
                "test": ExchangeConfig(
                    host="",  # Empty host
                    steady_rate=10.0,
                )
            }
        )
        
        with pytest.raises(ValueError, match="must have a host"):
            validate_config(config)
    
    def test_invalid_steady_rate(self):
        """Test validation fails for invalid steady rate."""
        config = LimitsConfig(
            exchanges={
                "test": ExchangeConfig(
                    host="api.test.com",
                    steady_rate=0.0,  # Invalid
                )
            }
        )
        
        with pytest.raises(ValueError, match="steady_rate must be positive"):
            validate_config(config)
    
    def test_invalid_burst(self):
        """Test validation fails for invalid burst."""
        config = LimitsConfig(
            exchanges={
                "test": ExchangeConfig(
                    host="api.test.com",
                    burst=-1,  # Invalid
                )
            }
        )
        
        with pytest.raises(ValueError, match="burst must be positive"):
            validate_config(config)
    
    def test_invalid_max_concurrency(self):
        """Test validation fails for invalid max concurrency."""
        config = LimitsConfig(
            exchanges={
                "test": ExchangeConfig(
                    host="api.test.com",
                    max_concurrency=0,  # Invalid
                )
            }
        )
        
        with pytest.raises(ValueError, match="max_concurrency must be positive"):
            validate_config(config)
    
    def test_invalid_bucket_pattern(self):
        """Test validation fails for invalid regex pattern."""
        bucket = BucketConfig(
            key="bad",
            pattern="[invalid(",  # Invalid regex
        )
        
        config = LimitsConfig(
            exchanges={
                "test": ExchangeConfig(
                    host="api.test.com",
                    buckets=[bucket],
                )
            }
        )
        
        with pytest.raises(ValueError, match="invalid pattern"):
            validate_config(config)


class TestIntegration:
    """Integration tests for config system."""
    
    def test_load_and_validate(self, tmp_path):
        """Test loading and validating config together."""
        config_file = tmp_path / "integration.yml"
        config_file.write_text("""
exchanges:
  polymarket:
    host: api.polymarket.com
    steady_rate: 10
    burst: 20
    max_concurrency: 4
    headers:
      retry_after: Retry-After
      limit: X-RateLimit-Limit
      remaining: X-RateLimit-Remaining
      reset: X-RateLimit-Reset
    buckets:
      - key: global
        pattern: /v.*/.*
        share_with: []
""")
        
        config = load_config(config_file)
        validate_config(config)
        
        # Should have loaded successfully
        assert "polymarket" in config.exchanges
        poly = config.exchanges["polymarket"]
        assert poly.host == "api.polymarket.com"
        assert len(poly.buckets) == 1
        assert poly.buckets[0].key == "global"
    
    def test_multiple_exchanges(self, tmp_path):
        """Test config with multiple exchanges."""
        config_file = tmp_path / "multi.yml"
        config_file.write_text("""
exchanges:
  exchange1:
    host: api.exchange1.com
    steady_rate: 5
    burst: 10
  exchange2:
    host: api.exchange2.com
    steady_rate: 15
    burst: 30
    max_concurrency: 8
""")
        
        config = load_config(config_file)
        validate_config(config)
        
        assert len(config.exchanges) == 2
        assert config.exchanges["exchange1"].steady_rate == 5.0
        assert config.exchanges["exchange2"].max_concurrency == 8


