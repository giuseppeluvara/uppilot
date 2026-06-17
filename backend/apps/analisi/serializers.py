from rest_framework import serializers

from .models import Bozza, Richiesta, SpuntoRicerca


class RichiestaSerializer(serializers.ModelSerializer):
    allegati_collegati = serializers.PrimaryKeyRelatedField(many=True, read_only=True)

    class Meta:
        model = Richiesta
        fields = [
            "id",
            "ordine",
            "parte_richiedente",
            "testo",
            "stato",
            "onere_probatorio",
            "allegati_collegati",
            "non_contestazioni",
            "quesiti_aperti",
            "motivazione",
        ]
        read_only_fields = [
            "ordine",
            "parte_richiedente",
            "testo",
            "stato",
            "onere_probatorio",
            "allegati_collegati",
            "non_contestazioni",
            "quesiti_aperti",
        ]


class BozzaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bozza
        fields = ["lavoro", "in_fatto", "pqm", "contenuto_per_richiesta", "versione", "updated_at"]


class SpuntoRicercaSerializer(serializers.ModelSerializer):
    class Meta:
        model = SpuntoRicerca
        fields = [
            "id",
            "argomento",
            "query_pseudonimizzata",
            "sintesi",
            "suggerimento",
            "fonte",
            "origine",
            "created_at",
        ]
