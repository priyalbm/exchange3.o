import asyncio
import hmac
import hashlib
import json
import time
import logging
import aiohttp
import base64
from decimal import Decimal
from typing import Dict, List, Any, Optional, Tuple
from urllib.parse import urlencode

from .base import BaseExchangeClient

logger = logging.getLogger('kucoin')

class KuCoinClient(BaseExchangeClient):
    """
    Client for interacting with the KuCoin exchange API.
    Documentation: https://www.kucoin.com/docs-new/
    """

    BASE_URL = "https://api.kucoin.com"

    def __init__(self, api_key: str, secret_key: str, passphrase: str = None):
        super().__init__(api_key, secret_key)
        self.passphrase = passphrase or ""  # KuCoin requires a passphrase
        self.session = None

    async def __aenter__(self):
        """Support for async context manager."""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Support for async context manager."""
        await self.cleanup()

    async def initialize(self):
        """Initialize the HTTP session for API requests."""
        if self.session is None:
            self.session = aiohttp.ClientSession()
        logger.debug("KuCoin client initialized")

    async def cleanup(self):
        """Close the HTTP session."""
        if self.session:
            await self.session.close()
            self.session = None
        logger.debug("KuCoin client cleaned up")

    def _generate_signature(self, method: str, endpoint: str, params: Dict[str, Any] = None, body: Dict[str, Any] = None) -> Dict[str, str]:
        """
        Generate the signature required for authenticated requests.
        
        Args:
            method (str): HTTP method (GET, POST, DELETE)
            endpoint (str): API endpoint path
            params (Dict[str, Any], optional): Query parameters
            body (Dict[str, Any], optional): Request body for POST requests
            
        Returns:
            Dict[str, str]: Dictionary containing signature and timestamp
        """
        timestamp = str(int(time.time() * 1000))
        
        # Create query string if params exist
        query_string = ""
        if params:
            query_string = "?" + urlencode(params)
        
        # Create signature base
        body_str = json.dumps(body) if body else ""
        signature_payload = f"{timestamp}{method}{endpoint}{query_string}{body_str}"
        
        # Generate HMAC-SHA256 signature
        signature = base64.b64encode(
            hmac.new(
                self.secret_key.encode('utf-8'),
                signature_payload.encode('utf-8'),
                hashlib.sha256
            ).digest()
        ).decode('utf-8')
        
        # Generate passphrase signature
        passphrase = base64.b64encode(
            hmac.new(
                self.secret_key.encode('utf-8'),
                self.passphrase.encode('utf-8'),
                hashlib.sha256
            ).digest()
        ).decode('utf-8')
        
        return {
            "KC-API-SIGN": signature,
            "KC-API-TIMESTAMP": timestamp,
            "KC-API-KEY": self.api_key,
            "KC-API-PASSPHRASE": passphrase,
            "KC-API-KEY-VERSION": "2"  # API key version 2
        }

    async def _make_request(self, method: str, endpoint: str, params: Dict[str, Any] = None, 
                       body: Dict[str, Any] = None, auth_required: bool = False,
                       max_retries: int = 3, retry_delay: float = 1.0) -> Dict[str, Any]:
        """
        Make an HTTP request to the KuCoin API with retry logic.
        
        Args:
            method (str): HTTP method (GET, POST, DELETE)
            endpoint (str): API endpoint path
            params (Dict[str, Any], optional): Query parameters
            body (Dict[str, Any], optional): Request body for POST requests
            auth_required (bool): Whether authentication is required
            max_retries (int): Maximum number of retry attempts
            retry_delay (float): Delay between retries (exponential backoff applied)
            
        Returns:
            Dict[str, Any]: API response
        """
        if not self.session:
            await self.initialize()

        url = f"{self.BASE_URL}{endpoint}"
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}

        # Add authentication headers if required
        if auth_required:
            auth_headers = self._generate_signature(method, endpoint, params, body)
            headers.update(auth_headers)

        retry_count = 0
        last_error = None

        while retry_count < max_retries:
            try:
                # Construct query string for GET requests
                if params and method == 'GET':
                    url = f"{url}?{urlencode(params)}"
                    params = None  # Clear params since they're now in the URL

                # Log request details for debugging
                logger.debug(f"Making {method} request to {url}")
                logger.debug(f"Headers: {headers}")
                if body:
                    logger.debug(f"Body: {body}")

                if method == 'GET':
                    response = await self.session.get(url, headers=headers)
                elif method == 'POST':
                    response = await self.session.post(url, headers=headers, json=body)
                elif method == 'DELETE':
                    response = await self.session.delete(url, headers=headers, json=body)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")

                # Get response text
                response_text = await response.text()
                
                # Log the response for debugging
                logger.debug(f"Response status: {response.status}")
                logger.debug(f"Response text: {response_text[:500]}")

                # For 500 errors, retry
                if response.status >= 500:
                    retry_count += 1
                    wait_time = retry_delay * (2 ** retry_count)  # Exponential backoff
                    logger.warning(f"Received {response.status} error, retrying in {wait_time}s (attempt {retry_count}/{max_retries})")
                    await asyncio.sleep(wait_time)
                    last_error = f"HTTP {response.status}: {response_text[:100]}..."
                    continue

                # Try to parse response as JSON
                try:
                    if response_text.strip():
                        response_data = json.loads(response_text)
                        
                        # Check if the response contains an error message
                        if 'code' in response_data and response_data['code'] != '200000':
                            error_msg = response_data.get('msg', 'Unknown error')
                            logger.error(f"KuCoin API error response: {error_msg}")
                            return {
                                'success': False, 
                                'error': error_msg,
                                'code': response_data.get('code', ''),
                                'response_data': response_data
                            }

                        return response_data
                    else:
                        return {'success': False, 'error': 'Empty response from server'}
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse JSON response: {str(e)}")
                    return {'success': False, 'error': f'Invalid JSON response: {response_text[:100]}...'}

            except aiohttp.ClientError as e:
                retry_count += 1
                wait_time = retry_delay * (2 ** retry_count)
                logger.warning(f"HTTP error: {str(e)}, retrying in {wait_time}s (attempt {retry_count}/{max_retries})")
                await asyncio.sleep(wait_time)
                last_error = f"HTTP error: {str(e)}"
                continue
            except Exception as e:
                logger.error(f"Error making request to KuCoin API: {str(e)}")
                return {'success': False, 'error': str(e)}

        # If we've exhausted all retries
        return {'success': False, 'error': f"Max retries exceeded. Last error: {last_error}"}

    async def get_wallet_balance(self) -> Dict[str, Any]:
        """
        Retrieve wallet balances from KuCoin.
        
        Returns:
            Dict[str, Dict]: Dictionary mapping asset symbols to their balances
        """
        try:
            # KuCoin endpoint for account balances
            response = await self._make_request('GET', '/api/v1/accounts', auth_required=True)

            # Check if we got a valid response
            if not response or not isinstance(response, dict):
                logger.error(f"Invalid response format from KuCoin API: {response}")
                return {'error': 'Invalid response format from KuCoin API'}

            # Check for error first
            if 'success' in response and response['success'] is False:
                logger.error(f"Error in wallet balance response: {response.get('error', 'Unknown error')}")
                return response

            # Extract balances from the response according to KuCoin API structure
            balances = {}
            if 'data' in response:
                for asset in response['data']:
                    symbol = asset.get('currency', '')
                    free = Decimal(str(asset.get('available', '0')))
                    locked = Decimal(str(asset.get('holds', '0')))
                    total = Decimal(str(asset.get('balance', '0')))

                    # Include all assets, even with zero balance for completeness
                    balances[symbol] = {
                        'free': str(free),
                        'locked': str(locked),
                        'total': str(total)
                    }
                logger.info(f"Retrieved balances for {len(balances)} assets")
                return balances
            else:
                # Return whole response for debugging
                logger.error(f"Unexpected response format in wallet balance: {response}")
                return {'error': 'Unexpected response format', 'data': response}

        except Exception as e:
            logger.error(f"Error processing wallet balance: {str(e)}")
            return {'error': f"Exception: {str(e)}"}

    async def get_order_book(self, pair: str) -> Dict[str, Any]:
        """
        Retrieve the order book for a trading pair.
        
        Args:
            pair (str): Trading pair symbol (e.g., 'BTC_USDT')
            
        Returns:
            Dict containing 'bids' and 'asks' lists, where each entry is [price, quantity]
        """
        formatted_pair = self.format_pair(pair)
        response = await self._make_request('GET', f"/api/v1/market/orderbook/level2_20", params={"symbol": formatted_pair})
        
        # Check for error response
        if 'success' in response and response['success'] is False:
            return response

        result = {
            'bids': [],
            'asks': []
        }

        # Check if we have a valid data section
        if 'data' in response:
            data = response['data']
            # Extract bids and asks according to KuCoin structure
            if 'bids' in data and 'asks' in data:
                # Convert string values to Decimal
                for bid in data.get('bids', []):
                    if len(bid) >= 2:
                        result['bids'].append([Decimal(str(bid[0])), Decimal(str(bid[1]))])

                for ask in data.get('asks', []):
                    if len(ask) >= 2:
                        result['asks'].append([Decimal(str(ask[0])), Decimal(str(ask[1]))])

                return result

        # Return full response for debugging if structure doesn't match expectations
        return {'error': 'Unexpected order book response format', 'data': response}

    async def get_24h_ticker(self, pair: str) -> Dict[str, Any]:
        """
        Retrieve 24-hour ticker data for a trading pair.
        
        Args:
            pair (str): Trading pair symbol
            
        Returns:
            Dict containing ticker data (high, low, volume, etc.)
        """
        formatted_pair = self.format_pair(pair)
        response = await self._make_request('GET', f"/api/v1/market/stats", params={"symbol": formatted_pair})

        # Check for error response
        if 'success' in response and response['success'] is False:
            return response

        # Process response according to KuCoin API structure
        try:
            if 'data' in response:
                ticker = response['data']
                return {
                    'symbol': formatted_pair,
                    'open': str(Decimal(str(ticker.get('open', '0')))),
                    'high': str(Decimal(str(ticker.get('high', '0')))),
                    'low': str(Decimal(str(ticker.get('low', '0')))),
                    'close': str(Decimal(str(ticker.get('last', '0')))),
                    'volume': str(Decimal(str(ticker.get('vol', '0')))),
                    'time': ticker.get('time', 0)
                }
            else:
                return {'error': 'No ticker data found', 'data': response}
        except (ValueError, TypeError) as e:
            logger.error(f"Error processing ticker data: {str(e)}")
            return {'error': 'Invalid ticker data format', 'data': response}

    async def get_ticker_price(self, symbol: str) -> Dict[str, Any]:
        """
        Get the current price for a trading pair.
        
        Args:
            symbol (str): The trading pair symbol (e.g., 'BTC_USDT')
            
        Returns:
            Dict: The ticker information including current price
        """
        try:
            formatted_pair = self.format_pair(symbol)
            response = await self._make_request('GET', f'/api/v1/market/orderbook/level1', params={"symbol": formatted_pair})
            
            # Check if we got a valid response
            if not response or not isinstance(response, dict):
                logger.error(f"Invalid response format from KuCoin API for ticker price: {response}")
                return {'error': 'Invalid response format from KuCoin API'}
                
            # Check for error first
            if 'success' in response and response['success'] is False:
                logger.error(f"Error in ticker price response: {response.get('error', 'Unknown error')}")
                return response
                
            # Extract the price from the response
            if 'data' in response:
                data = response['data']
                return {
                    'symbol': symbol,
                    'price': data.get('price', '0')
                }
            else:
                logger.error(f"Unexpected response format for ticker price: {response}")
                return {'error': 'Unexpected response format', 'data': response}
                
        except Exception as e:
            logger.error(f"Error getting ticker price for {symbol}: {str(e)}")
            return {'error': f"Exception: {str(e)}"}

    async def place_order(self, order_type: str, pair: str, volume: Decimal, price: Decimal) -> Dict[str, Any]:
        """
        Place an order on KuCoin.
        
        Args:
            order_type (str): 'buy' or 'sell'
            pair (str): Trading pair symbol
            volume (Decimal): Order quantity
            price (Decimal): Order price
            
        Returns:
            Dict containing order details including order ID
        """
        formatted_pair = self.format_pair(pair)

        # Convert Decimal to string to avoid JSON serialization issues
        price_str = str(price)
        volume_str = str(volume)
        
        # Prepare order data according to KuCoin API
        body = {
            "clientOid": f"kucoin_{int(time.time() * 1000)}",  # Unique client order ID
            "side": order_type.upper(),   # 'BUY' or 'SELL'
            "symbol": formatted_pair,
            "type": "limit",              # Using 'limit' order type
            "price": price_str,           # Limit price
            "size": volume_str            # Quantity in base asset
        }
        
        logger.info(f"Placing {order_type.upper()} order: {volume_str} {pair} at {price_str}")
        
        try:
            response = await self._make_request('POST', "/api/v1/orders", body=body, auth_required=True)
            
            # Check if the response is a success
            if 'data' in response and 'orderId' in response['data']:
                data = response['data']
                order_id = data.get('orderId', '')
                logger.info(f"Order placed successfully: ID={order_id}")
                return {
                    'success': True,
                    'order_id': order_id,
                    'symbol': formatted_pair,
                    'type': order_type.upper(),
                    'price': price_str,
                    'size': volume_str,
                    'status': 'NEW'
                }
            else:
                # Extract error information
                error_msg = response.get('msg', 'Unknown error')
                error_code = response.get('code', 'UNKNOWN_ERROR')
                
                logger.error(f"Order placement failed: {error_code} - {error_msg}")
                return {
                    'success': False, 
                    'error': f"{error_code}: {error_msg}",
                    'code': error_code,
                    'message': error_msg
                }
                
        except Exception as e:
            logger.error(f"Exception placing order: {str(e)}")
            return {'success': False, 'error': f"Exception: {str(e)}"}

    async def get_pairs(self) -> List[Dict[str, Any]]:
        """
        Get all available trading pairs from KuCoin.
        
        Returns:
            List of dictionaries containing pair information
        """
        response = await self._make_request('GET', '/api/v1/symbols')

        # Check for error response
        if 'success' in response and response['success'] is False:
            return [response]

        pairs = []
        if 'data' in response:
            for symbol_info in response['data']:
                try:
                    base_asset = symbol_info.get('baseCurrency', '')
                    quote_asset = symbol_info.get('quoteCurrency', '')
                    symbol = symbol_info.get('symbol', '')

                    # Extract precision information
                    price_precision = int(symbol_info.get('priceIncrement', '0.00000001').count('0') - 1)
                    quantity_precision = int(symbol_info.get('baseIncrement', '0.00000001').count('0') - 1)

                    # Extract min/max quantity
                    min_quantity = symbol_info.get('baseMinSize', '0')
                    max_quantity = symbol_info.get('baseMaxSize', None)

                    # Add to pairs list
                    pairs.append({
                        'symbol': symbol,
                        'base_asset': base_asset,
                        'quote_asset': quote_asset,
                        'price_precision': price_precision,
                        'quantity_precision': quantity_precision,
                        'min_quantity': min_quantity,
                        'max_quantity': max_quantity
                    })
                except Exception as e:
                    logger.error(f"Error processing symbol info: {str(e)}")
                    continue
        else:
            logger.error(f"Failed to get trading pairs: Unexpected response format")
            return [{'error': 'Unexpected response format', 'data': response}]

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
        response = await self._make_request('GET', f'/api/v1/orders/{order_id}', auth_required=True)

        # Check for error response
        if 'success' in response and response['success'] is False:
            return response

        # Process successful order status request
        try:
            if 'data' in response:
                data = response['data']

                # Map KuCoin order status to our standard format
                status_mapping = {
                    'active': 'open',
                    'done': 'filled',
                    'cancelled': 'canceled',
                    'cancelling': 'canceling',
                    'partially_filled': 'partially_filled'
                }

                kucoin_status = data.get('isActive', True)
                kucoin_status_str = 'active' if kucoin_status else 'done'
                if not kucoin_status and data.get('cancelExist', False):
                    kucoin_status_str = 'cancelled'
                
                mapped_status = status_mapping.get(kucoin_status_str, 'unknown')
                
                # If order is done but has deals, it's filled
                if mapped_status == 'done' and Decimal(str(data.get('dealSize', '0'))) > 0:
                    mapped_status = 'filled'

                return {
                    'order_id': data.get('id', ''),
                    'symbol': data.get('symbol', ''),
                    'price': str(Decimal(str(data.get('price', '0')))),
                    'quantity': str(Decimal(str(data.get('size', '0')))),
                    'executed_qty': str(Decimal(str(data.get('dealSize', '0')))),
                    'status': mapped_status,
                    'side': data.get('side', '').lower(),
                    'type': data.get('type', ''),
                }
            else:
                return {'error': 'Order data not found in response', 'data': response}
        except Exception as e:
            logger.error(f"Error processing order status response: {str(e)}")
            return {'error': 'Invalid order status format', 'data': response}

    async def get_open_orders(self, pair: str = None) -> List[Dict[str, Any]]:
        """
        Get all open orders for a symbol or all symbols.
        
        Args:
            pair (str, optional): Trading pair symbol. If None, get all open orders.
            
        Returns:
            List of dictionaries containing order information
        """
        params = {}
        if pair:
            formatted_pair = self.format_pair(pair)
            params['symbol'] = formatted_pair

        response = await self._make_request('GET', '/api/v1/orders', params=params, auth_required=True)

        # Check for error response
        if 'success' in response and response['success'] is False:
            return [response]

        orders = []

        # Extract orders from the response
        if 'data' in response and 'items' in response['data']:
            order_list = response['data']['items']

            # Map status codes to our format
            status_mapping = {
                'active': 'open',
                'done': 'filled',
                'cancelled': 'canceled',
                'cancelling': 'canceling',
                'partially_filled': 'partially_filled'
            }

            for order in order_list:
                try:
                    kucoin_status = order.get('isActive', True)
                    kucoin_status_str = 'active' if kucoin_status else 'done'
                    if not kucoin_status and order.get('cancelExist', False):
                        kucoin_status_str = 'cancelled'
                    
                    mapped_status = status_mapping.get(kucoin_status_str, 'unknown')

                    orders.append({
                        'order_id': order.get('id', ''),
                        'symbol': order.get('symbol', ''),
                        'price': str(Decimal(str(order.get('price', '0')))),
                        'quantity': str(Decimal(str(order.get('size', '0')))),
                        'executed_qty': str(Decimal(str(order.get('dealSize', '0')))),
                        'status': mapped_status,
                        'side': order.get('side', '').lower(),
                        'type': order.get('type', '')
                    })
                except Exception as e:
                    logger.error(f"Error processing order: {str(e)}")
                    continue
        else:
            return [{'error': 'Unexpected response format', 'data': response}]

        return orders

    async def cancel_order(self, order_id: str, pair: str) -> Dict[str, Any]:
        """
        Cancel an order on KuCoin.
        
        Args:
            order_id (str): Order ID to cancel
            pair (str): Trading pair for the order
            
        Returns:
            Dict containing cancel order response or success/failure
        """
        response = await self._make_request('DELETE', f'/api/v1/orders/{order_id}', auth_required=True)

        # Check for error response
        if 'success' in response and response['success'] is False:
            return response

        # Process successful cancel request
        if 'data' in response:
            cancel_id = response['data'].get('cancelledOrderIds', [order_id])[0]
            return {
                'success': True,
                'order_id': order_id,
                'cancel_id': cancel_id,
                'message': 'Order cancelled successfully'
            }
        else:
            return {'success': False, 'error': 'Unexpected response format', 'data': response}

    async def cancel_all_orders(self, pair: str) -> Dict[str, Any]:
        """
        Cancel all orders for a specific symbol.
        
        Args:
            pair (str): Trading pair symbol
            
        Returns:
            Dict containing success status and count of canceled orders
        """
        formatted_pair = self.format_pair(pair)
        params = {'symbol': formatted_pair}
        
        response = await self._make_request('DELETE', '/api/v1/orders', params=params, auth_required=True)

        # Check for error response
        if 'success' in response and response['success'] is False:
            return response

        # Process successful cancel all request
        if 'data' in response:
            cancelled_order_ids = response['data'].get('cancelledOrderIds', [])
            return {
                'success': True,
                'symbol': formatted_pair,
                'message': 'All orders cancelled successfully',
                'cancelled_orders': cancelled_order_ids,
                'count': len(cancelled_order_ids)
            }
        else:
            return {'success': False, 'error': 'Unexpected response format', 'data': response}

    def format_pair(self, pair: str) -> str:
        """
        Format a trading pair symbol for KuCoin API.
        
        Args:
            pair (str): Trading pair in format like BTC_USDT or BTC/USDT or BTCUSDT
            
        Returns:
            str: Formatted pair symbol for KuCoin API (e.g., BTC-USDT)
        """
        if not pair:
            logger.error("Empty trading pair provided")
            return ""
            
        # Handle various formats (BTC_USDT, BTC/USDT, BTCUSDT)
        if '_' in pair:
            base, quote = pair.split('_')
            return f"{base}-{quote}"  # KuCoin uses hyphens
        elif '/' in pair:
            base, quote = pair.split('/')
            return f"{base}-{quote}"
        elif '-' in pair:
            return pair  # Already in KuCoin format
        else:
            # Try to detect if this is a combined pair (like BTCUSDT)
            common_quote_assets = ['USDT', 'BTC', 'ETH', 'KCS', 'USDC']
            for quote in common_quote_assets:
                if pair.endswith(quote) and len(pair) > len(quote):
                    base = pair[:-len(quote)]
                    return f"{base}-{quote}"
                    
            # If we can't detect a pattern, return as-is
            return pair
