import asyncio
import hmac
import hashlib
import json
import time
import logging
import aiohttp
from decimal import Decimal
from typing import Dict, List, Any, Optional, Tuple
from urllib.parse import urlencode

from .base import BaseExchangeClient

logger = logging.getLogger('pionex')

class PionexClient(BaseExchangeClient):
    """
    Client for interacting with the Pionex exchange API.
    Documentation: https://pionex-doc.gitbook.io/apidocs/
    """

    BASE_URL = "https://api.pionex.com"

    def __init__(self, api_key: str, secret_key: str):
        super().__init__(api_key, secret_key)
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
        logger.debug("Pionex client initialized")

    async def cleanup(self):
        """Close the HTTP session."""
        if self.session:
            await self.session.close()
            self.session = None
        logger.debug("Pionex client cleaned up")

    def _sort_object(self, obj):
        """Sort dictionary by keys for signature calculation."""
        return {k: obj[k] for k in sorted(obj.keys())}

    def _generate_signature(self, method: str, path: str, params: Dict[str, Any] = None, body: Dict[str, Any] = None) -> Dict[str, str]:
        """
        Generate the signature required for authenticated requests.
        Based on the working Flutter implementation.

        Args:
            method (str): HTTP method (GET, POST, DELETE)
            path (str): API endpoint path
            params (Dict[str, Any], optional): Query parameters
            body (Dict[str, Any], optional): Request body for POST requests

        Returns:
            Dict[str, str]: Dictionary containing signature and timestamp
        """
        timestamp = str(int(time.time() * 1000))
        
        # Create query string
        query = f"?timestamp={timestamp}"
        fullPath = f"{path}{query}"
        
        # Convert body to JSON string
        bodyJson = json.dumps(body) if body else ""
        
        # Create signature base - this matches the Flutter implementation exactly
        signatureBase = f"{method}{fullPath}{bodyJson}"
        
        logger.debug(f"📄 Signature Base: {signatureBase}")
        
        # Generate HMAC-SHA256 signature
        signature = hmac.new(
            self.secret_key.encode(),
            signatureBase.encode(),
            hashlib.sha256
        ).hexdigest()
        
        logger.debug(f"🔑 Signature: {signature}")
        logger.debug(f"➡️ Request Body: {bodyJson}")
        
        return {"signature": signature, "timestamp": timestamp}

    async def _make_request(self, method: str, path: str, params: Dict[str, Any] = None, 
                       body: Dict[str, Any] = None, auth_required: bool = False,
                       max_retries: int = 3, retry_delay: float = 1.0) -> Dict[str, Any]:
        """
        Make an HTTP request to the Pionex API with retry logic.
        Captures API error headers and includes them in the response.

        Args:
            method (str): HTTP method (GET, POST, DELETE)
            path (str): API endpoint path
            params (Dict[str, Any], optional): Query parameters
            body (Dict[str, Any], optional): Request body for POST requests
            auth_required (bool): Whether authentication is required
            max_retries (int): Maximum number of retry attempts
            retry_delay (float): Delay between retries (exponential backoff applied)

        Returns:
            Dict[str, Any]: API response with additional error information if available
        """
        if not self.session:
            await self.initialize()

        url = f"{self.BASE_URL}{path}"
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}

        if params is None:
            params = {}

        retry_count = 0
        last_error = None

        while retry_count < max_retries:
            try:
                # Create the full URL including timestamp for authenticated requests
                if auth_required:
                    # Generate signature based on the working Flutter implementation
                    sign_info = self._generate_signature(method, path, params, body)
                    
                    # This matches the headers in the Flutter implementation exactly
                    headers.update({
                        "PIONEX-KEY": self.api_key,
                        "PIONEX-SIGNATURE": sign_info["signature"]
                    })
                    
                    # Construct URL with timestamp exactly like in Flutter
                    query = f"?timestamp={sign_info['timestamp']}"
                    full_url = f"{self.BASE_URL}{path}{query}"
                else:
                    full_url = url

                # Log request details for debugging
                logger.debug(f"Making {method} request to {full_url}")
                logger.debug(f"Headers: {headers}")
                logger.debug(f"Body: {body}")

                if method == 'GET':
                    # For GET requests with the timestamp already in the URL
                    response = await self.session.get(full_url, headers=headers)
                elif method == 'POST':
                    # For POST requests, parameters go in the body as JSON
                    response = await self.session.post(full_url, headers=headers, json=body)
                    # print(response,"-=-=-=-==--=-=-=-=-=-=-=-=-==--=-==- response")
                elif method == 'DELETE':
                    # For DELETE requests with the timestamp already in the URL
                    response = await self.session.delete(full_url, headers=headers)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")
                    
                # Try to get response as text first
                response_text = await response.text()
                
                # Extract API error headers if they exist
                api_code = response.headers.get('X-Api-Code', '')
                api_message = response.headers.get('X-Api-Message', '')
                
                # Log the raw response for debugging
                logger.debug(f"Response status: {response.status}")
                logger.debug(f"Response text: {response_text[:500]}")
                if api_code:
                    logger.debug(f"API Error Code: {api_code}")
                if api_message:
                    logger.debug(f"API Error Message: {api_message}")

                # For 500 errors, retry
                if response.status == 500:
                    retry_count += 1
                    wait_time = retry_delay * (2 ** retry_count)  # Exponential backoff
                    logger.warning(f"Received 500 error, retrying in {wait_time}s (attempt {retry_count}/{max_retries})")
                    await asyncio.sleep(wait_time)
                    last_error = f"HTTP 500: {response_text[:100]}..."
                    continue

                # Try to parse response as JSON
                try:
                    if response_text.strip():
                        response_data = json.loads(response_text)
                        
                        # Add API error headers to the response data if they exist
                        if api_code:
                            response_data['api_code'] = api_code
                        if api_message:
                            response_data['api_message'] = api_message

                        # Check if the response contains an error message
                        if isinstance(response_data, dict) and 'code' in response_data and response_data['code'] != 0:
                            error_msg = response_data.get('msg', 'Unknown error')
                            logger.error(f"Pionex API error response: {error_msg}")
                            
                            # Include both the API error headers and the response error
                            return {
                                'success': False, 
                                'error': error_msg,
                                'api_code': api_code,
                                'api_message': api_message,
                                'response_code': response_data.get('code', 0),
                                'response_msg': error_msg
                            }

                        return response_data
                    else:
                        # Even for empty responses, include API error headers if they exist
                        return {
                            'success': False, 
                            'error': 'Empty response from server',
                            'api_code': api_code,
                            'api_message': api_message
                        }
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse JSON response: {str(e)}")
                    return {
                        'success': False, 
                        'error': f'Invalid JSON response: {response_text[:100]}...',
                        'api_code': api_code,
                        'api_message': api_message
                    }

            except aiohttp.ClientError as e:
                retry_count += 1
                wait_time = retry_delay * (2 ** retry_count)
                logger.warning(f"HTTP error: {str(e)}, retrying in {wait_time}s (attempt {retry_count}/{max_retries})")
                await asyncio.sleep(wait_time)
                last_error = f"HTTP error: {str(e)}"
                continue
            except Exception as e:
                logger.error(f"Error making request to Pionex API: {str(e)}")
                return {'success': False, 'error': str(e)}

        # If we've exhausted all retries
        return {'success': False, 'error': f"Max retries exceeded. Last error: {last_error}"}

    async def get_wallet_balance(self) -> Dict[str, Any]:
        """
        Retrieve wallet balances from Pionex.
        Using the correct endpoint from your working code.

        Returns:
        Dict[str, Decimal]: Dictionary mapping asset symbols to their balances
        """
        try:
            # Using the endpoint from your working code: /api/v1/account/balances
            response = await self._make_request('GET', '/api/v1/account/balances', auth_required=True)

            # Check if we got a valid response
            if not response or not isinstance(response, dict):
                logger.error(f"Invalid response format from Pionex API: {response}")
                return {'error': 'Invalid response format from Pionex API'}

            # Check for error first
            if 'success' in response and response['success'] is False:
                logger.error(f"Error in wallet balance response: {response.get('error', 'Unknown error')}")
                return response

            # Extract balances from the response according to Pionex API structure
            balances = {}
            # If data contains balances array, process it
            if 'data' in response and 'balances' in response['data']:
                for asset in response['data']['balances']:
                    symbol = asset.get('coin', '')
                    free = Decimal(str(asset.get('free', '0')))
                    locked = Decimal(str(asset.get('locked', '0')))
                    total = free + locked

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
        Using the correct endpoint from your working code.

        Args:
            pair (str): Trading pair symbol (e.g., 'BTC_USDT')

        Returns:
            Dict containing 'bids' and 'asks' lists, where each entry is [price, quantity]
        """
        formatted_pair = self.format_pair(pair)
        # Using the endpoint from your working code: /api/v1/market/depth
        response = await self._make_request('GET', f"/api/v1/market/depth?symbol={formatted_pair}")
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
            # Extract bids and asks according to the structure in your working code
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
        Using correct endpoint from your working code.

        Args:
            pair (str): Trading pair symbol

        Returns:
            Dict containing ticker data (high, low, volume, etc.)
        """
        formatted_pair = self.format_pair(pair)
        # Using the endpoint from your working code: /api/v1/market/tickers
        response = await self._make_request('GET', f"/api/v1/market/tickers", params={"symbol": formatted_pair})

        # Check for error response
        if 'success' in response and response['success'] is False:
            return response

        # Process response according to Pionex API structure
        try:
            if 'data' in response and 'tickers' in response['data'] and len(response['data']['tickers']) > 0:
                ticker = response['data']['tickers'][0]
                return {
                    'symbol': ticker.get('symbol', formatted_pair),
                    'open': str(Decimal(str(ticker.get('open', '0')))),
                    'high': str(Decimal(str(ticker.get('high', '0')))),
                    'low': str(Decimal(str(ticker.get('low', '0')))),
                    'close': str(Decimal(str(ticker.get('close', '0')))),
                    'volume': str(Decimal(str(ticker.get('volume', '0')))),
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
            symbol (str): The trading pair symbol (e.g., 'BTCUSDT')
            
        Returns:
            Dict: The ticker information including current price
        """
        try:
            # Endpoint for getting ticker price
            formatted_pair = self.format_pair(symbol)
            response = await self._make_request('GET', f'/api/v1/market/klines?symbol={formatted_pair}&interval=1M&limit=1', auth_required=False)
            # Check if we got a valid response
            if not response or not isinstance(response, dict):
                logger.error(f"Invalid response format from Pionex API for ticker price: {response}")
                return {'error': 'Invalid response format from Pionex API'}
                
            # Check for error first
            if 'success' in response and response['success'] is False:
                logger.error(f"Error in ticker price response: {response.get('error', 'Unknown error')}")
                return response
                
            # Extract the price from the response
            if 'data' in response and 'klines' in response['data']:
                return {
                    'symbol': symbol,
                    'price': response['data']['klines'][0]['close']
                }
            else:
                logger.error(f"Unexpected response format for ticker price: {response}")
                return {'error': 'Unexpected response format', 'data': response}
                
        except Exception as e:
            logger.error(f"Error getting ticker price for {symbol}: {str(e)}")
            return {'error': f"Exception: {str(e)}"}
    # Modify the place_order method in the PionexClient class to extract and return API error headers
    async def place_order(self, order_type: str, pair: str, volume: Decimal, price: Decimal) -> Dict[str, Any]:
        """
        Place an order on Pionex.
        Using correct endpoint and parameters based on Pionex API docs.

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
        logger.info(f"Preparing to place {order_type.upper()} order for {formatted_pair}")
        
        # According to Pionex API docs format
        body = {
            "symbol": formatted_pair,
            "side": order_type.upper(),   # 'BUY' or 'SELL'
            "type": "LIMIT",              # Using 'LIMIT' order type
            "timeInForce": "GTC",         # Good Till Cancel - required parameter
            "price": price_str,           # Limit price
            "size": volume_str            # Quantity in base asset
        }
        
        logger.info(f"Placing {order_type.upper()} order: {volume_str} {pair} at {price_str}")
        logger.debug(f"Order request body: {body}")

        try:
            # Use the path exactly as in the API docs
            response = await self._make_request('POST', "/api/v1/trade/order", body=body, auth_required=True)
            
            # Check if the response is a success
            if 'result' in response and response['result'] is True:
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
                    logger.warning(f"Order placed but response format unexpected: {response}")
                    return {
                        'success': True,
                        'order_id': str(int(time.time())),  # Generate a temporary ID
                        'symbol': formatted_pair,
                        'type': order_type.upper(),
                        'price': price_str,
                        'size': volume_str,
                        'status': 'NEW',
                        'note': 'Response format did not contain expected orderId'
                    }
            else:
                # Extract API error information from the response
                api_code = response.get('api_code', 'UNKNOWN_ERROR')
                api_message = response.get('api_message', 'Unknown error')
                
                logger.error(f"Order placement failed: {api_code} - {api_message}")
                return {
                    'success': False, 
                    'error': f"{api_code}: {api_message}",
                    'api_code': api_code,
                    'api_message': api_message
                }
                
        except Exception as e:
            logger.error(f"Exception placing order: {str(e)}")
            return {'success': False, 'error': f"Exception: {str(e)}"}
   
    async def get_pairs(self) -> List[Dict[str, Any]]:
        """
        Get all available trading pairs from Pionex.
        Using the correct endpoint from the API docs.

        Returns:
            List of dictionaries containing pair information
        """
        # Using the exchangeInfo endpoint from the API docs
        response = await self._make_request('GET', '/api/v1/market/exchangeInfo')

        # Check for error response
        if 'success' in response and response['success'] is False:
            return [response]

        pairs = []
        if 'data' in response and 'symbols' in response['data']:
            for symbol_info in response['data']['symbols']:
                try:
                    base_asset = symbol_info.get('baseAsset', '')
                    quote_asset = symbol_info.get('quoteAsset', '')
                    symbol = symbol_info.get('symbol', '')

                    # Extract precision information if available
                    price_precision = symbol_info.get('pricePrecision', 8)
                    quantity_precision = symbol_info.get('quantityPrecision', 8)

                    # Extract min/max quantity if available
                    min_quantity = "0"
                    max_quantity = None

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
        Using the correct endpoint from your working code.

        Args:
            order_id (str): Order ID to check
            pair (str): Trading pair for the order

        Returns:
            Dict containing order status information
        """
        formatted_pair = self.format_pair(pair)
        params = {
            "symbol": formatted_pair,
            "orderId": order_id
        }

        # Using the endpoint from the API docs
        response = await self._make_request('GET', f'/api/v1/trade/order?orderId={order_id}', auth_required=True)

        # Check for error response
        if 'success' in response and response['success'] is False:
            return response

        # Process successful order status request
        try:
            if 'data' in response:
                data = response['data']

                # Map Pionex order status to our standard format
                status_mapping = {
                    'NEW': 'open',
                    'PARTIALLY_FILLED': 'partially_filled',
                    'FILLED': 'filled',
                    'CANCELED': 'canceled',
                    'REJECTED': 'rejected',
                    'EXPIRED': 'canceled'
                }

                pionex_status = data.get('status', 'UNKNOWN')
                mapped_status = status_mapping.get(pionex_status, 'unknown')

                return {
                    'order_id': data.get('orderId', ''),
                    'symbol': data.get('symbol', formatted_pair),
                    'price': str(Decimal(str(data.get('price', '0')))),
                    'quantity': str(Decimal(str(data.get('origQty', '0')))),
                    'executed_qty': str(Decimal(str(data.get('executedQty', '0')))),
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
        Using the correct endpoint from your working code.

        Args:
            pair (str, optional): Trading pair symbol. If None, get all open orders.

        Returns:
            List of dictionaries containing order information
        """
        params = {}
        if pair:
            formatted_pair = self.format_pair(pair)
            params['symbol'] = formatted_pair

        # Using the endpoint from your working code: /api/v1/trade/openOrders
        response = await self._make_request('GET', '/api/v1/trade/openOrders', params=params, auth_required=True)

        # Check for error response
        if 'success' in response and response['success'] is False:
            return [response]

        orders = []

        # Extract orders from the response according to the structure in your code
        if 'data' in response and 'orders' in response['data']:
            order_list = response['data']['orders']

            # Map status codes to our format
            status_mapping = {
                'NEW': 'open',
                'PARTIALLY_FILLED': 'partially_filled',
                'FILLED': 'filled',
                'CANCELED': 'canceled',
                'REJECTED': 'rejected',
                'EXPIRED': 'canceled'
            }

            for order in order_list:
                try:
                    pionex_status = order.get('status', 'UNKNOWN')
                    mapped_status = status_mapping.get(pionex_status, 'unknown')

                    orders.append({
                        'order_id': order.get('orderId', ''),
                        'symbol': order.get('symbol', ''),
                        'price': str(Decimal(str(order.get('price', '0')))),
                        'quantity': str(Decimal(str(order.get('origQty', '0')))),
                        'executed_qty': str(Decimal(str(order.get('executedQty', '0')))),
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
        Cancel an order on Pionex.
        Using the correct endpoint from your working code.

        Args:
            order_id (str): Order ID to cancel
            pair (str): Trading pair for the order

        Returns:
            Dict containing cancel order response or success/failure
        """
        formatted_pair = self.format_pair(pair)

        # Using the endpoint and parameter format from your working code
        params = {
            'symbol': formatted_pair,
            'orderId': order_id
        }

        response = await self._make_request('DELETE', '/api/v1/trade/order', params=params, auth_required=True)

        # Check for error response
        if 'success' in response and response['success'] is False:
            return response

        # Process successful cancel request
        if 'data' in response:
            return {
                'success': True,
                'order_id': order_id,
                'symbol': formatted_pair,
                'message': 'Order cancelled successfully'
            }
        else:
            return {'success': False, 'error': 'Unexpected response format', 'data': response}

    async def cancel_all_orders(self, pair: str) -> Dict[str, Any]:
        """
        Cancel all orders for a specific symbol.
        Using the correct endpoint from your working code.

        Args:
            pair (str): Trading pair symbol

        Returns:
            Dict containing success status and count of canceled orders
        """
        formatted_pair = self.format_pair(pair)

        # Using the endpoint from your working code
        params = {'symbol': formatted_pair}
        response = await self._make_request('DELETE', '/api/v1/trade/allOrders', params=params, auth_required=True)

        # Check for error response
        if 'success' in response and response['success'] is False:
            return response

        # Process successful cancel all request
        if 'data' in response:
            return {
                'success': True,
                'symbol': formatted_pair,
                'message': 'All orders cancelled successfully',
                'data': response['data']
            }
        else:
            return {'success': False, 'error': 'Unexpected response format', 'data': response}

    def format_pair(self, pair: str) -> str:
        """
        Format a trading pair symbol for Pionex API.

        Args:
            pair (str): Trading pair in format like BTC_USDT or BTC/USDT or BTCUSDT

        Returns:
            str: Formatted pair symbol for Pionex API
        """
        if not pair:
            logger.error("Empty trading pair provided")
            return ""
            
        # Handle various formats (BTC_USDT, BTC/USDT, BTCUSDT)
        if '_' in pair:
            return pair  # Pionex now uses underscores in the API
        elif '/' in pair:
            return pair.replace('/', '_')  # Convert BTC/USDT to BTC_USDT
        else:
            # Try to detect if this is a combined pair (like BTCUSDT)
            # This is just a fallback and should ideally be handled by the bot configuration
            common_quote_assets = ['USDT', 'BTC', 'ETH', 'BNB', 'BUSD' ,'WOLF']
            for quote in common_quote_assets:
                if pair.endswith(quote) and len(pair) > len(quote):
                    base = pair[:-len(quote)]
                    return f"{base}_{quote}"
                    
            # If we can't detect a pattern, return as-is
            return pair
