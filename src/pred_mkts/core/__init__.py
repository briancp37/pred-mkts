"""Core interfaces and types for data sources."""

from pred_mkts.core.config import (
    BucketConfig,
    ExchangeConfig,
    HeaderConfig,
    LimitsConfig,
    load_config,
    validate_config,
)
from pred_mkts.core.datasource import DataSource, Page, Paginator, RequestSpec
from pred_mkts.core.rate_limiter import (
    RateLimiter,
    RateLimitResponse,
    RateLimitStats,
    SystemTimeProvider,
    TimeProvider,
    TokenBucket,
)

__all__ = [
    # datasource
    "DataSource",
    "Page",
    "Paginator",
    "RequestSpec",
    # config
    "BucketConfig",
    "ExchangeConfig",
    "HeaderConfig",
    "LimitsConfig",
    "load_config",
    "validate_config",
    # rate_limiter
    "RateLimiter",
    "RateLimitResponse",
    "RateLimitStats",
    "SystemTimeProvider",
    "TimeProvider",
    "TokenBucket",
]

