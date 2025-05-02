"""
This module contains different trading strategies that can be used by the bot.
Future expansion: Add more sophisticated strategies here.
"""

from decimal import Decimal
from typing import Dict, List, Any, Tuple


def calculate_basic_spread(order_book: Dict[str, Any]) -> Tuple[Decimal, Decimal, Decimal, Decimal]:
    """
    Calculate the basic spread between the lowest ask and highest bid.
    
    Args:
        order_book (Dict): Order book data with 'bids' and 'asks'
        
    Returns:
        Tuple containing:
            - Lowest ask price
            - Highest bid price
            - Spread amount
            - Spread percentage
    """
    bids = order_book.get('bids', [])
    asks = order_book.get('asks', [])
    
    if not bids or not asks:
        return Decimal('0'), Decimal('0'), Decimal('0'), Decimal('0')
    
    # Get the highest bid price
    highest_bid = max(bids, key=lambda x: x[0])[0]
    
    # Get the lowest ask price
    lowest_ask = min(asks, key=lambda x: x[0])[0]
    
    # Calculate spread
    spread = lowest_ask - highest_bid
    
    # Calculate mid price
    mid_price = (lowest_ask + highest_bid) / 2
    
    # Calculate spread percentage
    spread_percent = (spread / mid_price) * 100
    
    return lowest_ask, highest_bid, spread, spread_percent


def analyze_market_depth(order_book: Dict[str, Any], depth_percentage: Decimal = Decimal('0.05')) -> bool:
    """
    Analyze market depth to determine if the market is bullish or bearish.
    
    Args:
        order_book (Dict): Order book data
        depth_percentage (Decimal): How deep into the order book to analyze (as percentage)
        
    Returns:
        bool: True if bullish, False if bearish
    """
    bids = order_book.get('bids', [])
    asks = order_book.get('asks', [])
    
    if not bids or not asks:
        return False
    
    # Get the mid price
    highest_bid = max(bids, key=lambda x: x[0])[0]
    lowest_ask = min(asks, key=lambda x: x[0])[0]
    mid_price = (highest_bid + lowest_ask) / 2
    
    # Calculate price thresholds based on depth_percentage
    lower_bound = mid_price * (1 - depth_percentage)
    upper_bound = mid_price * (1 + depth_percentage)
    
    # Calculate buy volume within depth
    buy_volume = sum(
        qty for price, qty in bids 
        if price >= lower_bound
    )
    
    # Calculate sell volume within depth
    sell_volume = sum(
        qty for price, qty in asks 
        if price <= upper_bound
    )
    
    # Market is bullish if there's more buy volume than sell volume
    return buy_volume > sell_volume


def calculate_vwap(order_book: Dict[str, Any], side: str) -> Decimal:
    """
    Calculate the Volume-Weighted Average Price (VWAP) for a specific side of the order book.
    
    Args:
        order_book (Dict): Order book data
        side (str): 'bids' or 'asks'
        
    Returns:
        Decimal: VWAP price
    """
    orders = order_book.get(side, [])
    
    if not orders:
        return Decimal('0')
    
    total_volume = Decimal('0')
    volume_price_sum = Decimal('0')
    
    for price, volume in orders:
        total_volume += volume
        volume_price_sum += price * volume
    
    if total_volume == 0:
        return Decimal('0')
    
    return volume_price_sum / total_volume


def is_market_active(ticker: Dict[str, Any], min_volume: Decimal) -> bool:
    """
    Determine if the market is active enough for trading based on volume.
    
    Args:
        ticker (Dict): 24h ticker data
        min_volume (Decimal): Minimum acceptable 24h volume
        
    Returns:
        bool: True if market is active, False otherwise
    """
    volume = ticker.get('volume', Decimal('0'))
    return volume >= min_volume
