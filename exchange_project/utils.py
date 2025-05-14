from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import ValidationError 
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if isinstance(exc, (InvalidToken, TokenError,ValidationError)) and response is not None:
        detail = exc.detail

        if isinstance(detail, dict):
            first_key = next(iter(detail))
            first_error = detail[first_key]
            message = first_error[0] if isinstance(first_error, list) else first_error
        elif isinstance(detail, list):
            message = detail[0]
        else:
            message = str(detail)

        return Response({'error': message}, status=status.HTTP_400_BAD_REQUEST)

    return response


