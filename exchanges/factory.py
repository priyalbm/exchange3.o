from typing import Optional
import logging

# Import exchange clients
from .base import BaseExchangeClient
from .pionex import PionexClient
from .mexc import MexcClient
from .bitmart import BitMartClient  # Add this import

logger = logging.getLogger('exchanges')

def get_exchange_client(exchange_name: str, api_key: str, secret_key: str, memo: str = None) -> Optional[BaseExchangeClient]:
    """
    Factory function to get the appropriate exchange client based on the exchange name.
    
    Args:
        exchange_name (str): Name of the exchange (e.g., 'pionex', 'mexc', 'bitmart')
        api_key (str): API key for the exchange
        secret_key (str): Secret key for the exchange
        memo (str, optional): memo for KuCoin or Memo for BitMart
        
    Returns:
        BaseExchangeClient: An instance of the appropriate exchange client, or None if not supported
    """
    exchange_name = exchange_name.lower()
    
    try:
        if exchange_name == 'pionex':
            return PionexClient(api_key, secret_key)
        elif exchange_name == 'mexc':
            return MexcClient(api_key, secret_key)
        elif exchange_name == 'bitmart':
            # For BitMart, use the memo parameter as the memo (private key)
            return BitMartClient(api_key, secret_key, memo)
        else:
            logger.error(f"Unsupported exchange: {exchange_name}")
            return None
    except Exception as e:
        logger.error(f"Error creating exchange client for {exchange_name}: {str(e)}")
        return None