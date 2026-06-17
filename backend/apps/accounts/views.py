from django.contrib.auth import authenticate, login, logout
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import UtenteSerializer


@method_decorator(ensure_csrf_cookie, name="get")
class CsrfView(APIView):
    """Imposta il cookie csrftoken per la SPA."""

    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"detail": "ok"})


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        utente = authenticate(
            username=request.data.get("username"),
            password=request.data.get("password"),
        )
        if utente is None:
            return Response(
                {"detail": "Credenziali non valide."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        login(request, utente)
        return Response(UtenteSerializer(utente).data)


class LogoutView(APIView):
    def post(self, request):
        logout(request)
        return Response({"detail": "ok"})


class MeView(APIView):
    """Utente corrente; 403 se non autenticato (usato dalla SPA all'avvio)."""

    def get(self, request):
        return Response(UtenteSerializer(request.user).data)
