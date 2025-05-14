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

logger = logging.getLogger('mexc')

class MexcClient(BaseExchangeClient):
    """
    Client for interacting with the MEXC exchange API.
    Documentation: https://mexcdevelop.github.io/apidocs/spot_v3_en/
    """

    BASE_URL = "https://api.mexc.com"

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
        logger.debug("MEXC client initialized")

    async def cleanup(self):
        """Close the HTTP session."""
        if self.session:
            await self.session.close()
            self.session = None
        logger.debug("MEXC client cleaned up")

    def _generate_signature(self, query_string: str) -> str:
        """
        Generate the signature required for authenticated requests.
        According to MEXC API docs, the signature is created by:
        1. Create a query string from parameters
        2. Sign this query string using HMAC-SHA256 with the secret key

        Args:
            query_string (str): Query string to sign

        Returns:
            str: HMAC SHA256 signature
        """
        # Create signature using HMAC-SHA256
        signature = hmac.new(
            self.secret_key.encode(),
            query_string.encode(),
            hashlib.sha256
        ).hexdigest()
        
        logger.debug(f"Signature base: {query_string}")
        logger.debug(f"Signature: {signature}")
        
        return signature

    async def _make_request(self, method: str, path: str, params: Dict[str, Any] = None, 
                       body: Dict[str, Any] = None, auth_required: bool = False,
                       max_retries: int = 3, retry_delay: float = 1.0) -> Dict[str, Any]:
        """
        Make an HTTP request to the MEXC API with retry logic.

        Args:
            method (str): HTTP method (GET, POST, DELETE)
            path (str): API endpoint path
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

        url = f"{self.BASE_URL}{path}"
        headers = {'Content-Type': 'application/json'}

        if params is None:
            params = {}

        # Add authentication for authenticated requests
        if auth_required:
            # Add API key to headers
            headers['X-MEXC-APIKEY'] = self.api_key
            
            # Add timestamp and recvWindow
            params['timestamp'] = str(int(time.time() * 1000))
            params['recvWindow'] = '5000'  # 5 seconds
            
            # Create query string before signature generation
            query_string = urlencode(params, safe="=")
            
            # Generate signature
            signature = self._generate_signature(query_string)
            
            # Add signature to query string
            query_string = f"{query_string}&signature={signature}"
            
            # Clear params since we're using the prepared query string
            request_params = None
        else:
            # For non-auth requests, use params directly
            request_params = params
            query_string = None

        retry_count = 0
        last_error = None

        while retry_count < max_retries:
            try:
                # Log request details for debugging
                logger.debug(f"Making {method} request to {url}")
                logger.debug(f"Headers: {headers}")
                logger.debug(f"Params: {params}")
                logger.debug(f"Query string: {query_string}")
                logger.debug(f"Body: {body}")

                # For auth requests, append the query string to URL
                request_url = url
                if auth_required:
                    request_url = f"{url}?{query_string}"

                if method == 'GET':
                    response = await self.session.get(request_url, headers=headers, params=request_params)
                elif method == 'POST':
                    if body:
                        response = await self.session.post(request_url, headers=headers, params=request_params, json=body)
                        print(response,"place order")
                    else:
                        response = await self.session.post(request_url, headers=headers, params=request_params)
                elif method == 'DELETE':
                    response = await self.session.delete(request_url, headers=headers, params=request_params)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")
                    
                # Get response as text
                response_text = await response.text()
                
                # Log the raw response for debugging
                logger.debug(f"Response status: {response.status}")
                logger.debug(f"Response text: {response_text[:500]}")

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
                        
                        # Check if the response contains an error message
                        if isinstance(response_data, dict) and 'code' in response_data and response_data['code'] != 200 and response_data['code'] != 0:
                            error_msg = response_data.get('msg', 'Unknown error')
                            logger.error(f"MEXC API error response: {error_msg}")
                            
                            return {
                                'success': False, 
                                'error': error_msg,
                                'code': response_data.get('code', 0)
                            }

                        return response_data
                    else:
                        return {
                            'success': False, 
                            'error': 'Empty response from server'
                        }
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse JSON response: {str(e)}")
                    return {
                        'success': False, 
                        'error': f'Invalid JSON response: {response_text[:100]}...'
                    }

            except aiohttp.ClientError as e:
                retry_count += 1
                wait_time = retry_delay * (2 ** retry_count)
                logger.warning(f"HTTP error: {str(e)}, retrying in {wait_time}s (attempt {retry_count}/{max_retries})")
                await asyncio.sleep(wait_time)
                last_error = f"HTTP error: {str(e)}"
                continue
            except Exception as e:
                logger.error(f"Error making request to MEXC API: {str(e)}")
                return {'success': False, 'error': str(e)}

        # If we've exhausted all retries
        return {'success': False, 'error': f"Max retries exceeded. Last error: {last_error}"}

    async def get_wallet_balance(self) -> Dict[str, Any]:
        """
        Retrieve wallet balances from MEXC.

        Returns:
            Dict[str, Decimal]: Dictionary mapping asset symbols to their balances
        """
        try:
            # Using the endpoint from MEXC API docs: /api/v3/account
            response = await self._make_request('GET', '/api/v3/account', auth_required=True)
            
            # Check if we got a valid response
            if not response or not isinstance(response, dict):
                logger.error(f"Invalid response format from MEXC API: {response}")
                return {'error': 'Invalid response format from MEXC API'}

            # Check for error first
            if 'success' in response and response['success'] is False:
                logger.error(f"Error in wallet balance response: {response.get('error', 'Unknown error')}")
                return response

            # Extract balances from the response according to MEXC API structure
            balances = {}
            # If balances array exists, process it
            if 'balances' in response:
                for asset in response['balances']:
                    symbol = asset.get('asset', '')
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

        Args:
            pair (str): Trading pair symbol (e.g., 'BTC_USDT')

        Returns:
            Dict containing 'bids' and 'asks' lists, where each entry is [price, quantity]
        """
        formatted_pair = self.format_pair(pair)
        # Using the endpoint from MEXC API docs: /api/v3/depth
        response = await self._make_request('GET', f"/api/v3/depth", params={"symbol": formatted_pair, "limit": 100})
        
        # Check for error response
        if 'success' in response and response['success'] is False:
            return response

        result = {
            'bids': [],
            'asks': []
        }

        # Extract bids and asks according to MEXC API structure
        if 'bids' in response and 'asks' in response:
            # Convert string values to Decimal
            for bid in response.get('bids', []):
                if len(bid) >= 2:
                    result['bids'].append([Decimal(str(bid[0])), Decimal(str(bid[1]))])

            for ask in response.get('asks', []):
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
        # Using the endpoint from MEXC API docs: /api/v3/ticker/24hr
        response = await self._make_request('GET', f"/api/v3/ticker/24hr", params={"symbol": formatted_pair})

        # Check for error response
        if 'success' in response and response['success'] is False:
            return response

        # Process response according to MEXC API structure
        try:
            # MEXC returns an array for all symbols or a single object for a specific symbol
            ticker_data = response
            if isinstance(response, list) and len(response) > 0:
                # Find the matching symbol in the list
                for ticker in response:
                    if ticker.get('symbol') == formatted_pair:
                        ticker_data = ticker
                        break
                else:
                    return {'error': f'Symbol {formatted_pair} not found in ticker data', 'data': response}
            
            return {
                'symbol': ticker_data.get('symbol', formatted_pair),
                'open': str(Decimal(str(ticker_data.get('openPrice', '0')))),
                'high': str(Decimal(str(ticker_data.get('highPrice', '0')))),
                'low': str(Decimal(str(ticker_data.get('lowPrice', '0')))),
                'close': str(Decimal(str(ticker_data.get('lastPrice', '0')))),
                'volume': str(Decimal(str(ticker_data.get('volume', '0')))),
                'time': ticker_data.get('closeTime', 0)
            }
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
            response = await self._make_request('GET', '/api/v3/ticker/price', params={"symbol": formatted_pair}, auth_required=False)
            
            # Check if we got a valid response
            if not response or not isinstance(response, dict):
                logger.error(f"Invalid response format from MEXC API for ticker price: {response}")
                return {'error': 'Invalid response format from MEXC API'}
                
            # Check for error first
            if 'success' in response and response['success'] is False:
                logger.error(f"Error in ticker price response: {response.get('error', 'Unknown error')}")
                return response
                
            # Extract the price from the response
            if 'price' in response:
                return {
                    'symbol': symbol,
                    'price': response['price']
                }
            else:
                logger.error(f"Unexpected response format for ticker price: {response}")
                return {'error': 'Unexpected response format', 'data': response}
                
        except Exception as e:
            logger.error(f"Error getting ticker price for {symbol}: {str(e)}")
            return {'error': f"Exception: {str(e)}"}

    async def place_order(self, order_type: str, pair: str, volume: Decimal, price: Decimal) -> Dict[str, Any]:
        """
        Place an order on MEXC.

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
        
        # According to MEXC API docs format
        params = {
            "symbol": formatted_pair,
            "side": order_type.upper(),   # 'BUY' or 'SELL'
            "type": "LIMIT",              # Using 'LIMIT' order type
            "timeInForce": "GTC",         # Good Till Cancel
            "price": price_str,           # Limit price
            "quantity": volume_str        # Quantity in base asset
        }
        
        logger.info(f"Placing {order_type.upper()} order: {volume_str} {pair} at {price_str}")
        logger.debug(f"Order request params: {params}")

        try:
            # Use the path exactly as in the API docs
            response = await self._make_request('POST', "/api/v3/order", params=params, auth_required=True)
            
            # Check if the response is a success
            if 'orderId' in response:
                order_id = str(response.get('orderId', ''))
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
                # Extract error information from the response
                error_code = response.get('code', 'UNKNOWN_ERROR')
                error_msg = response.get('msg', 'Unknown error')
                
                logger.error(f"Order placement failed: {error_code} - {error_msg}")
                return {
                    'success': False, 
                    'error': f"{error_code}: {error_msg}",
                    'code': error_code
                }
                
        except Exception as e:
            logger.error(f"Exception placing order: {str(e)}")
            return {'success': False, 'error': f"Exception: {str(e)}"}
   
    async def get_pairs(self) -> List[Dict[str, Any]]:
        """
        Get all available trading pairs from MEXC.

        Returns:
            List of dictionaries containing pair information
        """
        # Using the exchangeInfo endpoint from the API docs
        response = await self._make_request('GET', '/api/v3/exchangeInfo')

        # Check for error response
        if 'success' in response and response['success'] is False:
            return [response]

        pairs = []
        if 'symbols' in response:
            for symbol_info in response['symbols']:
                try:
                    base_asset = symbol_info.get('baseAsset', '')
                    quote_asset = symbol_info.get('quoteAsset', '')
                    symbol = symbol_info.get('symbol', '')

                    # Extract precision information
                    price_precision = 8  # Default
                    quantity_precision = 8  # Default
                    
                    # Extract filters for min/max quantity and precision
                    min_quantity = "0"
                    max_quantity = None
                    
                    for filter_item in symbol_info.get('filters', []):
                        if filter_item.get('filterType') == 'PRICE_FILTER':
                            price_precision = self._calculate_precision(filter_item.get('tickSize', '0.00000001'))
                        elif filter_item.get('filterType') == 'LOT_SIZE':
                            quantity_precision = self._calculate_precision(filter_item.get('stepSize', '0.00000001'))
                            min_quantity = filter_item.get('minQty', '0')
                            max_quantity = filter_item.get('maxQty', None)

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

    def _calculate_precision(self, step_size: str) -> int:
        """
        Calculate decimal precision from step size.
        
        Args:
            step_size (str): Step size string (e.g., '0.00100000')
            
        Returns:
            int: Decimal precision
        """
        try:
            step = Decimal(step_size)
            if step == Decimal('0'):
                return 0
                
            step_str = str(step).rstrip('0').rstrip('.') if '.' in str(step) else str(step)
            if '.' in step_str:
                return len(step_str.split('.')[1])
            return 0
        except Exception as e:
            logger.error(f"Error calculating precision: {str(e)}")
            return 8  # Default to 8 decimal places

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
            "symbol": formatted_pair,
            "orderId": order_id
        }

        # Using the endpoint from the API docs
        response = await self._make_request('GET', '/api/v3/order', params=params, auth_required=True)

        # Check for error response
        if 'success' in response and response['success'] is False:
            return response

        # Process successful order status request
        try:
            # Map MEXC order status to our standard format
            status_mapping = {
                'NEW': 'open',
                'PARTIALLY_FILLED': 'partially_filled',
                'FILLED': 'filled',
                'CANCELED': 'canceled',
                'REJECTED': 'rejected',
                'EXPIRED': 'canceled'
            }

            mexc_status = response.get('status', 'UNKNOWN')
            mapped_status = status_mapping.get(mexc_status, 'unknown')

            return {
                'order_id': str(response.get('orderId', '')),
                'symbol': response.get('symbol', formatted_pair),
                'price': str(Decimal(str(response.get('price', '0')))),
                'quantity': str(Decimal(str(response.get('origQty', '0')))),
                'executed_qty': str(Decimal(str(response.get('executedQty', '0')))),
                'status': mapped_status,
                'side': response.get('side', '').lower(),
                'type': response.get('type', ''),
            }
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

        # Using the endpoint from MEXC API docs: /api/v3/openOrders
        response = await self._make_request('GET', '/api/v3/openOrders', params=params, auth_required=True)

        # Check for error response
        if 'success' in response and response['success'] is False:
            return [response]

        orders = []

        # Extract orders from the response
        if isinstance(response, list):
            order_list = response

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
                    mexc_status = order.get('status', 'UNKNOWN')
                    mapped_status = status_mapping.get(mexc_status, 'unknown')

                    orders.append({
                        'order_id': str(order.get('orderId', '')),
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
        Cancel an order on MEXC.

        Args:
            order_id (str): Order ID to cancel
            pair (str): Trading pair for the order

        Returns:
            Dict containing cancel order response or success/failure
        """
        formatted_pair = self.format_pair(pair)

        # Using the endpoint and parameter format from MEXC API docs
        params = {
            'symbol': formatted_pair,
            'orderId': order_id
        }

        response = await self._make_request('DELETE', '/api/v3/order', params=params, auth_required=True)

        # Check for error response
        if 'success' in response and response['success'] is False:
            return response

        # Process successful cancel request
        if 'orderId' in response:
            return {
                'success': True,
                'order_id': str(response.get('orderId', '')),
                'symbol': formatted_pair,
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

        # Using the endpoint from MEXC API docs
        params = {'symbol': formatted_pair}
        response = await self._make_request('DELETE', '/api/v3/openOrders', params=params, auth_required=True)

        # Check for error response
        if 'success' in response and response['success'] is False:
            return response

        # Process successful cancel all request
        if isinstance(response, list):
            return {
                'success': True,
                'symbol': formatted_pair,
                'message': 'All orders cancelled successfully',
                'canceled_orders': len(response)
            }
        else:
            return {'success': False, 'error': 'Unexpected response format', 'data': response}

    def format_pair(self, pair: str) -> str:
        """
        Format a trading pair symbol for MEXC API.

        Args:
            pair (str): Trading pair in format like BTC_USDT or BTC/USDT or BTCUSDT

        Returns:
            str: Formatted pair symbol for MEXC API
        """
        if not pair:
            logger.error("Empty trading pair provided")
            return ""
            
        # Handle various formats (BTC_USDT, BTC/USDT, BTCUSDT)
        if '_' in pair:
            # Convert BTC_USDT to BTCUSDT (MEXC format)
            return pair.replace('_', '')
        elif '/' in pair:
            # Convert BTC/USDT to BTCUSDT
            return pair.replace('/', '')
        else:
            # Already in MEXC format (BTCUSDT)
            return pair