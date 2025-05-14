from rest_framework import permissions

class IsAdminUserOrReadOnly(permissions.BasePermission):
    """
    Custom permission to only allow admins to create, update, or delete plans.
    Non-admin users can only view plans.
    """

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:  # GET, HEAD, OPTIONS
            return True
        # Only allow admin users to create, update or delete
        return request.user and request.user.is_staff
