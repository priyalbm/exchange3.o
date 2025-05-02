import logging
import random
import string
import hashlib
import hmac
from decimal import Decimal, ROUND_DOWN
import time

logger = logging.getLogger('bot')

def round_decimal(value, places=8):
    """
    Round a Decimal value to a fixed number of decimal places.
    
    Args:
        value (Decimal): The value to round
        places (int): Number of decimal places
        
    Returns:
        Decimal: Rounded value
    """
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    
    return value.quantize(Decimal('0.' + '0' * places), rounding=ROUND_DOWN)


def generate_nonce():
    """
    Generate a unique nonce for API requests.
    
    Returns:
        str: Unique nonce string
    """
    # Current timestamp plus random string
    return str(int(time.time() * 1000)) + ''.join(random.choices(string.ascii_letters + string.digits, k=8))


def hmac_sha256(secret_key, message):
    """
    Create a HMAC SHA256 signature.
    
    Args:
        secret_key (str): Secret key
        message (str): Message to sign
        
    Returns:
        str: Hex-encoded signature
    """
    return hmac.new(
        secret_key.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()


def calculate_spread_metrics(order_book):
    """
    Calculate spread metrics from an order book.
    
    Args:
        order_book (dict): Order book with bids and asks
        
    Returns:
        dict: Spread metrics
    """
    max_buy_price = Decimal(str(order_book['bids'][0][0]))
    min_sell_price = Decimal(str(order_book['asks'][0][0]))
    
    spread = min_sell_price - max_buy_price
    mid_price = (min_sell_price + max_buy_price) / 2
    spread_percentage = (spread / mid_price) * 100
    
    return {
        'max_buy_price': max_buy_price,
        'min_sell_price': min_sell_price,
        'spread': spread,
        'mid_price': mid_price,
        'spread_percentage': spread_percentage
    }


def analyze_market_trend(order_book, ticker=None):
    """
    Analyze market trend using order book and ticker data.
    
    Args:
        order_book (dict): Order book with bids and asks
        ticker (dict, optional): 24h ticker data
        
    Returns:
        str: 'bullish', 'bearish', or 'neutral'
    """
    # Calculate volume on bid and ask sides
    bid_volume = sum(bid[1] for bid in order_book['bids'])
    ask_volume = sum(ask[1] for ask in order_book['asks'])
    
    # Volume ratio
    volume_ratio = bid_volume / ask_volume if ask_volume > 0 else float('inf')
    
    # Consider recent price change if ticker is provided
    if ticker and 'price_change_percent' in ticker:
        price_change = float(ticker['price_change_percent'])
        
        # Combine volume ratio and price change for trend analysis
        if volume_ratio > 1.2 and price_change > 0:
            return 'bullish'
        elif volume_ratio < 0.8 and price_change < 0:
            return 'bearish'
        else:
            return 'neutral'
    
    # If no ticker data, just use volume ratio
    if volume_ratio > 1.2:
        return 'bullish'
    elif volume_ratio < 0.8:
        return 'bearish'
    else:
        return 'neutral'
