# Exchange Integrations

This module provides a standardized interface for interacting with cryptocurrency exchanges. Each exchange is implemented using the same abstract base class to ensure consistent functionality across all supported platforms.

## Architecture

### BaseExchangeClient (Abstract Base Class)

The `BaseExchangeClient` class in `base.py` defines the interface that all exchange implementations must follow. It specifies methods for:

- Initializing and cleaning up resources
- Retrieving wallet balances
- Getting order books and ticker data
- Placing, checking, and canceling orders
- Retrieving available trading pairs
- Formatting trading pair symbols

### Exchange Implementations

Each supported exchange has its own implementation file:

- `binance.py`: Implementation for the Binance exchange
- `pionex.py`: Implementation for the Pionex exchange

### ExchangeFactory

The `factory.py` file provides a factory pattern for creating exchange client instances. This allows the application to dynamically select the appropriate exchange implementation at runtime.

## Adding a New Exchange

To add support for a new exchange:

1. Create a new Python file named after the exchange (e.g., `kraken.py`)
2. Import and subclass the `BaseExchangeClient` from `base.py`
3. Implement all required methods from the abstract base class
4. Update the `factory.py` file to include the new exchange

### Example Template

```python
from decimal import Decimal
from typing import Dict, List, Any
from .base import BaseExchangeClient

class NewExchangeClient(BaseExchangeClient):
    """
    Client for interacting with the New Exchange API.
    """
    
    BASE_URL = "https://api.newexchange.com"
    
    def __init__(self, api_key: str, secret_key: str):
        super().__init__(api_key, secret_key)
        # Exchange-specific initialization here
    
    async def initialize(self):
        """Initialize the HTTP session for API requests."""
        # Implementation here
    
    async def cleanup(self):
        """Close the HTTP session."""
        # Implementation here
    
    async def get_wallet_balance(self) -> Dict[str, Decimal]:
        """
        Retrieve wallet balances from the exchange.
        
        Returns:
            Dict[str, Decimal]: Dictionary mapping asset symbols to their balances
        """
        # Implementation here
    
    async def get_order_book(self, pair: str) -> Dict[str, List[List[Decimal]]]:
        """
        Retrieve the order book for a trading pair.
        
        Args:
            pair (str): Trading pair symbol (e.g., 'BTC_USDT')
            
        Returns:
            Dict containing 'bids' and 'asks' lists, where each entry is [price, quantity]
        """
        # Implementation here
    
    async def get_24h_ticker(self, pair: str) -> Dict[str, Any]:
        """
        Retrieve 24-hour ticker data for a trading pair.
        
        Args:
            pair (str): Trading pair symbol
            
        Returns:
            Dict containing ticker data (high, low, volume, etc.)
        """
        # Implementation here
    
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
        # Implementation here
    
    async def get_pairs(self) -> List[Dict[str, Any]]:
        """
        Get all available trading pairs from the exchange.
        
        Returns:
            List of dictionaries containing pair information
        """
        # Implementation here
    
    async def get_order_status(self, order_id: str, pair: str) -> Dict[str, Any]:
        """
        Get the status of an order.
        
        Args:
            order_id (str): Order ID to check
            pair (str): Trading pair for the order
            
        Returns:
            Dict containing order status information
        """
        # Implementation here
    
    async def cancel_order(self, order_id: str, pair: str) -> bool:
        """
        Cancel an order on the exchange.
        
        Args:
            order_id (str): Order ID to cancel
            pair (str): Trading pair for the order
            
        Returns:
            bool: True if cancellation was successful, False otherwise
        """
        # Implementation here
    
    def format_pair(self, pair: str) -> str:
        """
        Format a trading pair symbol according to the exchange's requirements.
        
        Args:
            pair (str): Trading pair symbol (e.g., 'BTC_USDT')
            
        Returns:
            str: Formatted trading pair symbol
        """
        # Implementation here
```

## Exchange-Specific Considerations

Each exchange has its own API quirks and requirements. Here are some common considerations when implementing a new exchange:

### Authentication

Most exchanges require API key authentication for private endpoints. Typically, this involves:

1. Including the API key in the request headers
2. Generating a signature using the secret key
3. Adding a timestamp or nonce to prevent replay attacks

### Rate Limiting

Exchanges impose rate limits on API requests. Consider implementing:

- Request rate limiting to avoid being temporarily banned
- Exponential backoff for retrying failed requests
- Proper error handling for rate limit exceptions

### Symbol Format

Different exchanges use different formats for trading pair symbols:

- Binance: `BTCUSDT`
- Some exchanges: `BTC/USDT`
- Others: `BTC-USDT`

The `format_pair` method should handle these conversions.

### Precision

Exchanges have different rules for price and quantity precision:

- Some require a specific number of decimal places
- Others require amounts to be within a specific range
- Some have minimum order sizes

## Error Handling

When implementing exchange methods, ensure proper error handling:

- Network errors (timeouts, connection failures)
- API errors (invalid parameters, insufficient funds)
- Authentication errors (invalid credentials, expired tokens)
- Rate limiting errors

All errors should be logged appropriately and propagated to the caller with meaningful context.