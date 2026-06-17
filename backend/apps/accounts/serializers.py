from rest_framework import serializers

from .models import Utente


class UtenteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Utente
        fields = ["id", "username", "email", "ruolo"]
