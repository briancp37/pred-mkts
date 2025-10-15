"""
Configuration module for rate limit settings.

This module provides configuration loading and validation for exchange-specific
rate limiting policies.
"""
# [CTX:PBI-0:0-2:CFG]

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class BucketConfig:
    """Configuration for a rate limit bucket."""
    
    key: str
    pattern: str
    share_with: list[str] = field(default_factory=list)
    
    def matches(self, endpoint: str) -> bool:
        """Check if endpoint matches this bucket pattern."""
        return bool(re.match(self.pattern, endpoint))


@dataclass
class HeaderConfig:
    """Configuration for rate limit headers."""
    
    retry_after: str = "Retry-After"
    limit: str = "X-RateLimit-Limit"
    remaining: str = "X-RateLimit-Remaining"
    reset: str = "X-RateLimit-Reset"


@dataclass
class ExchangeConfig:
    """Configuration for a single exchange."""
    
    host: str
    steady_rate: float = 10.0  # tokens per second
    burst: int = 20
    max_concurrency: int = 4
    headers: HeaderConfig = field(default_factory=HeaderConfig)
    buckets: list[BucketConfig] = field(default_factory=list)
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExchangeConfig":
        """Create ExchangeConfig from dictionary."""
        headers_data = data.get("headers", {})
        headers = HeaderConfig(**headers_data) if headers_data else HeaderConfig()
        
        buckets_data = data.get("buckets", [])
        buckets = [BucketConfig(**bucket) for bucket in buckets_data]
        
        return cls(
            host=data["host"],
            steady_rate=data.get("steady_rate", 10.0),
            burst=data.get("burst", 20),
            max_concurrency=data.get("max_concurrency", 4),
            headers=headers,
            buckets=buckets,
        )


@dataclass
class LimitsConfig:
    """Configuration for all exchanges."""
    
    exchanges: dict[str, ExchangeConfig] = field(default_factory=dict)
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LimitsConfig":
        """Create LimitsConfig from dictionary."""
        exchanges_data = data.get("exchanges", {})
        exchanges = {
            name: ExchangeConfig.from_dict(config)
            for name, config in exchanges_data.items()
        }
        return cls(exchanges=exchanges)
    
    def get_exchange_config(self, exchange_name: str) -> ExchangeConfig | None:
        """Get configuration for a specific exchange."""
        return self.exchanges.get(exchange_name)


def load_config(config_path: str | Path | None = None) -> LimitsConfig:
    """
    Load rate limit configuration from YAML file.
    
    Args:
        config_path: Path to config file. If None, uses default location.
        
    Returns:
        LimitsConfig with exchange configurations
        
    Raises:
        FileNotFoundError: If config file doesn't exist
        yaml.YAMLError: If config file is invalid YAML
        ValueError: If config validation fails
    """
    if config_path is None:
        config_path = Path(__file__).parents[3] / "config" / "limits.yml"
    else:
        config_path = Path(config_path)
    
    if not config_path.exists():
        # Return default empty config if file doesn't exist
        return LimitsConfig()
    
    with open(config_path, "r") as f:
        data = yaml.safe_load(f)
    
    if not data:
        return LimitsConfig()
    
    config = LimitsConfig.from_dict(data)
    validate_config(config)
    return config


def validate_config(config: LimitsConfig) -> None:
    """
    Validate configuration.
    
    Args:
        config: Configuration to validate
        
    Raises:
        ValueError: If configuration is invalid
    """
    for name, exchange in config.exchanges.items():
        if not exchange.host:
            raise ValueError(f"Exchange {name} must have a host")
        
        if exchange.steady_rate <= 0:
            raise ValueError(f"Exchange {name} steady_rate must be positive")
        
        if exchange.burst <= 0:
            raise ValueError(f"Exchange {name} burst must be positive")
        
        if exchange.max_concurrency <= 0:
            raise ValueError(f"Exchange {name} max_concurrency must be positive")
        
        # Validate bucket patterns are valid regex
        for bucket in exchange.buckets:
            try:
                re.compile(bucket.pattern)
            except re.error as e:
                raise ValueError(
                    f"Exchange {name} bucket {bucket.key} has invalid pattern: {e}"
                )


