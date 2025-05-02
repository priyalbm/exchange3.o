from rest_framework import status, viewsets
from rest_framework.response import Response
from .models import Plan
from .serializers import PlanSerializer
from .permissions import IsAdminUserOrReadOnly
from rest_framework.pagination import PageNumberPagination
from bot.models import Exchange

class PlanPagination(PageNumberPagination):
    page_size = 10  # Limit to 10 plans per page
    page_size_query_param = 'page_size'  # Allow the client to modify the page size via the URL
    max_page_size = 100  # Optional, set a maximum limit on page size


class PlanViewSet(viewsets.ViewSet):
    permission_classes = [IsAdminUserOrReadOnly]

    def list(self, request):
        """
        Get a list of all plans, with optional filtering by exchange_id and pagination applied.
        """
        exchange_id = request.query_params.get('exchange_id')  # Get exchange_id from query params

        # Filter by exchange_id if provided
        if exchange_id:
            plans = Plan.objects.filter(exchange__id=exchange_id).order_by('id')
        else:
            plans = Plan.objects.all().order_by('id')

        paginator = PlanPagination()
        result_page = paginator.paginate_queryset(plans, request)
        serializer = PlanSerializer(result_page, many=True)
        return paginator.get_paginated_response(serializer.data)


    def retrieve(self, request, pk=None):
        """
        Get a single plan by ID.
        """
        try:
            plan = Plan.objects.get(pk=pk)
        except Plan.DoesNotExist:
            return Response({'error': 'Plan not found'}, status=status.HTTP_404_NOT_FOUND)

        serializer = PlanSerializer(plan)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def create(self, request):
        """
        Create a new plan.
        """
        # Check if plan already exists
        if Plan.objects.filter(name=request.data.get('name')).exists():
            return Response({
                'error': 'Plan already exists. Please use a different plan name.'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Validate exchange field exists in the request
        exchange = request.data.get('exchange')
        if not exchange:
            return Response({
                'error': 'Exchange ID is required for plan creation.'
            }, status=status.HTTP_400_BAD_REQUEST)

        serializer = PlanSerializer(data=request.data)

        if serializer.is_valid():
            serializer.save()  # Save the plan
            return Response(
                {'message': 'Plan created successfully', 'data': serializer.data},
                status=status.HTTP_201_CREATED
            )

        return Response(
            {'error': 'Validation failed', 'errors': serializer.errors},
            status=status.HTTP_400_BAD_REQUEST
        )

    def update(self, request, pk=None):
        """
        Update an existing plan by ID (full update).
        """
        try:
            plan = Plan.objects.get(pk=pk)
        except Plan.DoesNotExist:
            return Response({'error': 'Plan not found'}, status=status.HTTP_404_NOT_FOUND)

        # Validate exchange field exists in the request
        exchange_id = request.data.get('exchange')
        if exchange_id and not Exchange.objects.filter(id=exchange_id).exists():
            return Response({
                'error': 'Invalid Exchange ID provided.'
            }, status=status.HTTP_400_BAD_REQUEST)

        serializer = PlanSerializer(plan, data=request.data, partial=False)
        if serializer.is_valid():
            serializer.save()
            return Response(
                {'message': 'Plan updated successfully', 'data': serializer.data},
                status=status.HTTP_200_OK
            )
        return Response(
            {'error': 'Validation failed', 'errors': serializer.errors},
            status=status.HTTP_400_BAD_REQUEST
        )

    def partial_update(self, request, pk=None):
        """
        Partially update an existing plan by ID.
        """
        try:
            plan = Plan.objects.get(pk=pk)
        except Plan.DoesNotExist:
            return Response({'error': 'Plan not found'}, status=status.HTTP_404_NOT_FOUND)

        # Validate exchange field exists in the request
        exchange_id = request.data.get('exchange')
        if exchange_id and not Exchange.objects.filter(id=exchange_id).exists():
            return Response({
                'error': 'Invalid Exchange ID provided.'
            }, status=status.HTTP_400_BAD_REQUEST)

        serializer = PlanSerializer(plan, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(
                {'message': 'Plan partially updated successfully', 'data': serializer.data},
                status=status.HTTP_200_OK
            )
        return Response(
            {'error': 'Validation failed', 'errors': serializer.errors},
            status=status.HTTP_400_BAD_REQUEST
        )

    def destroy(self, request, pk=None):
        """
        Delete a plan by ID.
        """
        try:
            plan = Plan.objects.get(pk=pk)
        except Plan.DoesNotExist:
            return Response({'error': 'Plan not found'}, status=status.HTTP_404_NOT_FOUND)

        plan.delete()
        return Response(
            {'message': 'Plan successfully deleted'},
            status=status.HTTP_204_NO_CONTENT
        )
