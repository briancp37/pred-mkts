"""
Configuration loader and validator for exchange rate limit settings.
[CTX:PBI-0:0-2:CFG]
"""
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml


# Default configuration used as fallback
DEFAULT_CONFIG = {
    "exchanges": {
        "default": {
            "host": "api.example.com",
            "steady_rate": 10,
            "burst": 20,
            "max_concurrency": 4,
            "headers": {
                "retry_after": "Retry-After",
                "limit": "X-RateLimit-Limit",
                "remaining": "X-RateLimit-Remaining",
                "reset": "X-RateLimit-Reset",
            },
            "buckets": []
        }
    }
}


class ConfigValidationError(Exception):
    """Raised when configuration validation fails."""
    pass


class ExchangeConfig:
    """Represents configuration for a single exchange."""
    
    def __init__(
        self,
        host: str,
        steady_rate: int = 10,
        burst: int = 20,
        max_concurrency: int = 4,
        headers: Optional[Dict[str, str]] = None,
        buckets: Optional[List[Dict[str, Any]]] = None
    ):
        self.host = host
        self.steady_rate = steady_rate
        self.burst = burst
        self.max_concurrency = max_concurrency
        self.headers = headers or {
            "retry_after": "Retry-After",
            "limit": "X-RateLimit-Limit",
            "remaining": "X-RateLimit-Remaining",
            "reset": "X-RateLimit-Reset",
        }
        self.buckets = buckets or []
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExchangeConfig":
        """Create ExchangeConfig from dictionary."""
        return cls(
            host=data.get("host", "api.example.com"),
            steady_rate=data.get("steady_rate", 10),
            burst=data.get("burst", 20),
            max_concurrency=data.get("max_concurrency", 4),
            headers=data.get("headers"),
            buckets=data.get("buckets")
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "host": self.host,
            "steady_rate": self.steady_rate,
            "burst": self.burst,
            "max_concurrency": self.max_concurrency,
            "headers": self.headers,
            "buckets": self.buckets
        }


class LimitsConfig:
    """Main configuration container for all exchanges."""
    
    def __init__(self, exchanges: Dict[str, ExchangeConfig]):
        self.exchanges = exchanges
    
    def get_exchange(self, name: str) -> Optional[ExchangeConfig]:
        """Get configuration for a specific exchange."""
        return self.exchanges.get(name)
    
    def get_exchange_or_default(self, name: str) -> ExchangeConfig:
        """Get exchange config or return default if not found."""
        return self.exchanges.get(name) or self._get_default_config()
    
    @staticmethod
    def _get_default_config() -> ExchangeConfig:
        """Get default exchange configuration."""
        return ExchangeConfig.from_dict(DEFAULT_CONFIG["exchanges"]["default"])
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LimitsConfig":
        """Create LimitsConfig from dictionary."""
        exchanges_data = data.get("exchanges", {})
        exchanges = {
            name: ExchangeConfig.from_dict(config)
            for name, config in exchanges_data.items()
        }
        return cls(exchanges=exchanges)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "exchanges": {
                name: config.to_dict()
                for name, config in self.exchanges.items()
            }
        }


def validate_config(config_data: Dict[str, Any]) -> None:
    """
    Validate configuration data structure.
    
    Raises:
        ConfigValidationError: If validation fails
    """
    if not isinstance(config_data, dict):
        raise ConfigValidationError("Config must be a dictionary")
    
    if "exchanges" not in config_data:
        raise ConfigValidationError("Config must contain 'exchanges' key")
    
    exchanges = config_data["exchanges"]
    if not isinstance(exchanges, dict):
        raise ConfigValidationError("'exchanges' must be a dictionary")
    
    for exchange_name, exchange_config in exchanges.items():
        if not isinstance(exchange_config, dict):
            raise ConfigValidationError(
                f"Exchange '{exchange_name}' config must be a dictionary"
            )
        
        # Validate required fields
        if "host" not in exchange_config:
            raise ConfigValidationError(
                f"Exchange '{exchange_name}' must have 'host' field"
            )
        
        # Validate numeric fields are positive
        for field in ["steady_rate", "burst", "max_concurrency"]:
            if field in exchange_config:
                value = exchange_config[field]
                if not isinstance(value, (int, float)) or value <= 0:
                    raise ConfigValidationError(
                        f"Exchange '{exchange_name}' field '{field}' must be a positive number"
                    )
        
        # Validate headers if present
        if "headers" in exchange_config:
            headers = exchange_config["headers"]
            if not isinstance(headers, dict):
                raise ConfigValidationError(
                    f"Exchange '{exchange_name}' headers must be a dictionary"
                )
        
        # Validate buckets if present
        if "buckets" in exchange_config:
            buckets = exchange_config["buckets"]
            if not isinstance(buckets, list):
                raise ConfigValidationError(
                    f"Exchange '{exchange_name}' buckets must be a list"
                )
            
            for i, bucket in enumerate(buckets):
                if not isinstance(bucket, dict):
                    raise ConfigValidationError(
                        f"Exchange '{exchange_name}' bucket {i} must be a dictionary"
                    )
                if "key" not in bucket:
                    raise ConfigValidationError(
                        f"Exchange '{exchange_name}' bucket {i} must have 'key' field"
                    )


def load_config(config_path: Optional[Path] = None) -> LimitsConfig:
    """
    Load and validate configuration from YAML file.
    
    Args:
        config_path: Path to config file. If None, uses default location.
    
    Returns:
        LimitsConfig instance
        
    Raises:
        ConfigValidationError: If validation fails
    """
    if config_path is None:
        # Default to config/limits.yml in project root
        config_path = Path(__file__).parent.parent.parent.parent / "config" / "limits.yml"
    
    try:
        with open(config_path, "r") as f:
            config_data = yaml.safe_load(f)
    except FileNotFoundError:
        # Return default config if file not found
        return LimitsConfig.from_dict(DEFAULT_CONFIG)
    except yaml.YAMLError as e:
        raise ConfigValidationError(f"Invalid YAML in config file: {e}")
    
    # Validate the loaded config
    validate_config(config_data)
    
    return LimitsConfig.from_dict(config_data)


def get_default_config() -> LimitsConfig:
    """Get default configuration."""
    return LimitsConfig.from_dict(DEFAULT_CONFIG)

