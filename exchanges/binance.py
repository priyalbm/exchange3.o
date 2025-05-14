import asyncio
import hmac
import hashlib
import time
import logging
import json
import aiohttp
from decimal import Decimal
from typing import Dict, List, Any, Optional, Tuple
from urllib.parse import urlencode

from .base import BaseExchangeClient

logger = logging.getLogger('bot')

class BinanceClient(BaseExchangeClient):
    """
    Client for interacting with the Binance exchange API.
    """
    
    BASE_URL = "https://api.binance.com"
    
    def __init__(self, api_key: str, secret_key: str):
        super().__init__(api_key, secret_key)
        self.session = None
    
    async def initialize(self):
        """Initialize the HTTP session for API requests."""
        if self.session is None:
            self.session = aiohttp.ClientSession()
        logger.debug("Binance client initialized")
    
    async def cleanup(self):
        """Close the HTTP session."""
        if self.session:
            await self.session.close()
            self.session = None
        logger.debug("Binance client cleaned up")
    
    def _generate_signature(self, params: Dict[str, Any]) -> str:
        """
        Generate the signature required for authenticated requests.
        
        Args:
            params (Dict[str, Any]): Parameters to include in the signature
            
        Returns:
            str: Signature for the request
        """
        # Convert params to a query string
        query_string = urlencode(params)
        
        # Create signature using HMAC SHA256
        signature = hmac.new(
            self.secret_key.encode(),
            query_string.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return signature
    
    async def _make_request(self, method: str, endpoint: str, params: Dict[str, Any] = None, 
                           auth_required: bool = False) -> Dict[str, Any]:
        """
        Make an HTTP request to the Binance API.
        
        Args:
            method (str): HTTP method (GET, POST, etc.)
            endpoint (str): API endpoint
            params (Dict[str, Any], optional): Request parameters
            auth_required (bool): Whether authentication is required
            
        Returns:
            Dict[str, Any]: API response
        """
        if not self.session:
            await self.initialize()
        
        url = f"{self.BASE_URL}{endpoint}"
        headers = {'X-MBX-APIKEY': self.api_key} if auth_required else {}
        
        if params is None:
            params = {}
        
        if auth_required:
            # Add timestamp parameter required for authenticated requests
            params['timestamp'] = int(time.time() * 1000)
            
            # Generate signature and add it to params
            signature = self._generate_signature(params)
            params['signature'] = signature
        
        try:
            if method == 'GET':
                if params:
                    query_string = urlencode(params)
                    url = f"{url}?{query_string}"
                response = await self.session.get(url, headers=headers)
            elif method == 'POST':
                if auth_required:
                    # For Binance POST requests, parameters go in the query string, not the body
                    query_string = urlencode(params)
                    url = f"{url}?{query_string}"
                    response = await self.session.post(url, headers=headers)
                else:
                    response = await self.session.post(url, headers=headers, json=params)
            elif method == 'DELETE':
                if params:
                    query_string = urlencode(params)
                    url = f"{url}?{query_string}"
                response = await self.session.delete(url, headers=headers)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            # Check if request was successful
            if response.status != 200:
                error_text = await response.text()
                logger.error(f"Binance API error: {response.status} - {error_text}")
                return {'success': False, 'error': f"HTTP {response.status}: {error_text}"}
            
            # Parse response
            response_data = await response.json()
            
            # Add success flag for consistency with other exchange implementations
            if isinstance(response_data, dict) and 'code' in response_data and response_data['code'] != 0:
                response_data['success'] = False
            else:
                response_data = {'success': True, 'data': response_data}
            
            return response_data
        except Exception as e:
            logger.error(f"Error making request to Binance API: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    async def get_wallet_balance(self) -> Dict[str, Decimal]:
        """
        Retrieve wallet balances from Binance.
        
        Returns:
            Dict[str, Decimal]: Dictionary mapping asset symbols to their balances
        """
        response = await self._make_request('GET', '/api/v3/account', auth_required=True)
        
        balances = {}
        if response.get('success', False):
            for asset in response.get('data', {}).get('balances', []):
                symbol = asset.get('asset', '')
                free = Decimal(str(asset.get('free', '0')))
                locked = Decimal(str(asset.get('locked', '0')))
                total = free + locked
                
                # Only include assets with non-zero balance
                if total > 0:
                    balances[symbol] = total
        else:
            logger.error(f"Failed to get wallet balance: {response.get('error', 'Unknown error')}")
        
        return balances
    
    async def get_order_book(self, pair: str) -> Dict[str, List[List[Decimal]]]:
        """
        Retrieve the order book for a trading pair.
        
        Args:
            pair (str): Trading pair symbol (e.g., 'BTC_USDT')
            
        Returns:
            Dict containing 'bids' and 'asks' lists, where each entry is [price, quantity]
        """
        formatted_pair = self.format_pair(pair)
        params = {'symbol': formatted_pair, 'limit': 100}  # Limit to 100 price levels
        response = await self._make_request('GET', '/api/v3/depth', params)
        
        result = {
            'bids': [],
            'asks': []
        }
        
        if response.get('success', False):
            data = response.get('data', {})
            
            # Convert string values to Decimal
            for bid in data.get('bids', []):
                result['bids'].append([Decimal(str(bid[0])), Decimal(str(bid[1]))])
            
            for ask in data.get('asks', []):
                result['asks'].append([Decimal(str(ask[0])), Decimal(str(ask[1]))])
        else:
            logger.error(f"Failed to get order book: {response.get('error', 'Unknown error')}")
        
        return result
    
    async def get_24h_ticker(self, pair: str) -> Dict[str, Any]:
        """
        Retrieve 24-hour ticker data for a trading pair.
        
        Args:
            pair (str): Trading pair symbol
            
        Returns:
            Dict containing ticker data (high, low, volume, etc.)
        """
        formatted_pair = self.format_pair(pair)
        params = {'symbol': formatted_pair}
        response = await self._make_request('GET', '/api/v3/ticker/24hr', params)
        
        result = {}
        if response.get('success', False):
            ticker = response.get('data', {})
            
            # Convert string values to Decimal
            result = {
                'symbol': ticker.get('symbol', formatted_pair),
                'high': Decimal(str(ticker.get('highPrice', '0'))),
                'low': Decimal(str(ticker.get('lowPrice', '0'))),
                'volume': Decimal(str(ticker.get('volume', '0'))),
                'last_price': Decimal(str(ticker.get('lastPrice', '0'))),
                'change_percent': Decimal(str(ticker.get('priceChangePercent', '0')))
            }
        else:
            logger.error(f"Failed to get 24h ticker: {response.get('error', 'Unknown error')}")
        
        return result
    
    async def place_order(self, order_type: str, pair: str, volume: Decimal, price: Decimal) -> Dict[str, Any]:
        """
        Place an order on Binance.
        
        Args:
            order_type (str): 'buy' or 'sell'
            pair (str): Trading pair symbol
            volume (Decimal): Order quantity
            price (Decimal): Order price
            
        Returns:
            Dict containing order details including order ID
        """
        formatted_pair = self.format_pair(pair)
        
        # Prepare parameters for order placement
        params = {
            'symbol': formatted_pair,
            'side': order_type.upper(),
            'type': 'LIMIT',
            'timeInForce': 'GTC',  # Good Till Canceled
            'quantity': str(volume),
            'price': str(price)
        }
        
        response = await self._make_request('POST', '/api/v3/order', params, auth_required=True)
        
        if response.get('success', False):
            order_data = response.get('data', {})
            return {
                'order_id': str(order_data.get('orderId', '')),
                'symbol': order_data.get('symbol', formatted_pair),
                'price': Decimal(str(order_data.get('price', price))),
                'quantity': Decimal(str(order_data.get('origQty', volume))),
                'type': order_data.get('side', '').lower(),
                'status': order_data.get('status', 'OPEN')
            }
        else:
            logger.error(f"Failed to place {order_type} order: {response.get('error', 'Unknown error')}")
            return {'success': False, 'error': response.get('error', 'Unknown error')}
    
    async def get_pairs(self) -> List[Dict[str, Any]]:
        """
        Get all available trading pairs from Binance.
        
        Returns:
            List of dictionaries containing pair information
        """
        response = await self._make_request('GET', '/api/v3/exchangeInfo')
        
        pairs = []
        if response.get('success', False):
            for symbol_info in response.get('data', {}).get('symbols', []):
                # Skip pairs that are not trading
                if symbol_info.get('status') != 'TRADING':
                    continue
                
                base_asset = symbol_info.get('baseAsset', '')
                quote_asset = symbol_info.get('quoteAsset', '')
                symbol = symbol_info.get('symbol', '')
                
                # Extract precision information
                price_precision = 8
                quantity_precision = 8
                min_quantity = Decimal('0')
                max_quantity = None
                
                # Extract precision and quantity constraints from filters
                for filter_info in symbol_info.get('filters', []):
                    if filter_info.get('filterType') == 'PRICE_FILTER':
                        # Calculate price precision from tickSize
                        tick_size = Decimal(str(filter_info.get('tickSize', '0.00000001')))
                        price_precision = max(0, -tick_size.as_tuple().exponent)
                    
                    elif filter_info.get('filterType') == 'LOT_SIZE':
                        # Calculate quantity precision from stepSize
                        step_size = Decimal(str(filter_info.get('stepSize', '0.00000001')))
                        quantity_precision = max(0, -step_size.as_tuple().exponent)
                        
                        min_quantity = Decimal(str(filter_info.get('minQty', '0')))
                        if 'maxQty' in filter_info and filter_info['maxQty'] != '0':
                            max_quantity = Decimal(str(filter_info.get('maxQty')))
                
                pairs.append({
                    'symbol': symbol,
                    'base_asset': base_asset,
                    'quote_asset': quote_asset,
                    'price_precision': price_precision,
                    'quantity_precision': quantity_precision,
                    'min_quantity': min_quantity,
                    'max_quantity': max_quantity
                })
        else:
            logger.error(f"Failed to get trading pairs: {response.get('error', 'Unknown error')}")
        
        return pairs
    
    async def get_order_status(self, order_id: str, pair: str) -> Dict[str, Any]:
        """
        Get the status of an order.
        
        Args:
            order_id (str): Order ID to check
            pair (str): Trading pair for the order
            
        Returns:
            Dict containing order status information
        """
        formatted_pair = self.format_pair(pair)
        params = {
            'symbol': formatted_pair,
            'orderId': order_id
        }
        
        response = await self._make_request('GET', '/api/v3/order', params, auth_required=True)
        
        if response.get('success', False):
            order_data = response.get('data', {})
            return {
                'order_id': str(order_data.get('orderId', '')),
                'symbol': order_data.get('symbol', formatted_pair),
                'price': Decimal(str(order_data.get('price', '0'))),
                'quantity': Decimal(str(order_data.get('origQty', '0'))),
                'executed_quantity': Decimal(str(order_data.get('executedQty', '0'))),
                'status': order_data.get('status', 'UNKNOWN'),
                'type': order_data.get('side', '').lower(),
                'time': order_data.get('time', 0)
            }
        else:
            logger.error(f"Failed to get order status: {response.get('error', 'Unknown error')}")
            return {'success': False, 'error': response.get('error', 'Unknown error')}
    
    async def cancel_order(self, order_id: str, pair: str) -> bool:
        """
        Cancel an order on Binance.
        
        Args:
            order_id (str): Order ID to cancel
            pair (str): Trading pair for the order
            
        Returns:
            bool: True if cancellation was successful, False otherwise
        """
        formatted_pair = self.format_pair(pair)
        params = {
            'symbol': formatted_pair,
            'orderId': order_id
        }
        
        response = await self._make_request('DELETE', '/api/v3/order', params, auth_required=True)
        
        if response.get('success', False):
            return True
        else:
            logger.error(f"Failed to cancel order: {response.get('error', 'Unknown error')}")
            return False
    
    def format_pair(self, pair: str) -> str:
        """
        Format a trading pair symbol according to Binance's requirements.
        
        Args:
            pair (str): Trading pair symbol (e.g., 'BTC_USDT')
            
        Returns:
            str: Formatted trading pair symbol
        """
        # Binance uses format like 'BTCUSDT' without separator
        if '_' in pair:
            return pair.replace('_', '')
        return pair
