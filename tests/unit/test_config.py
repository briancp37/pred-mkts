"""
Unit tests for configuration loading and validation.
Tests cover:
- Loading valid config
- Validation errors for invalid configs
- Fallback to defaults when config is missing
- ExchangeConfig and LimitsConfig functionality
"""
import pytest
from pathlib import Path
import tempfile
import yaml

from pred_mkts.core.config import (
    ConfigValidationError,
    ExchangeConfig,
    LimitsConfig,
    load_config,
    validate_config,
    get_default_config,
    DEFAULT_CONFIG,
)


class TestExchangeConfig:
    """Test ExchangeConfig class."""
    
    def test_create_with_defaults(self):
        """Test creating ExchangeConfig with minimal arguments."""
        config = ExchangeConfig(host="api.test.com")
        
        assert config.host == "api.test.com"
        assert config.steady_rate == 10
        assert config.burst == 20
        assert config.max_concurrency == 4
        assert config.headers == {
            "retry_after": "Retry-After",
            "limit": "X-RateLimit-Limit",
            "remaining": "X-RateLimit-Remaining",
            "reset": "X-RateLimit-Reset",
        }
        assert config.buckets == []
    
    def test_create_with_custom_values(self):
        """Test creating ExchangeConfig with custom values."""
        custom_headers = {"retry_after": "X-Retry"}
        custom_buckets = [{"key": "test", "pattern": "/api/.*"}]
        
        config = ExchangeConfig(
            host="api.custom.com",
            steady_rate=5,
            burst=10,
            max_concurrency=2,
            headers=custom_headers,
            buckets=custom_buckets
        )
        
        assert config.host == "api.custom.com"
        assert config.steady_rate == 5
        assert config.burst == 10
        assert config.max_concurrency == 2
        assert config.headers == custom_headers
        assert config.buckets == custom_buckets
    
    def test_from_dict(self):
        """Test creating ExchangeConfig from dictionary."""
        data = {
            "host": "api.fromdict.com",
            "steady_rate": 15,
            "burst": 30,
            "max_concurrency": 8,
            "headers": {"retry_after": "Retry"},
            "buckets": [{"key": "global"}]
        }
        
        config = ExchangeConfig.from_dict(data)
        
        assert config.host == "api.fromdict.com"
        assert config.steady_rate == 15
        assert config.burst == 30
        assert config.max_concurrency == 8
        assert config.headers == {"retry_after": "Retry"}
        assert config.buckets == [{"key": "global"}]
    
    def test_from_dict_with_missing_fields(self):
        """Test from_dict uses defaults for missing fields."""
        data = {"host": "api.minimal.com"}
        config = ExchangeConfig.from_dict(data)
        
        assert config.host == "api.minimal.com"
        assert config.steady_rate == 10
        assert config.burst == 20
    
    def test_to_dict(self):
        """Test converting ExchangeConfig to dictionary."""
        config = ExchangeConfig(
            host="api.test.com",
            steady_rate=5,
            burst=10
        )
        
        result = config.to_dict()
        
        assert result["host"] == "api.test.com"
        assert result["steady_rate"] == 5
        assert result["burst"] == 10
        assert result["max_concurrency"] == 4


class TestLimitsConfig:
    """Test LimitsConfig class."""
    
    def test_create_empty(self):
        """Test creating empty LimitsConfig."""
        config = LimitsConfig(exchanges={})
        assert config.exchanges == {}
    
    def test_get_exchange(self):
        """Test retrieving exchange config by name."""
        exchange_config = ExchangeConfig(host="api.test.com")
        limits_config = LimitsConfig(exchanges={"test": exchange_config})
        
        retrieved = limits_config.get_exchange("test")
        assert retrieved is exchange_config
        assert retrieved.host == "api.test.com"
    
    def test_get_exchange_not_found(self):
        """Test retrieving non-existent exchange returns None."""
        limits_config = LimitsConfig(exchanges={})
        assert limits_config.get_exchange("nonexistent") is None
    
    def test_get_exchange_or_default(self):
        """Test get_exchange_or_default returns default when not found."""
        limits_config = LimitsConfig(exchanges={})
        config = limits_config.get_exchange_or_default("nonexistent")
        
        assert config is not None
        assert config.host == "api.example.com"
        assert config.steady_rate == 10
    
    def test_from_dict(self):
        """Test creating LimitsConfig from dictionary."""
        data = {
            "exchanges": {
                "exchange1": {
                    "host": "api.ex1.com",
                    "steady_rate": 5
                },
                "exchange2": {
                    "host": "api.ex2.com",
                    "steady_rate": 15
                }
            }
        }
        
        config = LimitsConfig.from_dict(data)
        
        assert len(config.exchanges) == 2
        assert config.exchanges["exchange1"].host == "api.ex1.com"
        assert config.exchanges["exchange2"].steady_rate == 15
    
    def test_to_dict(self):
        """Test converting LimitsConfig to dictionary."""
        exchange1 = ExchangeConfig(host="api.ex1.com", steady_rate=5)
        exchange2 = ExchangeConfig(host="api.ex2.com", steady_rate=15)
        config = LimitsConfig(exchanges={
            "exchange1": exchange1,
            "exchange2": exchange2
        })
        
        result = config.to_dict()
        
        assert "exchanges" in result
        assert "exchange1" in result["exchanges"]
        assert "exchange2" in result["exchanges"]
        assert result["exchanges"]["exchange1"]["host"] == "api.ex1.com"
        assert result["exchanges"]["exchange2"]["steady_rate"] == 15


class TestValidateConfig:
    """Test configuration validation."""
    
    def test_valid_config(self):
        """Test validation passes for valid config."""
        config = {
            "exchanges": {
                "test": {
                    "host": "api.test.com",
                    "steady_rate": 10,
                    "burst": 20,
                    "max_concurrency": 4
                }
            }
        }
        
        # Should not raise
        validate_config(config)
    
    def test_not_dict(self):
        """Test validation fails if config is not a dictionary."""
        with pytest.raises(ConfigValidationError, match="must be a dictionary"):
            validate_config("not a dict")
    
    def test_missing_exchanges_key(self):
        """Test validation fails if 'exchanges' key is missing."""
        with pytest.raises(ConfigValidationError, match="must contain 'exchanges'"):
            validate_config({"other": "data"})
    
    def test_exchanges_not_dict(self):
        """Test validation fails if 'exchanges' is not a dictionary."""
        with pytest.raises(ConfigValidationError, match="'exchanges' must be a dictionary"):
            validate_config({"exchanges": []})
    
    def test_exchange_config_not_dict(self):
        """Test validation fails if individual exchange config is not a dict."""
        config = {
            "exchanges": {
                "test": "not a dict"
            }
        }
        with pytest.raises(ConfigValidationError, match="config must be a dictionary"):
            validate_config(config)
    
    def test_missing_host(self):
        """Test validation fails if exchange config missing 'host'."""
        config = {
            "exchanges": {
                "test": {
                    "steady_rate": 10
                }
            }
        }
        with pytest.raises(ConfigValidationError, match="must have 'host'"):
            validate_config(config)
    
    def test_negative_steady_rate(self):
        """Test validation fails for negative steady_rate."""
        config = {
            "exchanges": {
                "test": {
                    "host": "api.test.com",
                    "steady_rate": -5
                }
            }
        }
        with pytest.raises(ConfigValidationError, match="must be a positive number"):
            validate_config(config)
    
    def test_zero_burst(self):
        """Test validation fails for zero burst."""
        config = {
            "exchanges": {
                "test": {
                    "host": "api.test.com",
                    "burst": 0
                }
            }
        }
        with pytest.raises(ConfigValidationError, match="must be a positive number"):
            validate_config(config)
    
    def test_invalid_headers_type(self):
        """Test validation fails if headers is not a dict."""
        config = {
            "exchanges": {
                "test": {
                    "host": "api.test.com",
                    "headers": "not a dict"
                }
            }
        }
        with pytest.raises(ConfigValidationError, match="headers must be a dictionary"):
            validate_config(config)
    
    def test_invalid_buckets_type(self):
        """Test validation fails if buckets is not a list."""
        config = {
            "exchanges": {
                "test": {
                    "host": "api.test.com",
                    "buckets": "not a list"
                }
            }
        }
        with pytest.raises(ConfigValidationError, match="buckets must be a list"):
            validate_config(config)
    
    def test_bucket_not_dict(self):
        """Test validation fails if bucket is not a dict."""
        config = {
            "exchanges": {
                "test": {
                    "host": "api.test.com",
                    "buckets": ["not a dict"]
                }
            }
        }
        with pytest.raises(ConfigValidationError, match="bucket .* must be a dictionary"):
            validate_config(config)
    
    def test_bucket_missing_key(self):
        """Test validation fails if bucket missing 'key' field."""
        config = {
            "exchanges": {
                "test": {
                    "host": "api.test.com",
                    "buckets": [{"pattern": "/api/.*"}]
                }
            }
        }
        with pytest.raises(ConfigValidationError, match="must have 'key'"):
            validate_config(config)


class TestLoadConfig:
    """Test configuration loading."""
    
    def test_load_valid_config_file(self):
        """Test loading a valid config file."""
        config_data = {
            "exchanges": {
                "polymarket": {
                    "host": "api.polymarket.com",
                    "steady_rate": 10,
                    "burst": 20,
                    "max_concurrency": 4,
                    "headers": {
                        "retry_after": "Retry-After",
                        "limit": "X-RateLimit-Limit",
                        "remaining": "X-RateLimit-Remaining",
                        "reset": "X-RateLimit-Reset"
                    },
                    "buckets": [
                        {
                            "key": "global",
                            "pattern": "/v{1,}/.*",
                            "share_with": ["orders", "markets"]
                        }
                    ]
                }
            }
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            yaml.dump(config_data, f)
            temp_path = Path(f.name)
        
        try:
            config = load_config(temp_path)
            
            assert len(config.exchanges) == 1
            assert "polymarket" in config.exchanges
            
            poly_config = config.exchanges["polymarket"]
            assert poly_config.host == "api.polymarket.com"
            assert poly_config.steady_rate == 10
            assert poly_config.burst == 20
            assert poly_config.max_concurrency == 4
            assert len(poly_config.buckets) == 1
            assert poly_config.buckets[0]["key"] == "global"
        finally:
            temp_path.unlink()
    
    def test_load_missing_file_returns_default(self):
        """Test loading non-existent file returns default config."""
        non_existent_path = Path("/tmp/nonexistent_config_file_123456.yml")
        
        config = load_config(non_existent_path)
        
        # Should return default config
        assert config is not None
        default = get_default_config()
        assert len(config.exchanges) == len(default.exchanges)
    
    def test_load_invalid_yaml(self):
        """Test loading invalid YAML raises error."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            f.write("invalid: yaml: content:\n  - bad indentation")
            temp_path = Path(f.name)
        
        try:
            with pytest.raises(ConfigValidationError, match="Invalid YAML"):
                load_config(temp_path)
        finally:
            temp_path.unlink()
    
    def test_load_invalid_structure(self):
        """Test loading config with invalid structure raises error."""
        config_data = {
            "wrong_key": {
                "data": "here"
            }
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            yaml.dump(config_data, f)
            temp_path = Path(f.name)
        
        try:
            with pytest.raises(ConfigValidationError, match="must contain 'exchanges'"):
                load_config(temp_path)
        finally:
            temp_path.unlink()
    
    def test_load_default_location(self):
        """Test loading from default location."""
        # This should either load the actual config or return default
        config = load_config()
        assert config is not None
        assert isinstance(config, LimitsConfig)


class TestGetDefaultConfig:
    """Test default configuration retrieval."""
    
    def test_get_default_config(self):
        """Test getting default configuration."""
        config = get_default_config()
        
        assert config is not None
        assert isinstance(config, LimitsConfig)
        assert "default" in config.exchanges
        
        default_exchange = config.exchanges["default"]
        assert default_exchange.host == "api.example.com"
        assert default_exchange.steady_rate == 10
        assert default_exchange.burst == 20
        assert default_exchange.max_concurrency == 4

