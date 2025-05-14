import logging
import asyncio
from typing import Dict, Any, List, Optional, Callable, TypeVar
from rest_framework import viewsets, status, permissions
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView
from rest_framework.filters import SearchFilter
from rest_framework.response import Response
from rest_framework.decorators import api_view
from django.shortcuts import get_object_or_404
from django.conf import settings
from django.utils import timezone,dateparse
from .models import Exchange, BotConfiguration, TradeOrder, BotLog
from django.db.models import Q
from decimal import Decimal
from .serializers import (
    ExchangeSerializer, TradingPairSerializer, BotConfigurationSerializer,
    TradeOrderSerializer, BotLogSerializer, BotStartSerializer, BotStopSerializer,
    WalletBalanceRequestSerializer, CancelOrderSerializer, OrderCheckSerializer,BotUpdateSerializer
)
from asgiref.sync import async_to_sync
from exchanges.factory import get_exchange_client
from trading.engine import TradingBot
# Set up logging
from notifications2.models import DeviceToken, Notification
from notifications2.firebase import send_bulk_notifications
# Add these imports at the top of the file
from django.apps import apps
from django.db import transaction
logger = logging.getLogger('bot')

# Global dictionary to store running bot instances
RUNNING_BOTS = {}
# Type variable for the async function result
T = TypeVar('T')

class StandardResultsSetPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 500

def run_async_with_cleanup(async_func: Callable, exchange_client, *args, **kwargs):
    """
    Helper function to run an async function with proper exchange client cleanup.
    
    Args:
        async_func: The async function to execute
        exchange_client: The exchange client object
        *args, **kwargs: Arguments to pass to the async function
    
    Returns:
        The result of the async function execution
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = None
    
    try:
        # Run the primary async function
        result = loop.run_until_complete(async_func(exchange_client, *args, **kwargs))
        
        # Clean up exchange client session if possible
        if hasattr(exchange_client, 'cleanup'):
            logger.info("Cleaning up exchange client session")
            loop.run_until_complete(exchange_client.cleanup())
    except Exception as e:
        # Log any errors that occur
        logger.error(f"Error in async operation: {str(e)}")
        raise e
    finally:
        # Always close the event loop
        if not loop.is_closed():
            loop.close()
    
    return result


class BotPagination(PageNumberPagination):
    page_size = 10  # Changed from 1 to a more reasonable 10 items per page
    page_size_query_param = 'page_size'
    max_page_size = 100


class ExchangeViewSet(viewsets.ModelViewSet):
    """
    API endpoint to list all supported exchanges.
    Only administrators can create new exchanges.
    """
    queryset = Exchange.objects.filter(is_active=True)
    serializer_class = ExchangeSerializer
    
    def get_permissions(self):
        """
        - GET requests require no special permissions
        - POST/PUT/PATCH/DELETE requests require admin permissions
        """
        if self.action == 'list' or self.action == 'retrieve':
            permission_classes = [permissions.AllowAny]
        else:
            permission_classes = [permissions.IsAdminUser]
        return [permission() for permission in permission_classes]
    
    def perform_create(self, serializer):
        """
        Save the exchange with the admin user who created it
        """
        serializer.save()


class IsAdminOrOwner(permissions.BasePermission):
    """
    Custom permission: Admins can access all, users can only access their own.
    """

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        return request.user.is_staff or obj.user == request.user
    

class BotConfigurationViewSet(viewsets.ModelViewSet):
    """
    API endpoint for CRUD operations on bot configurations.
    """
    queryset = BotConfiguration.objects.all() 
    serializer_class = BotConfigurationSerializer
    permission_classes = [IsAdminOrOwner]
    pagination_class = BotPagination  
    filter_backends = (SearchFilter,)  
    search_fields = ['pair_symbol',"status"]  # add fields as needed
    filterset_fields = ['is_active']  # enable filtering

    def get_queryset(self):
        user = self.request.user
        queryset = BotConfiguration.objects.all()

        if not user.is_staff:
            queryset = queryset.filter(user_id=user)

        return queryset

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def get_serializer_class(self):
        """
        Use different serializers for create vs update operations.
        """
        if self.action in ['update', 'partial_update', 'put']:
            return BotUpdateSerializer
        return BotConfigurationSerializer

    def put(self, request, *args, **kwargs):
        """
        Override PUT to use partial update.
        """
        # Get the existing instance
        instance = self.get_object()
        
        # Use the update serializer
        serializer = BotUpdateSerializer(instance, data=request.data, partial=True)
        
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class TradingPairAPIView(APIView):
    """
    API endpoint to get trading pairs from a specific exchange
    """
    permission_classes = [permissions.IsAuthenticated]

    async def _get_pairs_async(self, exchange_client):
        """Helper method to get trading pairs asynchronously"""
        try:
            # Call the exchange client to get real pairs
            pairs = await exchange_client.get_pairs()
            return pairs
        except Exception as e:
            logger.error(f"Error fetching trading pairs: {str(e)}")
            raise e

    def get(self, request):
        # First check if a bot_config_id is provided
        bot_config_id = request.query_params.get('bot_config_id')

        if bot_config_id:
            try:
                # Get the bot configuration that belongs to the authenticated user
                bot_config = BotConfiguration.objects.get(id=bot_config_id, user=request.user)

                # Initialize exchange client with stored credentials
                exchange_client = get_exchange_client(
                    bot_config.exchange.name.lower(),
                    bot_config.api_key,
                    bot_config.secret_key,
                    bot_config.memo
                )

                if not exchange_client:
                    return Response(
                        {"error": f"Failed to initialize {bot_config.exchange.name} client"},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )

                try:
                    # Run the async function in a synchronous context
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    pairs = loop.run_until_complete(self._get_pairs_async(exchange_client))
                    loop.close()

                    # Format pairs as needed for our API
                    formatted_pairs = []
                    for pair in pairs:
                        # Ensure the data format matches our serializer
                        formatted_pair = {
                            "symbol": pair.get("symbol", ""),
                            "base_asset": pair.get("base_asset", ""),
                            "quote_asset": pair.get("quote_asset", ""),
                            "min_quantity": pair.get("min_quantity", "0"),
                            "max_quantity": pair.get("max_quantity"),
                            "price_precision": pair.get("price_precision", 0),
                            "quantity_precision": pair.get("quantity_precision", 0)
                        }
                        formatted_pairs.append(formatted_pair)

                    # Validate pairs with our serializer
                    serializer = TradingPairSerializer(data=formatted_pairs, many=True)
                    if serializer.is_valid():
                        return Response(serializer.validated_data)
                    else:
                        # Log serialization errors and return raw data
                        logger.warning(f"Trading pair serialization errors: {serializer.errors}")
                        return Response({
                            "pairs": formatted_pairs,
                            "validation_errors": serializer.errors,
                            "message": "Retrieved trading pairs but encountered format validation issues"
                        })

                except Exception as e:
                    logger.error(f"Error processing trading pairs: {str(e)}")
                    return Response(
                        {"error": f"Error processing trading pairs: {str(e)}"},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )

            except BotConfiguration.DoesNotExist:
                return Response(
                    {"error": f"Bot configuration with ID {bot_config_id} not found or does not belong to you"},
                    status=status.HTTP_404_NOT_FOUND
                )

        # Fallback to the original implementation if no bot_config_id is provided
        # This is kept for backward compatibility but should be used only in secure contexts
        exchange_name = request.query_params.get('exchange')
        api_key = request.query_params.get('api_key', '')
        secret_key = request.query_params.get('secret_key', '')

        if not exchange_name:
            return Response(
                {"error": "Either bot_config_id or exchange parameter is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Verify that the exchange exists in our system
            Exchange.objects.get(name=exchange_name, is_active=True)

            if not api_key or not secret_key:
                return Response({
                    "error": "API credentials (api_key and secret_key) are required to fetch trading pairs",
                    "message": "Please provide valid API credentials to access exchange data or use bot_config_id"
                }, status=status.HTTP_400_BAD_REQUEST)

            # Initialize exchange client with provided credentials
            exchange_client = get_exchange_client(
                exchange_name.lower(),
                api_key,
                secret_key
            )

            if not exchange_client:
                return Response(
                    {"error": f"Failed to initialize {exchange_name} client"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

            try:
                # Use the helper function to run async code with proper client cleanup
                pairs = run_async_with_cleanup(
                    self._get_pairs_async,
                    exchange_client
                )

                # Format pairs as needed for our API
                formatted_pairs = []
                for pair in pairs:
                    # Ensure the data format matches our serializer
                    formatted_pair = {
                        "symbol": pair.get("symbol", ""),
                        "base_asset": pair.get("base_asset", ""),
                        "quote_asset": pair.get("quote_asset", ""),
                        "min_quantity": pair.get("min_quantity", "0"),
                        "max_quantity": pair.get("max_quantity"),
                        "price_precision": pair.get("price_precision", 0),
                        "quantity_precision": pair.get("quantity_precision", 0)
                    }
                    formatted_pairs.append(formatted_pair)

                # Validate pairs with our serializer
                serializer = TradingPairSerializer(data=formatted_pairs, many=True)
                if serializer.is_valid():
                    return Response(serializer.validated_data)
                else:
                    # Log serialization errors and return raw data
                    logger.warning(f"Trading pair serialization errors: {serializer.errors}")
                    return Response({
                        "pairs": formatted_pairs,
                        "validation_errors": serializer.errors,
                        "message": "Retrieved trading pairs but encountered format validation issues"
                    })

            except Exception as e:
                logger.error(f"Error processing trading pairs: {str(e)}")
                return Response(
                    {"error": f"Error processing trading pairs: {str(e)}"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        except Exchange.DoesNotExist:
            return Response(
                {"error": f"Exchange '{exchange_name}' not found or inactive"}, 
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error fetching pairs from {exchange_name}: {str(e)}")
            return Response(
                {"error": f"Error fetching pairs: {str(e)}"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class BotStatusAPIView(APIView):
    """
    API endpoint to get the status of all bots or a specific bot
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        bot_id = request.query_params.get('bot_id')

        if bot_id:
            try:
                # Make sure the bot belongs to the authenticated user
                bot_config = BotConfiguration.objects.get(id=bot_id, user=request.user)
                serializer = BotConfigurationSerializer(bot_config)

                # Get data from serializer (which already includes status field)
                data = serializer.data
                
                # For backward compatibility, add is_running field too
                data['is_running'] = bot_id in RUNNING_BOTS
                
                # Ensure status field reflects running state for older bots
                if bot_id in RUNNING_BOTS and data['status'] == 'idle':
                    data['status'] = 'running'

                return Response(data)
            except BotConfiguration.DoesNotExist:
                return Response({"error": f"Bot configuration with ID {bot_id} not found or does not belong to you"}, 
                               status=status.HTTP_404_NOT_FOUND)
        else:
            # Return status of only the user's bots
            bot_configs = BotConfiguration.objects.filter(user=request.user)
            serializer = BotConfigurationSerializer(bot_configs, many=True)

            # Add running status to each bot in the response
            data = serializer.data
            for bot in data:
                bot_id = str(bot['id'])
                # For backward compatibility
                bot['is_running'] = bot_id in RUNNING_BOTS
                
                # Ensure status field reflects running state for older bots
                if bot_id in RUNNING_BOTS and bot['status'] == 'idle':
                    bot['status'] = 'running'

            return Response(data)


class BotStartAPIView(APIView):
    """
    API endpoint to start a trading bot with two methods:
    1. POST with bot_id parameter to start an existing bot
    2. POST with detailed configuration to create and start a new bot
    """
    permission_classes = [permissions.IsAuthenticated,IsAdminOrOwner]

    def post(self, request):
        # Check if we're starting an existing bot
        bot_id = request.data.get('bot_id')
        if bot_id:
            # User wants to start an existing bot configuration
            try:
                # Get the bot configuration
                bot_config = BotConfiguration.objects.get(id=bot_id, user=request.user)

                # Check if it's already running
                if str(bot_id) in RUNNING_BOTS:
                    # Check if the bot thread is actually still alive
                    bot_instance = RUNNING_BOTS[str(bot_id)]
                    if hasattr(bot_instance, 'thread') and bot_instance.thread and bot_instance.thread.is_alive():
                        return Response({
                            "message": "Bot is already running",
                            "bot_id": bot_id
                        })
                    else:
                        # Bot is in RUNNING_BOTS but thread is not alive (stopped due to error)
                        # Remove it from RUNNING_BOTS
                        logger.info(f"Removing stopped bot {bot_id} from RUNNING_BOTS")
                        del RUNNING_BOTS[str(bot_id)]

                # Set as active
                bot_config.is_active = True
                bot_config.status = "running"
                bot_config.save()

                # Initialize exchange client
                exchange_client = get_exchange_client(
                    bot_config.exchange.name.lower(),
                    bot_config.api_key,
                    bot_config.secret_key,
                    bot_config.memo
                )

                # Create and start bot
                bot = TradingBot(
                    bot_config=bot_config,
                    exchange_client=exchange_client
                )

                # Store the bot instance
                RUNNING_BOTS[str(bot_id)] = bot

                # Actually start the bot
                bot.start()

                try:
                    wallet_balance = async_to_sync(
                        exchange_client.get_wallet_balance,
                        # exchange_client
                    )
                    
                    # Check if there's an error in the wallet balance response
                    if isinstance(wallet_balance, dict) and 'error' in wallet_balance:
                        error_msg = f"Error getting wallet balance: {wallet_balance['error']}"
                        logger.error(error_msg)
                        
                        # Create a log entry
                        BotLog.objects.create(
                            bot_configuration=bot_config,
                            level='ERROR',
                            message=error_msg
                        )
                        
                        # Create notification and send push notification
                        try:
                            notification = Notification.objects.create(
                                user=request.user,
                                title="Wallet Balance Error",
                                message=f"Bot {bot_id} encountered an error checking wallet balance: {wallet_balance['error']}",
                                notification_type="ADMIN_MESSAGE",
                                is_read=False,
                                data={
                                    "bot_id": bot_id,
                                    "error_type": "wallet_balance_error"
                                }
                            )
                            
                            # Get all user's device tokens
                            device_tokens = DeviceToken.objects.filter(user=request.user, is_active=True)
                            tokens = [dt.token for dt in device_tokens]
                            
                            # Prepare data payload
                            data_payload = {
                                'notification_id': str(notification.id),
                                'notification_type': "ADMIN_MESSAGE",
                                'bot_id': bot_id,
                                'error_type': "wallet_balance_error"
                            }
                            
                            # Send notification to all user devices
                            if tokens:
                                send_bulk_notifications(
                                    tokens, 
                                    "Wallet Balance Error", 
                                    f"Bot {bot_id} encountered an error checking wallet balance: {wallet_balance['error']}",
                                    data=data_payload
                                )
                        except Exception as notif_error:
                            logger.error(f"Failed to create notification: {str(notif_error)}")
                        
                        # Return the response with the error
                        return Response({
                            "message": f"Bot {bot_id} started but encountered a wallet balance error",
                            "bot_id": bot_id,
                            "exchange": bot_config.exchange.name,
                            "pair": bot_config.pair_symbol,
                            "error": error_msg
                        })
                    
                    # Log the bot start with balance information
                    BotLog.objects.create(
                        bot_configuration=bot_config,
                        level='INFO',
                        message=f"Bot started using existing configuration with real exchange data. Wallet balance checked."
                    )
                    
                except Exception as e:
                    logger.error(f"Error checking wallet balance: {str(e)}")
                    # Continue with bot operation even if balance check fails

                # Log the bot start
                BotLog.objects.create(
                    bot_configuration=bot_config,
                    level='INFO',
                    message="Bot started using existing configuration with real exchange data"
                )


                # Log the bot start
                BotLog.objects.create(
                    bot_configuration=bot_config,
                    level='INFO',
                    message="Bot started using existing configuration with real exchange data"
                )

                return Response({
                    "message": f"Bot {bot_id} started successfully with real exchange data",
                    "bot_id": bot_id,
                    "exchange": bot_config.exchange.name,
                    "pair": bot_config.pair_symbol
                })

            except BotConfiguration.DoesNotExist:
                return Response(
                    {"error": f"Bot configuration with ID {bot_id} not found or does not belong to you"},
                    status=status.HTTP_404_NOT_FOUND
                )

        else:
            # Create a new bot configuration from the provided data
            serializer = BotStartSerializer(data=request.data)

            if serializer.is_valid():
                data = serializer.validated_data

                # Get or create exchange
                exchange, _ = Exchange.objects.get_or_create(
                    name=data['exchange'],
                    defaults={'description': f"{data['exchange']} cryptocurrency exchange"}
                )

                # Instead of saving the trading pair to the database, we'll use it directly from the request
                pair_symbol = data['pair']

                # Create bot configuration directly associated with the exchange and the current user
                bot_config = BotConfiguration.objects.create(
                    exchange=exchange,
                    # We'll store just the pair symbol, but not link to a TradingPair model
                    pair_symbol=pair_symbol,
                    api_key=data['api_key'],
                    secret_key=data['secret_key'],
                    decimal_precision=data['decimal_precision'],
                    risk_tolerance=data['risk_tolerance'],
                    trade_volume=data['trade_volume'],
                    time_interval=data['time_interval'],
                    is_active=False,
                    status='idle',  # Initialize with idle status
                    target_volume=data.get('target_volume'),  # Include target volume if provided
                    user=request.user  # Associate with current user
                )

                # Log the bot start request
                BotLog.objects.create(
                    bot_configuration=bot_config,
                    level='INFO',
                    message=f"Bot start requested for {exchange.name} with pair {pair_symbol}"
                )

                # Start the bot in a background task if it's not already running
                bot_id = str(bot_config.id)
                if bot_id not in RUNNING_BOTS:
                    # Initialize exchange client
                    exchange_client = get_exchange_client(
                        exchange.name.lower(),
                        data['api_key'],
                        data['secret_key'],
                        data['memo']
                    )

                    # Create and start bot
                    bot = TradingBot(
                        bot_config=bot_config,
                        exchange_client=exchange_client
                    )

                    # Store the bot instance and start it
                    RUNNING_BOTS[bot_id] = bot

                    # Actually start the bot
                    bot.start()

                    try:
                        wallet_balance = async_to_sync(
                            exchange_client.get_wallet_balance,
                            # exchange_client
                        )
                        
                        # Check if there's an error in the wallet balance response
                        if isinstance(wallet_balance, dict) and 'error' in wallet_balance:
                            error_msg = f"Error getting wallet balance: {wallet_balance['error']}"
                            logger.error(error_msg)
                            
                            # Create a log entry
                            BotLog.objects.create(
                                bot_configuration=bot_config,
                                level='ERROR',
                                message=error_msg
                            )
                            
                            # Create notification and send push notification
                            try:
                                # Get the notification models
                                # Create notification record
                                notification = Notification.objects.create(
                                    user=request.user,
                                    title="Wallet Balance Error",
                                    message=f"Bot {bot_id} encountered an error checking wallet balance: {wallet_balance['error']}",
                                    notification_type="ADMIN_MESSAGE",
                                    is_read=False,
                                    data={
                                        "bot_id": bot_id,
                                        "error_type": "wallet_balance_error"
                                    }
                                )
                                
                                # Get all user's device tokens
                                device_tokens = DeviceToken.objects.filter(user=request.user, is_active=True)
                                tokens = [dt.token for dt in device_tokens]
                                
                                # Prepare data payload
                                data_payload = {
                                    'notification_id': str(notification.id),
                                    'notification_type': "ADMIN_MESSAGE",
                                    'bot_id': bot_id,
                                    'error_type': "wallet_balance_error"
                                }
                                
                                # Send notification to all user devices
                                if tokens:
                                    send_bulk_notifications(
                                        tokens, 
                                        "Wallet Balance Error", 
                                        f"Bot {bot_id} encountered an error checking wallet balance: {wallet_balance['error']}",
                                        data=data_payload
                                    )
                            except Exception as notif_error:
                                logger.error(f"Failed to create notification: {str(notif_error)}")
                            
                            # Return the response with the error
                            return Response({
                                "message": f"Bot {bot_id} started but encountered a wallet balance error",
                                "bot_id": bot_id,
                                "exchange": bot_config.exchange.name,
                                "pair": bot_config.pair_symbol,
                                "error": error_msg
                            })
                        
                        # Log the bot start with balance information
                        BotLog.objects.create(
                            bot_configuration=bot_config,
                            level='INFO',
                            message=f"Bot started using existing configuration with real exchange data. Wallet balance checked."
                        )
                        
                    except Exception as e:
                        logger.error(f"Error checking wallet balance: {str(e)}")
                        # Continue with bot operation even if balance check fails
                        
                    # Log the bot start
                    BotLog.objects.create(
                        bot_configuration=bot_config,
                        level='INFO',
                        message="New trading bot started with real exchange data"
                    )

                    return Response({
                        "message": "New bot created and started successfully with real exchange data",
                        "bot_id": bot_config.id,
                        "exchange": exchange.name,
                        "pair": pair_symbol
                    })

                return Response({
                    "message": "New bot configuration created but not started",
                    "bot_id": bot_config.id,
                    "exchange": exchange.name,
                    "pair": pair_symbol
                })

            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def get(self, request):
        """
        Allow starting a bot with a GET request using query parameters

        Query parameters:
        - bot_id: Required. The ID of the bot configuration to start
        """
        bot_id = request.query_params.get('bot_id')

        if not bot_id:
            return Response(
                {"error": "bot_id query parameter is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Get the bot configuration
            bot_config = BotConfiguration.objects.get(id=bot_id, user=request.user)

            # Check if it's already running
            if str(bot_id) in RUNNING_BOTS:
                return Response({
                    "message": "Bot is already running",
                    "bot_id": bot_id
                })

            # Set as active
            bot_config.is_active = True
            bot_config.status = "running"
            bot_config.save()

            # Initialize exchange client
            exchange_client = get_exchange_client(
                bot_config.exchange.name.lower(),
                bot_config.api_key,
                bot_config.secret_key,
                bot_config.memo
            )

            # Create and start bot
            bot = TradingBot(
                bot_config=bot_config,
                exchange_client=exchange_client
            )

            # Store the bot instance
            RUNNING_BOTS[str(bot_id)] = bot

            # Actually start the bot
            bot.start()

            # Log the bot start
            BotLog.objects.create(
                bot_configuration=bot_config,
                level='INFO',
                message="Bot started via GET request with real exchange data"
            )

            return Response({
                "message": f"Bot {bot_id} started successfully with real exchange data",
                "bot_id": bot_id,
                "exchange": bot_config.exchange.name,
                "pair": bot_config.pair_symbol
            })

        except BotConfiguration.DoesNotExist:
            return Response(
                {"error": f"Bot configuration with ID {bot_id} not found or does not belong to you"},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error starting bot: {str(e)}")
            return Response(
                {"error": f"Error starting bot: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class BotStopAPIView(APIView):
    """
    API endpoint to stop a trading bot
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = BotStopSerializer(data=request.data)

        if serializer.is_valid():
            bot_id = str(serializer.validated_data['bot_id'])

            try:
                # Make sure the bot belongs to the authenticated user
                bot_config = BotConfiguration.objects.get(id=bot_id, user=request.user)

                # Check if it's running
                if bot_id in RUNNING_BOTS:
                    # Get the bot instance
                    bot = RUNNING_BOTS[bot_id]

                    # Actually stop the bot
                    bot.stop()

                    # Remove from running bots
                    del RUNNING_BOTS[bot_id]

                    # Update bot configuration status
                    bot_config.is_active = False
                    bot_config.status = "stopped"
                    bot_config.save()

                    # Log the bot stop
                    BotLog.objects.create(
                        bot_configuration=bot_config,
                        level='INFO',
                        message="Bot stopped via API request"
                    )
                    try:
                        # Get the notification models
                        
                        # Create notification record
                        notification = Notification.objects.create(
                            user=request.user,
                            title="Bot Stopped",
                            message=f"Trading bot {bot_id} for {bot_config.pair_symbol} has been stopped via API request.",
                            notification_type="ADMIN_MESSAGE",
                            is_read=False,
                            data={
                                "bot_id": bot_id,
                                "pair": bot_config.pair_symbol,
                                "status": "stopped"
                            }
                        )
                        
                        # Get all user's device tokens
                        device_tokens = DeviceToken.objects.filter(user=request.user, is_active=True)
                        tokens = [dt.token for dt in device_tokens]
                        
                        # Prepare data payload
                        data_payload = {
                            'notification_id': str(notification.id),
                            'notification_type': "ADMIN_MESSAGE",
                            'bot_id': bot_id,
                            'status': "stopped"
                        }
                        
                        # Send notification to all user devices
                        if tokens:
                            send_bulk_notifications(
                                tokens, 
                                "Bot Stopped", 
                                f"Trading bot {bot_id} for {bot_config.pair_symbol} has been stopped via API request.",
                                data=data_payload
                            )
                    except Exception as e:
                        logger.error(f"Failed to create notification for bot stop: {str(e)}")

                    return Response({
                        "message": f"Bot {bot_id} stopped successfully",
                        "bot_id": bot_id
                    })
                else:
                    # Bot is not running, just update its status
                    if bot_config.is_active:
                        bot_config.is_active = False
                        bot_config.status = "stopped"
                        bot_config.save()

                        BotLog.objects.create(
                            bot_configuration=bot_config,
                            level='INFO',
                            message="Bot marked as inactive (was not running)"
                        )

                    return Response({
                        "message": f"Bot {bot_id} is not running, marked as inactive",
                        "bot_id": bot_id
                    })

            except BotConfiguration.DoesNotExist:
                return Response(
                    {"error": f"Bot configuration with ID {bot_id} not found or does not belong to you"},
                    status=status.HTTP_404_NOT_FOUND
                )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def get(self, request):
        """
        Allow stopping a bot with a GET request using query parameters

        Query parameters:
        - bot_id: Required. The ID of the bot configuration to stop
        """
        bot_id = request.query_params.get('bot_id')

        if not bot_id:
            return Response(
                {"error": "bot_id query parameter is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Make sure the bot belongs to the authenticated user
            bot_config = BotConfiguration.objects.get(id=bot_id, user=request.user)

            # Check if it's running
            if str(bot_id) in RUNNING_BOTS:
                # Get the bot instance
                bot = RUNNING_BOTS[str(bot_id)]

                # Actually stop the bot
                bot.stop()

                # Remove from running bots
                del RUNNING_BOTS[str(bot_id)]

                # Update bot configuration status
                bot_config.is_active = False
                bot_config.status = "stopped"
                bot_config.save()

                # Log the bot stop
                BotLog.objects.create(
                    bot_configuration=bot_config,
                    level='INFO',
                    message="Bot stopped via GET request"
                )

                return Response({
                    "message": f"Bot {bot_id} stopped successfully",
                    "bot_id": bot_id
                })
            else:
                # Bot is not running, just update its status
                if bot_config.is_active:
                    bot_config.is_active = False
                    bot_config.status = "stopped"
                    bot_config.save()

                    BotLog.objects.create(
                        bot_configuration=bot_config,
                        level='INFO',
                        message="Bot marked as inactive (was not running)"
                    )

                return Response({
                    "message": f"Bot {bot_id} is not running, marked as inactive",
                    "bot_id": bot_id
                })

        except BotConfiguration.DoesNotExist:
            return Response(
                {"error": f"Bot configuration with ID {bot_id} not found or does not belong to you"},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error stopping bot: {str(e)}")
            return Response(
                {"error": f"Error stopping bot: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class LogsAPIView(APIView):
    """
    API endpoint to get bot logs with filtering and pagination
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        log_type = request.query_params.get('log_type')
        bot_id = request.query_params.get('bot_id')
        user_id = request.query_params.get('user_id')
        exchange_id = request.query_params.get('exchange_id')
        pair = request.query_params.get('pair')
        level = request.query_params.get('level')
        start_time = request.query_params.get('start_time')
        end_time = request.query_params.get('end_time')
        search_term = request.query_params.get('search')

        is_admin = request.user.is_staff or request.user.is_superuser
        logs_query = BotLog.objects.all()

        if log_type == 'user_action':
            logs_query = logs_query.filter(
                Q(message__icontains='bot started') | 
                Q(message__icontains='bot stopped') |
                Q(message__icontains='start bot') |
                Q(message__icontains='stop bot')
            )
        elif log_type == 'bot_operation':
            logs_query = logs_query.exclude(
                Q(message__icontains='bot started') | 
                Q(message__icontains='bot stopped') |
                Q(message__icontains='start bot') |
                Q(message__icontains='stop bot')
            )

        if bot_id:
            logs_query = logs_query.filter(bot_configuration_id=bot_id)

        if not is_admin:
            user_bots = BotConfiguration.objects.filter(user=request.user).values_list('id', flat=True)
            logs_query = logs_query.filter(bot_configuration__in=user_bots)
        elif user_id:
            logs_query = logs_query.filter(bot_configuration__user_id=user_id)

        if exchange_id:
            logs_query = logs_query.filter(bot_configuration__exchange_id=exchange_id)
        if pair:
            logs_query = logs_query.filter(bot_configuration__pair=pair)
        if level:
            logs_query = logs_query.filter(level=level)
        if search_term:
            logs_query = logs_query.filter(message__icontains=search_term)
        if start_time:
            start_datetime = dateparse.parse_datetime(start_time)
            if start_datetime:
                logs_query = logs_query.filter(created_at__gte=start_datetime)
        if end_time:
            end_datetime = dateparse.parse_datetime(end_time)
            if end_datetime:
                logs_query = logs_query.filter(created_at__lte=end_datetime)

        logs_query = logs_query.order_by('-created_at')

        # ✅ Apply pagination
        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(logs_query, request)
        serializer = BotLogSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class OrdersAPIView(APIView):
    """
    API endpoint to get bot orders
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        bot_id = request.query_params.get('bot_id')
        limit = int(request.query_params.get('limit', 100))
        status = request.query_params.get('status')

        if bot_id:
            try:
                # Make sure the bot belongs to the authenticated user
                bot_config = BotConfiguration.objects.get(id=bot_id, user=request.user)
                orders_query = TradeOrder.objects.filter(bot_configuration=bot_config)

                # Filter by status if provided
                if status:
                    orders_query = orders_query.filter(status=status)

                orders = orders_query.order_by('-created_at')[:limit]
                serializer = TradeOrderSerializer(orders, many=True)

                # Get summary statistics
                buy_orders = orders_query.filter(order_type='buy').count()
                sell_orders = orders_query.filter(order_type='sell').count()
                filled_orders = orders_query.filter(status='filled').count()
                open_orders = orders_query.filter(status='open').count()

                return Response({
                    'orders': serializer.data,
                    'summary': {
                        'total': orders_query.count(),
                        'buy_orders': buy_orders,
                        'sell_orders': sell_orders,
                        'filled_orders': filled_orders,
                        'open_orders': open_orders
                    }
                })
            except BotConfiguration.DoesNotExist:
                return Response(
                    {"error": f"Bot configuration with ID {bot_id} not found or does not belong to you"},
                    status=status.HTTP_404_NOT_FOUND
                )
        else:
            # Get orders for all bots belonging to the user
            user_bots = BotConfiguration.objects.filter(user=request.user).values_list('id', flat=True)
            orders_query = TradeOrder.objects.filter(bot_configuration__in=user_bots)

            # Filter by status if provided
            if status:
                orders_query = orders_query.filter(status=status)

            orders = orders_query.order_by('-created_at')[:limit]
            serializer = TradeOrderSerializer(orders, many=True)

            return Response(serializer.data)


class WalletBalanceAPIView(APIView):
    """
    API endpoint to get user wallet balance from exchange using GET or POST
    """
    permission_classes = [permissions.IsAuthenticated]

    async def _get_balance_async(self, exchange_client):
        """Helper method to get the wallet balance asynchronously"""
        try:
            # Call the exchange client to get real balance
            balance = await exchange_client.get_wallet_balance()

            # Check if the response contains an error message
            if isinstance(balance, dict) and 'error' in balance:
                logger.error(f"Error in balance response: {balance['error']}")
                # Return the error in a format that can be properly handled
                return {'error': balance['error'], 'success': False}

            return balance
        except Exception as e:
            logger.error(f"Error fetching wallet balance: {str(e)}")
            # Return error in a format that can be properly handled
            return {'error': str(e), 'success': False}
            
    async def _get_total_balance_async(self, exchange_client, balance):
        """Calculate total balance by converting all coins to USDT"""
        try:
            if isinstance(balance, dict) and 'error' in balance:
                return balance
                
            total_balance = Decimal('0')
            
            # Extract USDT balance first if it exists
            if 'USDT' in balance:
                usdt_total = Decimal(balance['USDT']['total'])
                total_balance += usdt_total
            
            # Get current prices for other assets
            for symbol, asset_data in balance.items():
                if symbol == 'USDT':
                    continue  # Already counted
                
                # Check if the asset has a balance
                if Decimal(asset_data['total']) > 0:
                    try:
                        # Get the current price of this asset in USDT
                        ticker = await exchange_client.get_ticker_price(f"{symbol}_USDT")
                        if ticker and 'price' in ticker:
                            price = Decimal(str(ticker['price']))
                            asset_value = Decimal(asset_data['total']) * price
                            total_balance += asset_value
                            logger.debug(f"Converted {symbol}: {asset_data['total']} * {price} = {asset_value} USDT")
                        else:
                            logger.warning(f"Could not get price for {symbol}_USDT")
                    except Exception as e:
                        logger.warning(f"Error getting price for {symbol}: {str(e)}")
            
            return str(total_balance)
        except Exception as e:
            logger.error(f"Error calculating total balance: {str(e)}")
            return "0"  # Return 0 as fallback if calculation fails

    def get(self, request):
        """
        Get wallet balance using GET request with query parameters.
        Either bot_id or exchange must be provided.
        """
        exchange_name = request.query_params.get('exchange')
        bot_id = request.query_params.get('bot_id')
        api_key = request.query_params.get('api_key')
        secret_key = request.query_params.get('secret_key')

        if bot_id:
            try:
                # Get the bot configuration to use its stored API credentials
                bot_config = BotConfiguration.objects.get(id=bot_id, user=request.user)

                # Initialize exchange client using the stored credentials
                exchange_client = get_exchange_client(
                    bot_config.exchange.name.lower(),
                    bot_config.api_key,
                    bot_config.secret_key,
                    bot_config.memo
                )

                if exchange_client:
                    try:
                        # Use the helper function to run async code with proper cleanup
                        balance = run_async_with_cleanup(
                            self._get_balance_async, 
                            exchange_client
                        )
                        
                        # Calculate total balance in USDT
                        total_balance = run_async_with_cleanup(
                            self._get_total_balance_async,
                            exchange_client,
                            balance
                        )

                        return Response({
                            "exchange": bot_config.exchange.name,
                            "balance": balance,
                            "total_balance": total_balance,
                            "bot_id": bot_id
                        })
                    except Exception as e:
                        return Response(
                            {"error": f"Error fetching balance from exchange: {str(e)}"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR
                        )
                else:
                    return Response(
                        {"error": f"Failed to initialize {bot_config.exchange.name} client"},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )

            except BotConfiguration.DoesNotExist:
                return Response(
                    {"error": f"Bot configuration with ID {bot_id} not found or does not belong to you"},
                    status=status.HTTP_404_NOT_FOUND
                )

        elif exchange_name and api_key and secret_key:
            # For cases where the user provides API credentials directly in the query parameters
            try:
                # Get the exchange
                exchange = Exchange.objects.get(name=exchange_name, is_active=True)

                # Initialize exchange client with provided credentials
                exchange_client = get_exchange_client(
                    exchange_name.lower(),
                    api_key,
                    secret_key,
                    
                )

                if exchange_client:
                    try:
                        # Use the helper function to run async code with proper client cleanup
                        balance = run_async_with_cleanup(
                            self._get_balance_async, 
                            exchange_client
                        )
                        
                        # Calculate total balance in USDT
                        total_balance = run_async_with_cleanup(
                            self._get_total_balance_async,
                            exchange_client,
                            balance
                        )

                        return Response({
                            "exchange": exchange.name,
                            "balance": balance,
                            "total_balance": total_balance
                        })
                    except Exception as e:
                        return Response(
                            {"error": f"Error fetching balance from exchange: {str(e)}"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR
                        )
                else:
                    return Response(
                        {"error": f"Failed to initialize {exchange_name} client"},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )

            except Exchange.DoesNotExist:
                return Response(
                    {"error": f"Exchange '{exchange_name}' not found or inactive"},
                    status=status.HTTP_404_NOT_FOUND
                )

        elif exchange_name:
            return Response(
                {"error": "For direct exchange balance checks, both api_key and secret_key must be provided"},
                status=status.HTTP_400_BAD_REQUEST
            )

        else:
            return Response(
                {"error": "Either 'bot_id' or 'exchange' with API credentials is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

    def post(self, request):
        """
        Get wallet balance using POST request with API credentials in the request body.
        """
        serializer = WalletBalanceRequestSerializer(data=request.data)

        if serializer.is_valid():
            data = serializer.validated_data

            try:
                # Get or verify exchange exists
                exchange, _ = Exchange.objects.get_or_create(
                    name=data['exchange'],
                    defaults={'description': f"{data['exchange']} cryptocurrency exchange"}
                )

                # Initialize exchange client
                exchange_client = get_exchange_client(
                    exchange.name.lower(),
                    data['api_key'],
                    data['secret_key'],
                    data['memo']

                )

                if exchange_client:
                    try:
                        # Use the helper function to run async code with proper cleanup
                        balance = run_async_with_cleanup(
                            self._get_balance_async, 
                            exchange_client
                        )
                        
                        # Calculate total balance in USDT
                        total_balance = run_async_with_cleanup(
                            self._get_total_balance_async,
                            exchange_client,
                            balance
                        )

                        return Response({
                            "exchange": exchange.name,
                            "balance": balance,
                            "total_balance": total_balance
                        })
                    except Exception as e:
                        return Response(
                            {"error": f"Error fetching balance from exchange: {str(e)}"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR
                        )
                else:
                    return Response(
                        {"error": f"Failed to initialize {exchange.name} client"},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )

            except Exception as e:
                logger.error(f"Error fetching wallet balance: {str(e)}")
                return Response(
                    {"error": f"Error fetching wallet balance: {str(e)}"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class OrderStatusAPIView(APIView):
    """
    API endpoint to check the status of a specific order or all orders for a bot
    """
    permission_classes = [permissions.IsAuthenticated]

    async def _get_order_status_async(self, exchange_client, order_id, pair):
        """Helper method to get the order status asynchronously"""
        try:
            # Call the exchange client to get real order status
            order_status = await exchange_client.get_order_status(order_id, pair)
            return order_status
        except Exception as e:
            logger.error(f"Error fetching order status: {str(e)}")
            raise e

    def get(self, request):
        """
        Check order status with a GET request

        Query parameters:
        - bot_id: Required. The ID of the bot configuration
        - order_id: Optional. If provided, checks status of specific order
        """
        bot_id = request.query_params.get('bot_id')
        order_id = request.query_params.get('order_id')

        if not bot_id:
            return Response(
                {"error": "bot_id query parameter is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Make sure the bot belongs to the authenticated user
            bot_config = BotConfiguration.objects.get(id=bot_id, user=request.user)

            # Initialize exchange client
            exchange_client = get_exchange_client(
                bot_config.exchange.name.lower(),
                bot_config.api_key,
                bot_config.secret_key,
                bot_config.memo

            )

            if not exchange_client:
                return Response(
                    {"error": f"Failed to initialize {bot_config.exchange.name} client"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

            if order_id:
                # Check specific order
                try:
                    # First get the order from the database so we have the full details
                    order = TradeOrder.objects.get(
                        bot_configuration=bot_config,
                        exchange_order_id=order_id
                    )

                    # Then fetch real-time status from the exchange
                    try:
                        # Use the helper function to run async code with proper client cleanup
                        order_status = run_async_with_cleanup(
                            self._get_order_status_async,
                            exchange_client,
                            order.exchange_order_id, 
                            order.symbol
                        )

                        # Update order in database with latest status
                        if 'status' in order_status:
                            order.status = order_status['status']
                            if order_status['status'] == 'filled' and not order.filled_at:
                                order.filled_at = timezone.now()
                            order.save()

                        # Serialize the updated order
                        serializer = TradeOrderSerializer(order)

                        return Response({
                            "order": serializer.data,
                            "exchange_status": order_status,
                            "bot_id": bot_id,
                            "exchange": bot_config.exchange.name
                        })
                    except Exception as e:
                        # If the exchange request fails, at least return what we have in the database
                        serializer = TradeOrderSerializer(order)
                        return Response({
                            "order": serializer.data,
                            "bot_id": bot_id,
                            "exchange": bot_config.exchange.name,
                            "error": f"Could not fetch live status from exchange: {str(e)}"
                        })

                except TradeOrder.DoesNotExist:
                    return Response(
                        {"error": f"Order with ID {order_id} not found for bot {bot_id}"},
                        status=status.HTTP_404_NOT_FOUND
                    )
            else:
                # Check all orders for the bot
                try:
                    # Fetch all orders from the database
                    orders = TradeOrder.objects.filter(bot_configuration=bot_config).order_by('-created_at')

                    # We could fetch real-time status for each order here, but that would be inefficient
                    # for a large number of orders. Instead, we'll return what we have in the database
                    # and suggest using the specific order endpoint for real-time status of individual orders.
                    serializer = TradeOrderSerializer(orders, many=True)

                    return Response({
                        "orders": serializer.data,
                        "count": orders.count(),
                        "exchange": bot_config.exchange.name,
                        "pair": bot_config.pair_symbol,
                        "bot_id": bot_id,
                        "message": "For real-time status of individual orders, use the endpoint with an order_id parameter"
                    })
                except Exception as e:
                    return Response(
                        {"error": f"Error retrieving orders: {str(e)}"},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )

        except BotConfiguration.DoesNotExist:
            return Response(
                {"error": f"Bot configuration with ID {bot_id} not found or does not belong to you"},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error checking order status: {str(e)}")
            return Response(
                {"error": f"Error checking order status: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def post(self, request):
        """
        Legacy method maintained for backward compatibility
        """
        serializer = OrderCheckSerializer(data=request.data)

        if serializer.is_valid():
            data = serializer.validated_data
            bot_id = data['bot_id']
            order_id = data.get('order_id')

            try:
                # Make sure the bot belongs to the authenticated user
                bot_config = BotConfiguration.objects.get(id=bot_id, user=request.user)

                # Initialize exchange client
                exchange_client = get_exchange_client(
                    bot_config.exchange.name.lower(),
                    bot_config.api_key,
                    bot_config.secret_key,
                    bot_config.memo
                )

                if not exchange_client:
                    return Response(
                        {"error": f"Failed to initialize {bot_config.exchange.name} client"},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )

                if order_id:
                    # Check specific order
                    try:
                        # First get the order from the database so we have the full details
                        order = TradeOrder.objects.get(
                            bot_configuration=bot_config,
                            exchange_order_id=order_id
                        )

                        # Then fetch real-time status from the exchange with proper cleanup
                        try:
                            # Use the helper function to run async code with proper client cleanup
                            order_status = run_async_with_cleanup(
                                self._get_order_status_async,
                                exchange_client,
                                order.exchange_order_id, 
                                order.symbol
                            )

                            # Update order in database with latest status
                            if 'status' in order_status:
                                order.status = order_status['status']
                                if order_status['status'] == 'filled' and not order.filled_at:
                                    order.filled_at = timezone.now()
                                order.save()

                            # Serialize the updated order
                            serializer = TradeOrderSerializer(order)

                            return Response({
                                "order": serializer.data,
                                "exchange_status": order_status,
                                "exchange": bot_config.exchange.name
                            })
                        except Exception as e:
                            # If the exchange request fails, at least return what we have in the database
                            serializer = TradeOrderSerializer(order)
                            return Response({
                                "order": serializer.data,
                                "exchange": bot_config.exchange.name,
                                "error": f"Could not fetch live status from exchange: {str(e)}"
                            })

                    except TradeOrder.DoesNotExist:
                        return Response(
                            {"error": f"Order with ID {order_id} not found for bot {bot_id}"},
                            status=status.HTTP_404_NOT_FOUND
                        )
                else:
                    # Check all orders for the bot
                    orders = TradeOrder.objects.filter(bot_configuration=bot_config).order_by('-created_at')
                    serializer = TradeOrderSerializer(orders, many=True)
                    return Response({
                        "orders": serializer.data,
                        "count": orders.count(),
                        "exchange": bot_config.exchange.name,
                        "message": "For real-time status of individual orders, use the endpoint with an order_id parameter"
                    })

            except BotConfiguration.DoesNotExist:
                return Response(
                    {"error": f"Bot configuration with ID {bot_id} not found or does not belong to you"},
                    status=status.HTTP_404_NOT_FOUND
                )
            except Exception as e:
                logger.error(f"Error checking order status: {str(e)}")
                return Response(
                    {"error": f"Error checking order status: {str(e)}"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class CancelOrderAPIView(APIView):
    """
    API endpoint to cancel a specific order or all open orders for a bot
    """
    permission_classes = [permissions.IsAuthenticated]

    async def _cancel_order_async(self, exchange_client, order_id, pair):
        """Helper method to cancel an order asynchronously"""
        try:
            # Call the exchange client to cancel the order
            result = await exchange_client.cancel_order(order_id, pair)
            return result
        except Exception as e:
            logger.error(f"Error cancelling order: {str(e)}")
            raise e

    def get(self, request):
        """
        Cancel orders using GET request with query parameters:
        - bot_id: Required. The ID of the bot configuration
        - order_id: Optional. The ID of a specific order to cancel
        - cancel_all: Optional. Set to 'true' to cancel all open orders for the bot
        """
        bot_id = request.query_params.get('bot_id')
        order_id = request.query_params.get('order_id')
        cancel_all_param = request.query_params.get('cancel_all', 'false').lower()
        cancel_all = cancel_all_param in ('true', '1', 'yes')

        if not bot_id:
            return Response(
                {"error": "bot_id query parameter is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not order_id and not cancel_all:
            return Response(
                {"error": "Either order_id or cancel_all=true query parameter is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Make sure the bot belongs to the authenticated user
            bot_config = BotConfiguration.objects.get(id=bot_id, user=request.user)

            # Initialize exchange client
            exchange_client = get_exchange_client(
                bot_config.exchange.name.lower(),
                bot_config.api_key,
                bot_config.secret_key,
                bot_config.memo

            )

            if not exchange_client:
                return Response(
                    {"error": f"Failed to initialize {bot_config.exchange.name} client"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

            cancelled_orders = []

            if cancel_all:
                # Cancel all open orders
                orders = TradeOrder.objects.filter(
                    bot_configuration=bot_config,
                    status='open'
                )

                # Cancel each order by calling the exchange API
                for order in orders:
                    try:
                        # Use the helper function to run async code with proper client cleanup
                        result = run_async_with_cleanup(
                            self._cancel_order_async,
                            exchange_client,
                            order.exchange_order_id, 
                            order.symbol
                        )

                        if result:
                            # Update order status in database
                            order.status = 'canceled'
                            order.save()
                            cancelled_orders.append(order.id)

                            # Log the cancellation
                            BotLog.objects.create(
                                bot_configuration=bot_config,
                                level='INFO',
                                message=f"Order {order.exchange_order_id} cancelled successfully"
                            )
                        else:
                            BotLog.objects.create(
                                bot_configuration=bot_config,
                                level='ERROR',
                                message=f"Failed to cancel order {order.exchange_order_id}"
                            )
                    except Exception as e:
                        logger.error(f"Error cancelling order {order.exchange_order_id}: {str(e)}")
                        BotLog.objects.create(
                            bot_configuration=bot_config,
                            level='ERROR',
                            message=f"Error cancelling order {order.exchange_order_id}: {str(e)}"
                        )

                return Response({
                    "message": f"Cancelled {len(cancelled_orders)} orders",
                    "cancelled_orders": cancelled_orders,
                    "bot_id": bot_id,
                    "exchange": bot_config.exchange.name
                })

            elif order_id:
                # Cancel specific order
                try:
                    order = TradeOrder.objects.get(
                        bot_configuration=bot_config,
                        exchange_order_id=order_id,
                        status='open'
                    )

                    # Call the exchange API to cancel the order
                    try:
                        # Use the helper function to run async code with proper client cleanup
                        result = run_async_with_cleanup(
                            self._cancel_order_async,
                            exchange_client,
                            order.exchange_order_id, 
                            order.symbol
                        )

                        if result:
                            # Update order status in database
                            order.status = 'canceled'
                            order.save()

                            # Log the cancellation
                            BotLog.objects.create(
                                bot_configuration=bot_config,
                                level='INFO',
                                message=f"Order {order.exchange_order_id} cancelled successfully"
                            )

                            return Response({
                                "message": f"Order {order_id} cancelled successfully",
                                "bot_id": bot_id,
                                "exchange": bot_config.exchange.name
                            })
                        else:
                            return Response({
                                "error": f"Failed to cancel order {order_id}",
                                "bot_id": bot_id,
                                "exchange": bot_config.exchange.name
                            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                    except Exception as e:
                        return Response({
                            "error": f"Error cancelling order: {str(e)}",
                            "bot_id": bot_id,
                            "exchange": bot_config.exchange.name
                        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

                except TradeOrder.DoesNotExist:
                    return Response(
                        {"error": f"Open order with ID {order_id} not found for bot {bot_id}"},
                        status=status.HTTP_404_NOT_FOUND
                    )

        except BotConfiguration.DoesNotExist:
            return Response(
                {"error": f"Bot configuration with ID {bot_id} not found or does not belong to you"},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error cancelling order(s): {str(e)}")
            return Response(
                {"error": f"Error cancelling order(s): {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def post(self, request):
        """
        Legacy method maintained for backward compatibility
        """
        serializer = CancelOrderSerializer(data=request.data)

        if serializer.is_valid():
            data = serializer.validated_data
            bot_id = data['bot_id']
            order_id = data.get('order_id')
            cancel_all = data.get('cancel_all', False)

            if not order_id and not cancel_all:
                return Response(
                    {"error": "Must provide either order_id or set cancel_all to true"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                # Make sure the bot belongs to the authenticated user
                bot_config = BotConfiguration.objects.get(id=bot_id, user=request.user)

                # Initialize exchange client
                exchange_client = get_exchange_client(
                    bot_config.exchange.name.lower(),
                    bot_config.api_key,
                    bot_config.secret_key,
                    bot_config.memo

                )

                if not exchange_client:
                    return Response(
                        {"error": f"Failed to initialize {bot_config.exchange.name} client"},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )

                cancelled_orders = []

                if cancel_all:
                    # Cancel all open orders
                    orders = TradeOrder.objects.filter(
                        bot_configuration=bot_config,
                        status='open'
                    )

                    # Cancel each order by calling the exchange API
                    for order in orders:
                        try:
                            # Use the helper function to run async code with proper client cleanup
                            result = run_async_with_cleanup(
                                self._cancel_order_async,
                                exchange_client,
                                order.exchange_order_id, 
                                order.symbol
                            )

                            if result:
                                # Update order status in database
                                order.status = 'canceled'
                                order.save()
                                cancelled_orders.append(order.id)

                                # Log the cancellation
                                BotLog.objects.create(
                                    bot_configuration=bot_config,
                                    level='INFO',
                                    message=f"Order {order.exchange_order_id} cancelled successfully"
                                )
                            else:
                                BotLog.objects.create(
                                    bot_configuration=bot_config,
                                    level='ERROR',
                                    message=f"Failed to cancel order {order.exchange_order_id}"
                                )
                        except Exception as e:
                            logger.error(f"Error cancelling order {order.exchange_order_id}: {str(e)}")
                            BotLog.objects.create(
                                bot_configuration=bot_config,
                                level='ERROR',
                                message=f"Error cancelling order {order.exchange_order_id}: {str(e)}"
                            )

                    return Response({
                        "message": f"Cancelled {len(cancelled_orders)} orders",
                        "cancelled_orders": cancelled_orders,
                        "exchange": bot_config.exchange.name
                    })

                elif order_id:
                    # Cancel specific order
                    try:
                        order = TradeOrder.objects.get(
                            bot_configuration=bot_config,
                            exchange_order_id=order_id,
                            status='open'
                        )

                        # Call the exchange API to cancel the order
                        try:
                            # Use the helper function to run async code with proper client cleanup
                            result = run_async_with_cleanup(
                                self._cancel_order_async,
                                exchange_client,
                                order.exchange_order_id, 
                                order.symbol
                            )

                            if result:
                                # Update order status in database
                                order.status = 'canceled'
                                order.save()

                                # Log the cancellation
                                BotLog.objects.create(
                                    bot_configuration=bot_config,
                                    level='INFO',
                                    message=f"Order {order.exchange_order_id} cancelled successfully"
                                )

                                return Response({
                                    "message": f"Order {order_id} cancelled successfully",
                                    "exchange": bot_config.exchange.name
                                })
                            else:
                                return Response({
                                    "error": f"Failed to cancel order {order_id}",
                                    "exchange": bot_config.exchange.name
                                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                        except Exception as e:
                            return Response({
                                "error": f"Error cancelling order: {str(e)}",
                                "exchange": bot_config.exchange.name
                            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

                    except TradeOrder.DoesNotExist:
                        return Response(
                            {"error": f"Open order with ID {order_id} not found for bot {bot_id}"},
                            status=status.HTTP_404_NOT_FOUND
                        )

            except BotConfiguration.DoesNotExist:
                return Response(
                    {"error": f"Bot configuration with ID {bot_id} not found or does not belong to you"},
                    status=status.HTTP_404_NOT_FOUND
                )
            except Exception as e:
                logger.error(f"Error cancelling order(s): {str(e)}")
                return Response(
                    {"error": f"Error cancelling order(s): {str(e)}"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)