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

logger = logging.getLogger('bitmart')

class BitMartClient(BaseExchangeClient):
    """
    Client for interacting with the BitMart exchange API.
    Documentation: https://developer-pro.bitmart.com/en/spot/
    """

    BASE_URL = "https://api-cloud.bitmart.com"

    def __init__(self, api_key: str, secret_key: str, memo: str = None):
        """
        Initialize the BitMart client.
        
        Args:
            api_key (str): API key (Access Key)
            secret_key (str): API secret key (Secret Key)
            memo (str): API private key (Memo) - Required for authenticated requests
        """
        super().__init__(api_key, secret_key)
        self.memo = memo  # BitMart requires a memo (private key) for authentication
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
        logger.debug("BitMart client initialized")

    async def cleanup(self):
        """Close the HTTP session."""
        if self.session:
            await self.session.close()
            self.session = None
        logger.debug("BitMart client cleaned up")

    def _generate_signature(self, timestamp: str, query_string: str = "") -> str:
        """
        Generate the signature required for authenticated requests.
        According to BitMart API docs: The signature is created by using HMAC SHA256.

        Args:
            timestamp (str): Timestamp in milliseconds
            query_string (str): Query string for GET requests or request body for POST requests

        Returns:
            str: HMAC SHA256 signature
        """
        # Check if memo (private key) is available
        if not self.memo:
            logger.error("BitMart authentication error: Memo (Private Key) is required but not provided")
            raise ValueError("BitMart authentication requires a memo (Private Key). Please provide it when initializing the client.")
            
        # Create signature string: timestamp + #API key + query_string
        signature_string = f"{timestamp}#{self.memo}#{query_string}"
        
        # Create signature using HMAC-SHA256 with secret_key as the key (not memo)
        # The BitMart API documentation indicates that the secret key should be used for signing
        signature = hmac.new(
            self.secret_key.encode(),  # Use secret_key instead of memo for HMAC
            signature_string.encode(),
            hashlib.sha256
        ).hexdigest()
        
        logger.debug(f"Signature base: {signature_string}")
        logger.debug(f"Signature: {signature}")
        
        return signature

    async def _make_request(self, method: str, path: str, params: Dict[str, Any] = None, 
                       body: Dict[str, Any] = None, auth_required: bool = False,
                       max_retries: int = 3, retry_delay: float = 1.0) -> Dict[str, Any]:
        """
        Make an HTTP request to the BitMart API with retry logic.

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
        headers = {'Content-Type': 'application/json', 'X-BM-TIMESTAMP': '', 'X-BM-KEY': '', 'X-BM-SIGN': ''}

        if params is None:
            params = {}

        # Add authentication for authenticated requests
        if auth_required:
            # Check if memo is available for authenticated requests
            if not self.memo:
                logger.error("BitMart authentication error: Memo (Private Key) is required but not provided")
                return {
                    'success': False,
                    'error': 'BitMart authentication requires a memo (Private Key). Please provide it when initializing the client.'
                }
                
            # Add API key to headers
            headers['X-BM-KEY'] = self.api_key
            
            # Add timestamp
            timestamp = str(int(time.time() * 1000))
            headers['X-BM-TIMESTAMP'] = timestamp
            
            # Create query string for signature
            query_string = ""
            if method == 'GET' and params:
                # For GET requests, sort parameters alphabetically
                sorted_params = dict(sorted(params.items()))
                query_string = urlencode(sorted_params)
            elif method == 'POST' and body:
                
                # For POST requests, use the JSON body
                query_string = json.dumps(body)
            
            # Generate signature
            try:
                signature = self._generate_signature(timestamp, query_string)
                # Add signature to headers
                headers['X-BM-SIGN'] = signature
            except Exception as e:
                logger.error(f"Error generating signature: {str(e)}")
                return {'success': False, 'error': f"Authentication error: {str(e)}"}

        retry_count = 0
        last_error = None

        while retry_count < max_retries:
            try:
                # Log request details for debugging
                logger.debug(f"Making {method} request to {url}")
                logger.debug(f"Headers: {headers}")
                logger.debug(f"Params: {params}")
                logger.debug(f"Body: {body}")

                if method == 'GET':
                    response = await self.session.get(url, headers=headers, params=params)
                elif method == 'POST':
                    if body:
                        response = await self.session.post(url, headers=headers, json=body)
                        # print(response,"make request print")
                    else:
                        response = await self.session.post(url, headers=headers)
                elif method == 'DELETE':
                    response = await self.session.delete(url, headers=headers, params=params)
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
                        if isinstance(response_data, dict) and response_data.get('code') != 1000:
                            error_msg = response_data.get('message', 'Unknown error')
                            logger.error(f"BitMart API error response: {error_msg}")
                            
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
                logger.error(f"Error making request to BitMart API: {str(e)}")
                return {'success': False, 'error': str(e)}

        # If we've exhausted all retries
        return {'success': False, 'error': f"Max retries exceeded. Last error: {last_error}"}

    async def get_wallet_balance(self) -> Dict[str, Any]:
        """
        Retrieve wallet balances from BitMart.

        Returns:
            Dict[str, Decimal]: Dictionary mapping asset symbols to their balances
        """
        try:
            # Using the endpoint from BitMart API docs: /spot/v1/wallet
            response = await self._make_request('GET', '/spot/v1/wallet', auth_required=True)
            # Check if we got a valid response
            if not response or not isinstance(response, dict):
                logger.error(f"Invalid response format from BitMart API: {response}")
                return {'error': 'Invalid response format from BitMart API'}

            # Check for error first
            if 'success' in response and response['success'] is False:
                logger.error(f"Error in wallet balance response: {response.get('error', 'Unknown error')}")
                return response

            # Extract balances from the response according to BitMart API structure
            balances = {}
            # If data contains balances array, process it
            if 'data' in response and 'wallet' in response['data']:
                for asset in response['data']['wallet']:
                    symbol = asset.get('id', '')
                    free = Decimal(str(asset.get('available', '0')))
                    locked = Decimal(str(asset.get('frozen', '0')))
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
        # Using the endpoint from BitMart API docs: /spot/v1/symbols/book
        response = await self._make_request('GET', f"/spot/v1/symbols/book", params={"symbol": formatted_pair, "size": 100})
        # Check for error response
        # if 'success' in response and response['success'] is False:
        #     return response

        result = {
            'bids': [],
            'asks': []
        }

        # Extract bids and asks according to BitMart API structure
        if 'data' in response and 'buys' in response['data'] and 'sells' in response['data']:
            # Convert string values to Decimal
            for bid in response['data'].get('buys', []):
                if 'price' in bid and 'amount' in bid:
                    result['bids'].append([Decimal(str(bid['price'])), Decimal(str(bid['amount']))])

            for ask in response['data'].get('sells', []):
                if 'price' in ask and 'amount' in ask:
                    result['asks'].append([Decimal(str(ask['price'])), Decimal(str(ask['amount']))])

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
        # Using the endpoint from BitMart API docs: /spot/quotation/v3/ticker
        response = await self._make_request('GET', f"/spot/quotation/v3/ticker", params={"symbol": formatted_pair})
        
        # Check for error response
        if 'success' in response and response['success'] is False:
            return response

        # Process response according to BitMart API structure
        try:
            if 'data' in response:
                ticker = response['data']
                return {
                    'symbol': ticker.get('symbol', formatted_pair),
                    'open': str(Decimal(str(ticker.get('open_24h', '0')))),
                    'high': str(Decimal(str(ticker.get('high_24h', '0')))),
                    'low': str(Decimal(str(ticker.get('low_24h', '0')))),
                    'close': str(Decimal(str(ticker.get('last', '0')))),
                    'volume': str(Decimal(str(ticker.get('v_24h', '0')))),
                    'time': int(time.time() * 1000)  # BitMart doesn't provide timestamp in this endpoint
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
            # Endpoint for getting ticker price
            formatted_pair = self.format_pair(symbol)
            response = await self._make_request('GET', '/spot/quotation/v3/ticker', params={"symbol": formatted_pair}, auth_required=False)
            
            # Check if we got a valid response
            if not response or not isinstance(response, dict):
                logger.error(f"Invalid response format from BitMart API for ticker price: {response}")
                return {'error': 'Invalid response format from BitMart API'}
                
            # Check for error first
            if 'success' in response and response['success'] is False:
                logger.error(f"Error in ticker price response: {response.get('error', 'Unknown error')}")
                return response
                
            # Extract the price from the response
            if 'data' in response:
                ticker = response['data']
                return {
                    'symbol': symbol,
                    'price': ticker.get('last', '0')
                }
            else:
                logger.error(f"Unexpected response format for ticker price: {response}")
                return {'error': 'Unexpected response format', 'data': response}
                
        except Exception as e:
            logger.error(f"Error getting ticker price for {symbol}: {str(e)}")
            return {'error': f"Exception: {str(e)}"}

    async def place_order(self, order_type: str, pair: str, volume: Decimal, price: Decimal) -> Dict[str, Any]:
        """
        Place an order on BitMart.

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
        
        # According to BitMart API docs format
        body = {
            "symbol": formatted_pair,
            "side": order_type.lower(),   # 'buy' or 'sell'
            "type": "limit",              # Using 'limit' order type
            "size": volume_str,           # Quantity in base asset
            "price": price_str            # Limit price
        }   
        logger.info(f"Placing {order_type.upper()} order: {volume_str} {pair} at {price_str}")
        logger.debug(f"Order request body: {body}")

        try:
            # Use the path exactly as in the API docs
            response = await self._make_request('POST', "/spot/v2/submit_order", body=body, auth_required=True)
            # Check if the response is a success
            if 'code' in response and response['code'] == 1000:
                if 'data' in response and 'order_id' in response['data']:
                    order_id = str(response['data']['order_id'])
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
                        'note': 'Response format did not contain expected order_id'
                    }
            else:
                # Extract error information from the response
                error_code = response.get('code', 'UNKNOWN_ERROR')
                error_msg = response.get('message', 'Unknown error')
                
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
        Get all available trading pairs from BitMart.

        Returns:
            List of dictionaries containing pair information
        """
        # Using the symbols endpoint from the API docs
        response = await self._make_request('GET', '/spot/v1/symbols')

        # Check for error response
        if 'success' in response and response['success'] is False:
            return [response]

        pairs = []
        if 'data' in response and 'symbols' in response['data']:
            for symbol_info in response['data']['symbols']:
                try:
                    symbol = symbol_info.get('symbol', '')
                    
                    # Extract base and quote assets from symbol (e.g., BTC_USDT)
                    if '_' in symbol:
                        base_asset, quote_asset = symbol.split('_')
                    else:
                        # If symbol format is different, try to extract from other fields
                        base_asset = symbol_info.get('base_currency', '')
                        quote_asset = symbol_info.get('quote_currency', '')
                        
                        # If still not available, use a fallback approach
                        if not base_asset or not quote_asset:
                            continue

                    # Extract precision information if available
                    price_precision = int(symbol_info.get('price_precision', 8))
                    quantity_precision = int(symbol_info.get('amount_precision', 8))

                    # Extract min/max quantity if available
                    min_quantity = symbol_info.get('min_buy_amount', "0")
                    max_quantity = symbol_info.get('max_buy_amount', None)

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
        formatted_pair = self.format_pair(pair)

        # Using the endpoint from the API docs
        params = {
            "symbol": formatted_pair,
            "order_id": order_id
        }
        response = await self._make_request('GET', '/spot/v2/order_detail', params=params, auth_required=True)

        # Check for error response
        if 'success' in response and response['success'] is False:
            return response

        # Process successful order status request
        try:
            if 'data' in response and 'order_detail' in response['data']:
                order_detail = response['data']['order_detail']

                # Map BitMart order status to our standard format
                status_mapping = {
                    1: 'open',             # pending
                    2: 'open',             # partially_filled
                    3: 'filled',           # filled
                    4: 'canceled',         # canceled
                    5: 'rejected',         # partially_canceled
                    6: 'canceled'          # sys_canceled
                }

                bitmart_status = order_detail.get('status', 0)
                mapped_status = status_mapping.get(bitmart_status, 'unknown')

                return {
                    'order_id': order_detail.get('order_id', ''),
                    'symbol': order_detail.get('symbol', formatted_pair),
                    'price': str(Decimal(str(order_detail.get('price', '0')))),
                    'quantity': str(Decimal(str(order_detail.get('size', '0')))),
                    'executed_qty': str(Decimal(str(order_detail.get('filled_size', '0')))),
                    'status': mapped_status,
                    'side': order_detail.get('side', '').lower(),
                    'type': order_detail.get('type', ''),
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

        # Using the endpoint from the API docs
        response = await self._make_request('GET', '/spot/v2/orders', params=params, auth_required=True)

        # Check for error response
        if 'success' in response and response['success'] is False:
            return [response]

        orders = []

        # Extract orders from the response
        if 'data' in response and 'orders' in response['data']:
            order_list = response['data']['orders']

            # Map status codes to our format
            status_mapping = {
                1: 'open',             # pending
                2: 'partially_filled',  # partially_filled
                3: 'filled',           # filled
                4: 'canceled',         # canceled
                5: 'partially_filled',  # partially_canceled
                6: 'canceled'          # sys_canceled
            }

            for order in order_list:
                try:
                    bitmart_status = order.get('status', 0)
                    mapped_status = status_mapping.get(bitmart_status, 'unknown')

                    orders.append({
                        'order_id': order.get('order_id', ''),
                        'symbol': order.get('symbol', ''),
                        'price': str(Decimal(str(order.get('price', '0')))),
                        'quantity': str(Decimal(str(order.get('size', '0')))),
                        'executed_qty': str(Decimal(str(order.get('filled_size', '0')))),
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
        Cancel an order on BitMart.

        Args:
            order_id (str): Order ID to cancel
            pair (str): Trading pair for the order

        Returns:
            Dict containing cancel order response or success/failure
        """
        formatted_pair = self.format_pair(pair)

        # Using the endpoint and parameter format from the API docs
        body = {
            'symbol': formatted_pair,
            'order_id': order_id
        }

        response = await self._make_request('POST', '/spot/v2/cancel_order', body=body, auth_required=True)

        # Check for error response
        if 'success' in response and response['success'] is False:
            return response

        # Process successful cancel request
        if 'code' in response and response['code'] == 1000:
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

        Args:
            pair (str): Trading pair symbol

        Returns:
            Dict containing success status and count of canceled orders
        """
        formatted_pair = self.format_pair(pair)

        # Using the endpoint from the API docs
        body = {'symbol': formatted_pair}
        response = await self._make_request('POST', '/spot/v1/cancel_orders', body=body, auth_required=True)

        # Check for error response
        if 'success' in response and response['success'] is False:
            return response

        # Process successful cancel all request
        if 'code' in response and response['code'] == 1000:
            return {
                'success': True,
                'symbol': formatted_pair,
                'message': 'All orders cancelled successfully',
                'data': response.get('data', {})
            }
        else:
            return {'success': False, 'error': 'Unexpected response format', 'data': response}

    def format_pair(self, pair: str) -> str:
        """
        Format a trading pair symbol for BitMart API.

        Args:
            pair (str): Trading pair in format like BTC_USDT or BTC/USDT or BTCUSDT

        Returns:
            str: Formatted pair symbol for BitMart API
        """
        if not pair:
            logger.error("Empty trading pair provided")
            return ""
            
        # Handle various formats (BTC_USDT, BTC/USDT, BTCUSDT)
        if '_' in pair:
            return pair  # BitMart uses underscores in the API
        elif '/' in pair:
            return pair.replace('/', '_')  # Convert BTC/USDT to BTC_USDT
        else:
            # Try to detect if this is a combined pair (like BTCUSDT)
            # This is just a fallback and should ideally be handled by the bot configuration
            common_quote_assets = ['USDT', 'BTC', 'ETH', 'USDC', 'BUSD']
            for quote in common_quote_assets:
                if pair.endswith(quote) and len(pair) > len(quote):
                    base = pair[:-len(quote)]
                    return f"{base}_{quote}"
                    
            # If we can't detect a pattern, return as-is
            return pair
