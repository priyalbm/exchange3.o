import abc
import asyncio
import logging
from decimal import Decimal
from typing import Dict, List, Tuple, Optional, Any

logger = logging.getLogger('bot')

class BaseExchangeClient(abc.ABC):
    """
    Abstract base class for cryptocurrency exchange clients.
    All exchange implementations must inherit from this class.
    """
    
    def __init__(self, api_key: str, secret_key: str):
        """
        Initialize the exchange client with API credentials.
        
        Args:
            api_key (str): API key for the exchange
            secret_key (str): Secret key for the exchange
        """
        self.api_key = api_key
        self.secret_key = secret_key
        self.session = None
        
    async def initialize(self):
        """Initialize any resources needed by the client."""
        pass
    
    async def cleanup(self):
        """Cleanup any resources used by the client."""
        pass
    
    @abc.abstractmethod
    async def get_wallet_balance(self) -> Dict[str, Decimal]:
        """
        Retrieve wallet balances from the exchange.
        
        Returns:
            Dict[str, Decimal]: Dictionary mapping asset symbols to their balances
        """
        pass
    
    @abc.abstractmethod
    async def get_order_book(self, pair: str) -> Dict[str, List[List[Decimal]]]:
        """
        Retrieve the order book for a trading pair.
        
        Args:
            pair (str): Trading pair symbol (e.g., 'BTC_USDT')
            
        Returns:
            Dict containing 'bids' and 'asks' lists, where each entry is [price, quantity]
        """
        pass
    
    @abc.abstractmethod
    async def get_24h_ticker(self, pair: str) -> Dict[str, Any]:
        """
        Retrieve 24-hour ticker data for a trading pair.
        
        Args:
            pair (str): Trading pair symbol
            
        Returns:
            Dict containing ticker data (high, low, volume, etc.)
        """
        pass
    
    @abc.abstractmethod
    async def place_order(self, order_type: str, pair: str, volume: Decimal, price: Decimal) -> Dict[str, Any]:
        """
        Place an order on the exchange.
        
        Args:
            order_type (str): 'buy' or 'sell'
            pair (str): Trading pair symbol
            volume (Decimal): Order quantity
            price (Decimal): Order price
            
        Returns:
            Dict containing order details including order ID
        """
        pass
    
    @abc.abstractmethod
    async def get_pairs(self) -> List[Dict[str, Any]]:
        """
        Get all available trading pairs from the exchange.
        
        Returns:
            List of dictionaries containing pair information
        """
        pass
    
    @abc.abstractmethod
    async def get_order_status(self, order_id: str, pair: str) -> Dict[str, Any]:
        """
        Get the status of an order.
        
        Args:
            order_id (str): Order ID to check
            pair (str): Trading pair for the order
            
        Returns:
            Dict containing order status information
        """
        pass
    
    @abc.abstractmethod
    async def cancel_order(self, order_id: str, pair: str) -> bool:
        """
        Cancel an order on the exchange.
        
        Args:
            order_id (str): Order ID to cancel
            pair (str): Trading pair for the order
            
        Returns:
            bool: True if cancellation was successful, False otherwise
        """
        pass
    
    def format_pair(self, pair: str) -> str:
        """
        Format a trading pair symbol according to the exchange's requirements.
        
        Args:
            pair (str): Trading pair symbol (e.g., 'BTC_USDT')
            
        Returns:
            str: Formatted trading pair symbol
        """
        return pair
