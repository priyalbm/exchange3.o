from typing import Optional
from .base import BaseExchangeClient
from .pionex import PionexClient
from .binance import BinanceClient


def get_exchange_client(exchange: str, api_key: str, secret_key: str) -> Optional[BaseExchangeClient]:
    """
    Factory function to get an appropriate exchange client based on the exchange name.
    
    Args:
        exchange (str): Exchange name (e.g., 'pionex', 'binance')
        api_key (str): API key for the exchange
        secret_key (str): Secret key for the exchange
        
    Returns:
        BaseExchangeClient: An appropriate exchange client instance
        
    Raises:
        ValueError: If the exchange is not supported
    """
    exchange = exchange.lower()
    
    if exchange == 'pionex':
        return PionexClient(api_key, secret_key)
    elif exchange == 'binance':
        return BinanceClient(api_key, secret_key)
    else:
        raise ValueError(f"Unsupported exchange: {exchange}")
