import asyncio
import logging
import random
import time
import json
from decimal import Decimal
from typing import Dict, List, Any, Optional
import threading

from django.utils import timezone
from asgiref.sync import sync_to_async

from notifications2.models import DeviceToken, Notification
from notifications2.firebase import send_push_notification
from django.db import transaction

# Add these imports at the top of the file
from django.apps import apps
from django.db import transaction

logger = logging.getLogger('trading')

# Add this function near the top of the file, after the imports
async def send_bot_notification(user_id, title, message, data=None):
    """
    Send a push notification to the user using Firebase.
    
    Args:
        user_id: The ID of the user to notify
        title: The notification title
        message: The notification message
        data: Additional data to include with the notification
    """
    try:
        from asgiref.sync import sync_to_async
        
        @sync_to_async
        def create_notification_and_send():
            try:
                # Get the notification model from the notification2 app
                # Import the send_push_notification function
                with transaction.atomic():
                    notification = Notification.objects.create(
                        user_id=user_id,
                        title=title,
                        message=message,
                        notification_type='ADMIN_MESSAGE',
                        is_read=False,
                        data=data or {}
                    )
                
                    # Get all user's device tokens
                    device_tokens = DeviceToken.objects.filter(user_id=user_id, is_active=True)
                    
                    # Send notification to each device
                    for device in device_tokens:
                        # Prepare data payload
                        data_payload = {
                            'notification_id': str(notification.id),
                            'notification_type': 'ADMIN_MESSAGE',
                            **(data or {})
                        }
                        # Send notification to device
                        send_push_notification(
                            device.token, 
                            title, 
                            message,
                            data=data_payload
                        )
                
                logger.info(f"Notification sent to user {user_id}: {title}")
                return notification
            except Exception as e:
                logger.error(f"Failed to send notification: {str(e)}")
                return None
        
        return await create_notification_and_send()
    except Exception as e:
        logger.error(f"Error in send_bot_notification: {str(e)}")
        return None


class TradingBot:
    """
    Trading bot for cryptocurrency trading.
    """
    def __init__(self, bot_config, exchange_client):
            """
            Initialize the trading bot with configuration and exchange client.
            """
            self.bot_config = bot_config
            self.exchange_client = exchange_client
            self.is_running = False
            self.thread = None
            self._stop_requested = threading.Event()
            self.user_id = getattr(self.bot_config, 'user_id', None)
            # In the TradingBot class __init__ method, add this line after self.user_id = getattr(self.bot_config, 'user_id', None)
            self.user_id = getattr(self.bot_config.user, 'id', None) if hasattr(self.bot_config, 'user') else None
            self.total_volume_traded = Decimal('0')
            # In the TradingBot class __init__ method, add this line after self.total_volume_traded = Decimal('0')
            # Add this line to get the user ID
            self.user_id = getattr(bot_config.user, 'id', None) if hasattr(bot_config, 'user') else None
            
            # Log target volume if set
            if hasattr(self.bot_config, 'target_volume') and self.bot_config.target_volume is not None:
                logger.info(f"Bot {self.bot_config.id} initialized with target volume: {self.bot_config.target_volume}")
            else:
                logger.info(f"Bot {self.bot_config.id} initialized without target volume limit")

    def start(self):
        """
        Start the trading bot in a background thread.
        """
        if self.is_running:
            logger.info(f"Bot {self.bot_config.id} is already running")
            return

        self.is_running = True
        self._stop_requested.clear()

        # Start the bot in a separate thread
        self.thread = threading.Thread(target=self._run_bot_thread)
        self.thread.daemon = True
        self.thread.start()

        logger.info(f"Bot {self.bot_config.id} started")

    def _run_bot_thread(self):
        """
        Run the bot in a separate thread.
        """
        # Create a new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.loop = loop

        try:
            # Run the main bot loop
            loop.run_until_complete(self._run_bot())
        except Exception as e:
            logger.error(f"Error in bot thread: {str(e)}")
            # Make sure the bot is removed from RUNNING_BOTS when an error occurs
            from bot.views import RUNNING_BOTS
            bot_id = str(getattr(self.bot_config, 'id', ''))
            if bot_id and bot_id in RUNNING_BOTS:
                logger.info(f"Removing bot {bot_id} from RUNNING_BOTS due to error")
                try:
                    del RUNNING_BOTS[bot_id]
                except KeyError:
                    pass
        finally:
            self.is_running = False

            # Clean up
            try:
                if loop.is_running():
                    loop.stop()
                if not loop.is_closed():
                    loop.close()
            except Exception as e:
                logger.error(f"Error cleaning up bot thread: {str(e)}")

            self.loop = None
            logger.info(f"Bot {self.bot_config.id} thread exited")

    async def _run_bot(self):
        """
        Main bot logic that runs until stopped.
        """
        from bot.models import BotLog, TradeOrder

        logger.info(f"Bot {self.bot_config.id} running with pair {self.bot_config.pair_symbol}")

        # Initialize consecutive error counter for auto-stopping
        consecutive_errors = 0
        max_consecutive_errors = 5
        total_volume_traded = self.total_volume_traded

        # Define sync functions for database operations
        @sync_to_async
        def create_log(config, level, message):
            try:
                return BotLog.objects.create(
                    bot_configuration=config,
                    level=level,
                    message=message
                )
            except Exception as e:
                logger.error(f"Failed to create log: {str(e)}")
                return None

        @sync_to_async
        def create_order(config, order_type, order_id, symbol, price, quantity, status):
            try:
                return TradeOrder.objects.create(
                    bot_configuration=config,
                    order_type=order_type,
                    exchange_order_id=order_id,
                    symbol=symbol,
                    price=price,
                    quantity=quantity,
                    status=status
                )
            except Exception as e:
                logger.error(f"Failed to create order record: {str(e)}")
                return None

        @sync_to_async
        def get_filled_orders(config):
            try:
                return list(TradeOrder.objects.filter(
                    bot_configuration=config,
                    status='filled'
                ))
            except Exception as e:
                logger.error(f"Failed to get filled orders: {str(e)}")
                return []

        @sync_to_async
        def update_order_status(config, order_id, status):
            try:
                return TradeOrder.objects.filter(
                    bot_configuration=config,
                    exchange_order_id=order_id
                ).update(status=status, filled_at=timezone.now())
            except Exception as e:
                logger.error(f"Failed to update order status: {str(e)}")
                return 0

        @sync_to_async
        def count_filled_orders(config):
            try:
                return TradeOrder.objects.filter(
                    bot_configuration=config, 
                    status='filled'
                ).count()
            except Exception as e:
                logger.error(f"Failed to count filled orders: {str(e)}")
                return 0

        @sync_to_async
        def update_volume_traded(config, volume_traded):
            try:
                if hasattr(config, 'volume_traded'):
                    config.volume_traded = volume_traded
                    config.save()
                    logger.info(f"Updated volume traded: {volume_traded}")
                return True
            except Exception as e:
                logger.error(f"Failed to update volume traded: {str(e)}")
                return False

        # Log bot start using sync_to_async
        try:
            await create_log(
                self.bot_config,
                'INFO',
                f"Bot {self.bot_config.id} started with pair {self.bot_config.pair_symbol}"
            )
        except Exception as e:
            logger.error(f"Failed to create initial log: {str(e)}")

        # Make sure the exchange client is initialized
        try:
            if hasattr(self.exchange_client, 'initialize'):
                await self.exchange_client.initialize()
                logger.info(f"Exchange client initialized for bot {self.bot_config.id}")
        except Exception as e:
            logger.error(f"Failed to initialize exchange client: {str(e)}")
            await create_log(
                self.bot_config,
                'ERROR',
                f"Failed to initialize exchange client: {str(e)}"
            )
            self.stop()
            return

        while self.is_running and not self._stop_requested.is_set():
            try:
                # 1. Check wallet balance to determine what we can do
                wallet_balance = await self.exchange_client.get_wallet_balance()
                
                if 'error' in wallet_balance:
                    error_msg = f"Error getting wallet balance: {wallet_balance['error']}"
                    logger.error(error_msg)
                    await create_log(
                        self.bot_config,
                        'ERROR',
                        error_msg
                    )
                    # Wait before retrying
                    await asyncio.sleep(10)
                    continue

                # Parse pair symbol to extract base and quote assets
                pair_symbol = self.bot_config.pair_symbol
                logger.info(f"Processing pair symbol: {pair_symbol}")

                # Try different separators
                if '_' in pair_symbol:
                    parts = pair_symbol.split('_')
                    base_asset = parts[0]
                    quote_asset = parts[1]
                elif '/' in pair_symbol:
                    parts = pair_symbol.split('/')
                    base_asset = parts[0]
                    quote_asset = parts[1]
                else:
                    # For pairs without separators like BTCUSDT, we need to determine where to split
                    # Common quote assets are USDT, BTC, ETH, BNB
                    common_quote_assets = ['USDT', 'BTC', 'ETH', 'BNB', 'BUSD', 'USDC']
                    for quote in common_quote_assets:
                        if pair_symbol.endswith(quote):
                            base_asset = pair_symbol[:-len(quote)]
                            quote_asset = quote
                            break
                    else:
                        # Default fallback - try to guess based on common 3-4 letter format
                        if len(pair_symbol) >= 6:  # Minimum for something like BTCETH
                            base_asset = pair_symbol[:-4]  # Assume last 4 chars are quote asset
                            quote_asset = pair_symbol[-4:]
                        else:
                            error_msg = f"Unable to parse pair symbol: {pair_symbol}"
                            logger.error(error_msg)
                            await create_log(
                                self.bot_config,
                                'ERROR',
                                error_msg
                            )
                            base_asset = "ERROR"
                            quote_asset = "ERROR"
                            self.stop()
                            break

                logger.info(f"Parsed pair: Base={base_asset}, Quote={quote_asset}")

                # Initialize with zero balance
                quote_balance = Decimal('0')
                base_balance = Decimal('0')

                # Log all available assets for debugging
                logger.info(f"Available assets in wallet: {list(wallet_balance.keys())}")

                # Handle different formats of wallet balance response
                if isinstance(wallet_balance, dict):
                    if 'data' in wallet_balance and 'balances' in wallet_balance['data']:
                        # Handle Pionex-style response
                        for balance_item in wallet_balance['data']['balances']:
                            coin = balance_item.get('coin', '')
                            free = balance_item.get('free', '0')

                            if coin.upper() == quote_asset.upper():
                                quote_balance = Decimal(free)
                                logger.info(f"Found {coin} balance (quote): {quote_balance}")

                            if coin.upper() == base_asset.upper():
                                base_balance = Decimal(free)
                                logger.info(f"Found {coin} balance (base): {base_balance}")
                    else:
                        # Try both uppercase and lowercase versions of the assets
                        base_asset_variants = [base_asset, base_asset.upper(), base_asset.lower()]
                        quote_asset_variants = [quote_asset, quote_asset.upper(), quote_asset.lower()]

                        # Check for quote asset (e.g., USDT)
                        for quote_variant in quote_asset_variants:
                            if quote_variant in wallet_balance:
                                quote_balance = Decimal(wallet_balance[quote_variant].get('free', '0'))
                                logger.info(f"Found {quote_variant} balance: {quote_balance}")
                                break

                        # Check for base asset (e.g., BTC)
                        for base_variant in base_asset_variants:
                            if base_variant in wallet_balance:
                                base_balance = Decimal(wallet_balance[base_variant].get('free', '0'))
                                logger.info(f"Found {base_variant} balance: {base_balance}")
                                break

                logger.info(f"Current balances: {base_balance} {base_asset}, {quote_balance} {quote_asset}")

                # 2. Get current market data
                ticker_data = await self.exchange_client.get_24h_ticker(self.bot_config.pair_symbol)
                if 'error' in ticker_data:
                    error_msg = f"Error getting ticker data: {ticker_data['error']}"
                    logger.error(error_msg)
                    await create_log(
                        self.bot_config,
                        'ERROR',
                        error_msg
                    )
                    # Increment consecutive errors counter
                    consecutive_errors += 1

                    # Check if we've reached the maximum consecutive errors limit
                    if consecutive_errors >= max_consecutive_errors:
                        error_msg = f"Reached {max_consecutive_errors} consecutive API errors. Stopping bot."
                        logger.error(error_msg)
                        await create_log(
                            self.bot_config,
                            'ERROR',
                            error_msg
                        )
                        self.stop()
                        break

                    await asyncio.sleep(10)
                    continue

                # Reset consecutive errors counter on success
                consecutive_errors = 0

                current_price = Decimal(ticker_data.get('close', '0'))
                logger.info(f"Current price: {current_price}")

                # 3. Get order book to analyze market depth
                order_book = await self.exchange_client.get_order_book(self.bot_config.pair_symbol)
                if 'error' in order_book:
                    error_msg = f"Error getting order book: {order_book['error']}"
                    logger.error(error_msg)
                    await create_log(
                        self.bot_config,
                        'ERROR',
                        error_msg
                    )
                    await asyncio.sleep(10)
                    continue

                bids = order_book.get('bids', [])
                asks = order_book.get('asks', [])

                if not bids or not asks:
                    logger.warning("Empty order book. Waiting for data...")
                    await create_log(
                        self.bot_config,
                        'WARNING',
                        "Empty order book. Waiting for data..."
                    )
                    await asyncio.sleep(5)
                    continue

                # Calculate total volumes for sentiment analysis
                total_bid_volume = sum(float(bid[1]) for bid in bids)
                total_ask_volume = sum(float(ask[1]) for ask in asks)

                # Determine market sentiment based on volume
                if total_bid_volume > total_ask_volume:
                    market_sentiment = "Bullish"
                else:
                    market_sentiment = "Bearish"

                logger.info(f"Market sentiment: {market_sentiment}")
             
                # Get best prices
                highest_bid = Decimal(str(bids[0][0]))
                lowest_ask = Decimal(str(asks[0][0]))
                print(highest_bid,"highest_bid")
                print(lowest_ask,"lowest_ask")

                # Calculate spread and percentage
                spread = lowest_ask - highest_bid
                print(spread,"spread")

                spread_percentage = (spread / ((highest_bid + lowest_ask) / 2)) * 100

                logger.info(f"Spread: {spread}, Spread percentage: {spread_percentage}")

                # Calculate trade price based on spread
                random_value_spread = Decimal(str(random.uniform(0, float(spread))))
                trade_price = highest_bid + random_value_spread
                print(trade_price,"trade price")
                # Format price with proper decimal precision
                trade_price = self._format_price(trade_price, self.bot_config.decimal_precision)
                print(trade_price,"trade price2222")

                # Get original trade volume from bot config
                trade_volume = self.bot_config.trade_volume

                # Special handling for minimum order sizes for specific trading pairs
                pair_symbol = self.bot_config.pair_symbol.upper()

                # Check if pair requires minimum order size
                if '_' in pair_symbol:
                    base_asset, quote_asset = pair_symbol.split('_')

                    if (base_asset == 'ACE' or base_asset == 'WOLF') and quote_asset == 'USDT':
                        min_volume = Decimal('1.0')  # Minimum 1.0 for ACE_USDT and WOLF_USDT on Pionex

                        if trade_volume < min_volume:
                            logger.info(f"Increasing trade volume for {pair_symbol} from {trade_volume} to {min_volume} to meet minimum requirements")
                            await create_log(
                                self.bot_config,
                                'INFO',
                                f"Increasing trade volume from {trade_volume} to {min_volume} to meet minimum requirements"
                            )
                            trade_volume = min_volume

                # Calculate required amounts for orders
                quote_needed_for_buy = trade_price * trade_volume
                base_needed_for_sell = trade_volume

                # Check available balance and determine which orders we can place
                can_buy = quote_balance >= quote_needed_for_buy
                can_sell = base_balance >= base_needed_for_sell

                # IMPROVEMENT 1: Check if we have enough coins to sell, show error and stop if not
                if not can_buy and not can_sell:
                    error_msg = f"Insufficient balance for both buy and sell. Need {quote_needed_for_buy} {quote_asset} or {base_needed_for_sell} {base_asset}. Stopping bot."
                    logger.warning(error_msg)
                    await create_log(
                        self.bot_config,
                        'WARNING',
                        error_msg
                    )
                    self.stop()
                    if self.user_id:
                        await send_bot_notification(
                            self.user_id,
                            "Insufficient Balance",
                            f"Bot {self.bot_config.id} stopped: Insufficient balance for trading {self.bot_config.pair_symbol}. Need {quote_needed_for_buy} {quote_asset} or {base_needed_for_sell} {base_asset}.",
                            data={
                                "bot_id": str(self.bot_config.id),
                                "pair": self.bot_config.pair_symbol,
                                "error_type": "insufficient_balance"
                            }
                        )
                    
                    break
                
                # If we don't have enough base asset to sell, show error and stop
                if not can_sell:
                    error_msg = f"Insufficient {base_asset} balance. Need {base_needed_for_sell}, have {base_balance}. Stopping bot."
                    logger.warning(error_msg)
                    await create_log(
                        self.bot_config,
                        'WARNING',
                        error_msg
                    )
                    self.stop()

                    if self.user_id:
                        await send_bot_notification(
                            self.user_id,
                            "Insufficient Balance",
                            f"Bot {self.bot_config.id} stopped: Insufficient {base_asset} balance. Need {base_needed_for_sell}, have {base_balance}.",
                            data={
                                "bot_id": str(self.bot_config.id),
                                "pair": self.bot_config.pair_symbol,
                                "error_type": "insufficient_base_asset"
                            }
                        )
                    
                    break

                
                # IMPROVEMENT 2: Check if we have enough coins to sell, prioritize buying first
                # Determine the actions based on available balance
                if not can_buy and not can_sell:
                    error_msg = f"Insufficient balance for both buy and sell. Stopping bot."
                    logger.warning(error_msg)
                    await create_log(
                        self.bot_config,
                        'WARNING',
                        error_msg
                    )
                
                    
                    self.stop()
                    break
                
                # IMPROVEMENT 2: Prioritize buying first if we don't have enough base asset to sell
                new_user_with_only_quote = (quote_balance > 0 and (base_balance == 0 or base_balance < base_needed_for_sell))
                
                if new_user_with_only_quote:
                    logger.info("Not enough base asset to sell, prioritizing buy first")
                    await create_log(
                        self.bot_config,
                        'INFO',
                        f"Not enough {base_asset} to sell, prioritizing buy first"
                    )
                    can_buy = True
                    can_sell = False

                logger.info(f"Can buy: {can_buy} ({quote_balance} >= {quote_needed_for_buy})")
                logger.info(f"Can sell: {can_sell} ({base_balance} >= {base_needed_for_sell})")

                # Track total volume traded
                filled_orders = await get_filled_orders(self.bot_config)
                for order in filled_orders:
                    if hasattr(order, 'quantity'):
                        total_volume_traded += order.quantity

                logger.info(f"Total volume traded so far: {total_volume_traded}")

                # STOP CONDITION: Check if we've reached the target volume (if configured)
                if hasattr(self.bot_config, 'target_volume') and self.bot_config.target_volume and total_volume_traded >= self.bot_config.target_volume:
                    logger.info(f"Target volume of {self.bot_config.target_volume} reached. Stopping bot.")
                    await create_log(
                        self.bot_config,
                        'INFO',
                        f"Target volume of {self.bot_config.target_volume} reached. Bot stopped."
                    )
                    self.stop()
                    break

                # Initialize order variables
                buy_order = {"error": "Not placed"}
                sell_order = {"error": "Not placed"}

                # IMPROVEMENT 4: Check order book for same size orders to avoid competing with ourselves
                # This helps create volume without loss or profit
                should_place_orders = True
                
                # Check if there are existing orders with the same size
                same_size_orders_exist = False
                for bid in bids:
                    if Decimal(str(bid[1])) == trade_volume:
                        same_size_orders_exist = True
                        logger.info(f"Found existing bid with same size {trade_volume}. Waiting for our turn.")
                        await create_log(
                            self.bot_config,
                            'INFO',
                            f"Found existing bid with same size {trade_volume}. Waiting for our turn."
                        )
                        break
                
                for ask in asks:
                    if Decimal(str(ask[1])) == trade_volume:
                        same_size_orders_exist = True
                        logger.info(f"Found existing ask with same size {trade_volume}. Waiting for our turn.")
                        await create_log(
                            self.bot_config,
                            'INFO',
                            f"Found existing ask with same size {trade_volume}. Waiting for our turn."
                        )
                        break
                
                if same_size_orders_exist:
                    # Wait for a bit before checking again
                    await asyncio.sleep(self.bot_config.time_interval)
                    continue

                # IMPROVEMENT 2: For new users with only quote asset (e.g., USDT), buy first
                if new_user_with_only_quote:
                    if can_buy:
                        logger.info(f"New user flow: Placing buy order with {quote_needed_for_buy} {quote_asset}")
                        try:
                            buy_order = await self.exchange_client.place_order('buy', self.bot_config.pair_symbol, trade_volume, trade_price)
                            
                            # IMPROVEMENT 1: Better error handling and logging
                            if 'error' in buy_order:
                                error_msg = f"Error placing buy order: {buy_order['error']}"
                                logger.error(error_msg)
                                
                                # IMPROVEMENT 3: Provide specific error messages for limit/size issues
                                if "minimum" in buy_order['error'].lower() or "size" in buy_order['error'].lower():
                                    error_msg = f"Order size too small: Minimum required is likely higher than {trade_volume}"
                                elif "precision" in buy_order['error'].lower() or "decimal" in buy_order['error'].lower():
                                    error_msg = f"Price precision error: {trade_price} exceeds allowed decimal precision"
                                elif "insufficient" in buy_order['error'].lower() or "balance" in buy_order['error'].lower():
                                    error_msg = f"Insufficient balance: Need {quote_needed_for_buy} {quote_asset}, have {quote_balance}"
                                
                                await create_log(
                                    self.bot_config,
                                    'ERROR',
                                    error_msg
                                )
                                # Wait before retrying
                                await asyncio.sleep(10)
                                continue
                            else:
                                # Log successful order
                                logger.info(f"Buy order placed: {buy_order}")
                                # await create_log(
                                #     self.bot_config,
                                #     'INFO',
                                #     f"Buy order placed: ID={buy_order.get('order_id', 'unknown')}, Price={trade_price}, Volume={trade_volume}"
                                # )
                                
                                # Save order to database
                                if 'order_id' in buy_order:
                                    await create_order(
                                        self.bot_config,
                                        'buy',
                                        buy_order['order_id'],
                                        self.bot_config.pair_symbol,
                                        trade_price,
                                        trade_volume,
                                        'open'
                                    )

                                    # Check order status after placement
                                    # await asyncio.sleep(2)  # Wait a moment for the order to be processed
                                    buy_status = await self.exchange_client.get_order_status(buy_order['order_id'], self.bot_config.pair_symbol)
                                    if 'status' in buy_status and buy_status['status'] == 'filled':
                                        logger.info(f"Buy order {buy_order['order_id']} filled immediately!")
                                        await create_log(
                                            self.bot_config,
                                            'INFO',
                                            f"Buy order {buy_order['order_id']} filled"
                                        )
                                        await update_order_status(
                                            self.bot_config,
                                            buy_order['order_id'],
                                            'filled'
                                        )

                        except Exception as e:
                            error_msg = f"Exception placing buy order: {str(e)}"
                            logger.error(error_msg)
                            await create_log(
                                self.bot_config,
                                'ERROR',
                                error_msg
                            )
                    else:
                        logger.info(f"Skipping buy order, insufficient {quote_asset} balance")
                        await create_log(
                            self.bot_config,
                            'INFO',
                            f"Skipping buy order, insufficient {quote_asset} balance (have {quote_balance}, need {quote_needed_for_buy})"
                        )
                # Case 2: Experienced user with both assets - IMPROVEMENT 2: Sell first, then buy
                else:
                    # First place a sell order if we have enough base asset (e.g., BTC)
                    if can_sell:
                        logger.info(f"Placing sell order with {base_needed_for_sell} {base_asset}")
                        try:
                            sell_order = await self.exchange_client.place_order('sell', self.bot_config.pair_symbol, trade_volume, trade_price)
                            
                            # Better error handling and logging
                            if 'error' in sell_order:
                                # Extract API error information if available
                                api_code = sell_order.get('api_code', '')
                                api_message = sell_order.get('api_message', '')
                                
                                if api_code and api_message:
                                    error_msg = f"Error placing sell order: {api_code}: {api_message}"
                                else:
                                    error_msg = f"Error placing sell order: {sell_order['error']}"
                                
                                logger.error(error_msg)
                                await create_log(
                                    self.bot_config,
                                    'ERROR',
                                    error_msg
                                )
                                
                                # IMPROVEMENT 3: Handle TRADE_AMOUNT_FILTER_DENIED error with retries
                                if "TRADE_AMOUNT_FILTER_DENIED" in str(sell_order.get('error', '')):
                                    retry_count = 0
                                    max_retries = 3
                                    while retry_count < max_retries:
                                        retry_count += 1
                                        logger.info(f"Retrying sell order after TRADE_AMOUNT_FILTER_DENIED error (attempt {retry_count}/{max_retries})")
                                        await create_log(
                                            self.bot_config,
                                            'INFO',
                                            f"Retrying sell order after filter error (attempt {retry_count}/{max_retries})"
                                        )
                                        await asyncio.sleep(2)  # Wait before retry
                                        
                                        # Try with slightly adjusted volume
                                        adjusted_volume = trade_volume
                                        adjusted_volume = self._format_price(adjusted_volume, self.bot_config.decimal_precision)
                                        
                                        sell_order = await self.exchange_client.place_order('sell', self.bot_config.pair_symbol, adjusted_volume, trade_price)
                                        if 'error' not in sell_order:
                                            logger.info(f"Sell order retry successful with adjusted volume {adjusted_volume}")
                                            break
                                    
                                    if retry_count >= max_retries and 'error' in sell_order:
                                        logger.error(f"Failed to place sell order after {max_retries} retries. Stopping bot.")
                                        await create_log(
                                            self.bot_config,
                                            'ERROR',
                                            f"Failed to place sell order after {max_retries} retries. Stopping bot."
                                        )
                                        self.stop()
                                        break
                                
                                # Continue with next iteration if error persists
                                if 'error' in sell_order:
                                    await asyncio.sleep(10)
                                    continue
                            else:
                                # Log successful order
                                logger.info(f"Sell order placed: {sell_order}")
                                # await create_log(
                                #     self.bot_config,
                                #     'INFO',
                                #     f"Sell order placed: ID={sell_order.get('order_id', 'unknown')}, Price={trade_price}, Volume={trade_volume}"
                                # )
                                
                                # Save order to database
                                if 'order_id' in sell_order:
                                    await create_order(
                                        self.bot_config,
                                        'sell',
                                        sell_order['order_id'],
                                        self.bot_config.pair_symbol,
                                        trade_price,
                                        trade_volume,
                                        'open'
                                    )

                                    # Check sell order status to see if it was filled
                                    await asyncio.sleep(2)  # Wait a moment for the order to be processed
                                    sell_status = await self.exchange_client.get_order_status(sell_order['order_id'], self.bot_config.pair_symbol)
                                    if 'status' in sell_status and sell_status['status'] == 'filled':
                                        logger.info(f"Sell order {sell_order['order_id']} filled immediately!")
                                        await create_log(
                                            self.bot_config,
                                            'INFO',
                                            f"Sell order {sell_order['order_id']} filled"
                                        )
                                        # Update order in database
                                        await update_order_status(
                                            self.bot_config,
                                            sell_order['order_id'],
                                            'filled'
                                        )
                        except Exception as e:
                            error_msg = f"Exception placing sell order: {str(e)}"
                            logger.error(error_msg)
                            await create_log(
                                self.bot_config,
                                'ERROR',
                                error_msg
                            )
                    
                    # Next place a buy order if we have enough quote asset (e.g., USDT)
                    if can_buy:
                        logger.info(f"Placing buy order with {quote_needed_for_buy} {quote_asset}")
                        try:
                            buy_order = await self.exchange_client.place_order('buy', self.bot_config.pair_symbol, trade_volume, trade_price)
                            
                            # Better error handling and logging
                            if 'error' in buy_order:
                                # Extract API error information if available
                                api_code = buy_order.get('api_code', '')
                                api_message = buy_order.get('api_message', '')
                                
                                if api_code and api_message:
                                    error_msg = f"Error placing buy order: {api_code}: {api_message}"
                                else:
                                    error_msg = f"Error placing buy order: {buy_order['error']}"
                                
                                logger.error(error_msg)
                                await create_log(
                                    self.bot_config,
                                    'ERROR',
                                    error_msg
                                )
                                
                                # IMPROVEMENT 3: Handle TRADE_AMOUNT_FILTER_DENIED error with retries
                                if "TRADE_AMOUNT_FILTER_DENIED" in str(buy_order.get('error', '')):
                                    retry_count = 0
                                    max_retries = 3
                                    while retry_count < max_retries:
                                        retry_count += 1
                                        logger.info(f"Retrying buy order after TRADE_AMOUNT_FILTER_DENIED error (attempt {retry_count}/{max_retries})")
                                        await create_log(
                                            self.bot_config,
                                            'INFO',
                                            f"Retrying buy order after filter error (attempt {retry_count}/{max_retries})"
                                        )
                                        await asyncio.sleep(2)  # Wait before retry
                                        
                                        # Try with slightly adjusted volume
                                        adjusted_volume = trade_volume * Decimal('1.001')
                                        adjusted_volume = self._format_price(adjusted_volume, self.bot_config.decimal_precision)
                                        
                                        buy_order = await self.exchange_client.place_order('buy', self.bot_config.pair_symbol, adjusted_volume, trade_price)
                                        if 'error' not in buy_order:
                                            logger.info(f"Buy order retry successful with adjusted volume {adjusted_volume}")
                                            break
                                    
                                    if retry_count >= max_retries and 'error' in buy_order:
                                        logger.error(f"Failed to place buy order after {max_retries} retries. Stopping bot.")
                                        await create_log(
                                            self.bot_config,
                                            'ERROR',
                                            f"Failed to place buy order after {max_retries} retries. Stopping bot."
                                        )
                                        self.stop()
                                        break
                                
                                # Wait before retrying
                                if 'error' in buy_order:
                                    await asyncio.sleep(10)
                                    continue
                            else:
                                # Log successful order
                                logger.info(f"Buy order placed: {buy_order}")
                                # await create_log(
                                #     self.bot_config,
                                #     'INFO',
                                #     f"Buy order placed: ID={buy_order.get('order_id', 'unknown')}, Price={trade_price}, Volume={trade_volume}"
                                # )

                                # Save order to database
                                if 'order_id' in buy_order:
                                    await create_order(
                                        self.bot_config,
                                        'buy',
                                        buy_order['order_id'],
                                        self.bot_config.pair_symbol,
                                        trade_price,
                                        trade_volume,
                                        'open'
                                    )

                                    # Check buy order status immediately to see if it was filled
                                    await asyncio.sleep(2)  # Wait a moment for the order to be processed
                                    buy_status = await self.exchange_client.get_order_status(buy_order['order_id'], self.bot_config.pair_symbol)
                                    if 'status' in buy_status and buy_status['status'] == 'filled':
                                        logger.info(f"Buy order {buy_order['order_id']} filled immediately!")
                                        await create_log(
                                            self.bot_config,
                                            'INFO',
                                            f"Buy order {buy_order['order_id']} filled"
                                        )
                                        # Update order in database
                                        await update_order_status(
                                            self.bot_config,
                                            buy_order['order_id'],
                                            'filled'
                                        )
                        except Exception as e:
                            error_msg = f"Exception placing buy order: {str(e)}"
                            logger.error(error_msg)
                            await create_log(
                                self.bot_config,
                                'ERROR',
                                error_msg
                            )

                # Check status of recently placed orders
                try:
                    open_orders = await self.exchange_client.get_open_orders(self.bot_config.pair_symbol)

                    # For debugging
                    logger.info(f"Current open orders: {len(open_orders)}")

                    # If there are no open orders, all orders have been filled
                    if isinstance(open_orders, list) and len(open_orders) == 0:
                        # Check if it's because the orders were filled
                        filled_orders_count = await count_filled_orders(self.bot_config)

                        if filled_orders_count > 0:
                            logger.info(f"All orders filled. Trade volume complete with {filled_orders_count} filled orders.")
                            await create_log(
                                self.bot_config,
                                'INFO',
                                f"Trade volume complete with {filled_orders_count} filled orders and total volume of {total_volume_traded}."
                            )

                            # Update the total volume traded
                            await update_volume_traded(self.bot_config, total_volume_traded)

                            # Update instance variable for volume tracking
                            self.total_volume_traded = total_volume_traded

                            # Check if target volume has been reached
                            if (hasattr(self.bot_config, 'target_volume') and 
                                self.bot_config.target_volume is not None and 
                                self.bot_config.target_volume > Decimal('0') and
                                total_volume_traded >= self.bot_config.target_volume):

                                logger.info(f"Target volume of {self.bot_config.target_volume} reached with {total_volume_traded}. Stopping bot.")
                                await create_log(
                                    self.bot_config,
                                    'INFO',
                                    f"Target volume of {self.bot_config.target_volume} reached with {total_volume_traded}. Stopping bot."
                                )

                                # Update status to completed
                                try:
                                    # Import here to avoid circular imports
                                    from django.utils import timezone

                                    @sync_to_async
                                    def update_status():
                                        # Update bot configuration to completed status
                                        if hasattr(self.bot_config, 'status'):
                                            self.bot_config.status = 'completed'
                                            self.bot_config.is_active = False
                                            self.bot_config.updated_at = timezone.now()
                                            self.bot_config.save(update_fields=['status', 'is_active', 'updated_at'])

                                    await update_status()
                                    logger.info(f"Bot {self.bot_config.id} status updated to 'completed'")
                                except Exception as status_error:
                                    logger.error(f"Failed to update bot status to completed: {str(status_error)}")
                               
                                if self.user_id:
                                    await send_bot_notification(
                                        self.user_id,
                                        "Bot Completed",
                                        f"Trading bot {self.bot_config.id} for {self.bot_config.pair_symbol} has completed trading with target volume {self.bot_config.target_volume}.",
                                        data={
                                            "bot_id": str(self.bot_config.id),
                                            "pair": self.bot_config.pair_symbol,
                                            "status": "completed"
                                        }
                                    )
                                # Signal the bot to stop
                                self._stop_requested.set()
                except Exception as e:
                    error_msg = f"Error checking open orders: {str(e)}"
                    logger.error(error_msg)
                    await create_log(
                        self.bot_config,
                        'ERROR',
                        error_msg
                    )

                # Wait before the next iteration
                await asyncio.sleep(self.bot_config.time_interval)

            except Exception as e:
                error_msg = f"Error in bot loop: {str(e)}"
                logger.error(error_msg)
                await create_log(
                    self.bot_config,
                    'ERROR',
                    error_msg
                )

                # Set bot status to error
                try:
                    # Import here to avoid circular imports
                    from django.utils import timezone

                    @sync_to_async
                    def update_status():
                        # Update bot configuration to error status
                        if hasattr(self.bot_config, 'status'):
                            self.bot_config.status = 'error'
                            self.bot_config.is_active = False
                            self.bot_config.updated_at = timezone.now()
                            self.bot_config.save(update_fields=['status', 'is_active', 'updated_at'])

                    await update_status()
                    logger.info(f"Bot {self.bot_config.id} status updated to 'error'")
                except Exception as status_error:
                    logger.error(f"Failed to update bot status to error: {str(status_error)}")

                await asyncio.sleep(10)  # Wait a bit longer on error

        # Clean up the exchange client
        try:
            await self.cleanup_exchange_client()

            # Set bot status to stopped if it's not already in error state
            try:
                # Import here to avoid circular imports
                from django.utils import timezone

                @sync_to_async
                def update_final_status():
                    # Update bot configuration to stopped status if not in error
                    if hasattr(self.bot_config, 'status') and self.bot_config.status != 'error':
                        self.bot_config.status = 'stopped'
                        self.bot_config.is_active = False
                        self.bot_config.updated_at = timezone.now()
                        self.bot_config.save(update_fields=['status', 'is_active','updated_at'])

                await update_final_status()
                logger.info(f"Bot {self.bot_config.id} status updated to 'stopped' after completion")
            except Exception as status_error:
                logger.error(f"Failed to update final bot status: {str(status_error)}")

        except Exception as e:
            logger.error(f"Error during exchange client cleanup: {str(e)}")

        # Log bot stop
        logger.info(f"Bot {self.bot_config.id} stopped")

        # Create bot log for stop with total volume from instance variable
        await create_log(
            self.bot_config,
            'INFO',
            f"Bot {self.bot_config.id} stopped with total volume traded: {self.total_volume_traded}"
        )

    async def cleanup_exchange_client(self):
        """
        Clean up the exchange client to prevent unclosed session warnings.
        """
        try:
            if hasattr(self.exchange_client, 'cleanup') and callable(self.exchange_client.cleanup):
                logger.info(f"Cleaning up exchange client for bot {self.bot_config.id}")
                await self.exchange_client.cleanup()
                logger.info(f"Exchange client for bot {self.bot_config.id} cleaned up successfully")
            else:
                logger.warning(f"Exchange client for bot {self.bot_config.id} does not have a cleanup method")
        except Exception as e:
            logger.error(f"Error cleaning up exchange client: {str(e)}")
  
    def stop(self):
            """
            Stop the trading bot.
            """
            if not self.is_running:
                logger.info(f"Bot {self.bot_config.id} is not running")
                return

            # Signal the bot to stop using thread-safe event
            self._stop_requested.set()

            # Send notification that the bot has stopped
            if hasattr(self, 'user_id') and self.user_id:
                # Create a temporary event loop for the notification if needed
                if self.loop is None:
                    temp_loop = asyncio.new_event_loop()
                    temp_loop.run_until_complete(send_bot_notification(
                        self.user_id,
                        "Bot Stopped",
                        f"Trading bot {self.bot_config.id} for {self.bot_config.pair_symbol} has been stopped.",
                        data={
                            "bot_id": str(self.bot_config.id),
                            "pair": self.bot_config.pair_symbol,
                            "status": "stopped"
                        }
                    ))
                    # Don't close the loop here as it's used for other operations below
                else:
                    # Use the existing loop
                    asyncio.run_coroutine_threadsafe(
                        send_bot_notification(
                            self.user_id,
                            "Bot Stopped",
                            f"Trading bot {self.bot_config.id} for {self.bot_config.pair_symbol} has been stopped.",
                            data={
                                "bot_id": str(self.bot_config.id),
                                "pair": self.bot_config.pair_symbol,
                                "status": "stopped"
                            }
                        ),
                        self.loop
                    )

            # Create a temporary event loop for cleanup if needed
            if self.loop is None:
                temp_loop = asyncio.new_event_loop()
                temp_loop.run_until_complete(self.cleanup_exchange_client())

                # Update bot status in database in the temp event loop
                async def update_bot_status():
                    try:
                        # Import here to avoid circular imports
                        from django.utils import timezone

                        @sync_to_async
                        def update_status():
                            # Update bot configuration to stopped status
                            if hasattr(self.bot_config, 'status'):
                                self.bot_config.status = 'stopped'
                                self.bot_config.is_active = False
                                self.bot_config.updated_at = timezone.now()
                                self.bot_config.save(update_fields=['status', 'is_active', 'updated_at'])

                        await update_status()
                        logger.info(f"Bot {self.bot_config.id} status updated to 'stopped'")
                    except Exception as status_error:
                        logger.error(f"Failed to update bot status on stop: {str(status_error)}")

                temp_loop.run_until_complete(update_bot_status())
                temp_loop.close()

            logger.info(f"Stop requested for bot {self.bot_config.id}")

    def _format_price(self, price, decimal_precision):
        """
        Format the price with proper decimal precision.
        Special handling for certain pairs that require specific precision.
        """
        # Special case handling for specific trading pairs
        pair_symbol = self.bot_config.pair_symbol.upper() if hasattr(self, 'bot_config') and hasattr(self.bot_config, 'pair_symbol') else ''

        # Special precision handling for specific pairs
        if '_' in pair_symbol:
            base_asset, quote_asset = pair_symbol.split('_')

            # WOLF_USDT typically has a different precision requirement
            if base_asset == 'WOLF' and quote_asset == 'USDT':
                # Ensure WOLF_USDT uses 8 decimal places for price precision
                logger.info(f"Using special price formatting for WOLF_USDT pair: 8 decimal places")
                format_str = "{:.8f}"
                return Decimal(format_str.format(price))

        # Default formatting based on bot configuration
        format_str = f"{{:.{decimal_precision}f}}"
        return Decimal(format_str.format(price))