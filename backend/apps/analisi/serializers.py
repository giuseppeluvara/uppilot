from rest_framework import serializers
from urllib.parse import urlparse

from .models import Bozza, Richiesta, SpuntoRicerca


_FONTI_ISTITUZIONALI = (
    "cortedicassazione.it",
    "cortecostituzionale.it",
    "giustizia.it",
    "gazzettaufficiale.it",
    "normattiva.it",
    "eur-lex.europa.eu",
)

_FONTI_EDITORIALI = (
    "altalex.com",
    "brocardi.it",
    "dejure.it",
    "ilcaso.it",
    "ius.giuffrefl.it",
    "onelegale.wolterskluwer.com",
    "pluris-cedam.utetgiuridica.it",
)


def _qualifica_fonte(url: str) -> tuple[str, str]:
    if not url:
        return "non_indicata", "Fonte non indicata"
    host = (urlparse(url).netloc or url).lower().removeprefix("www.")
    if any(host.endswith(d) for d in _FONTI_ISTITUZIONALI):
        return "alta", "Fonte istituzionale"
    if any(host.endswith(d) for d in _FONTI_EDITORIALI):
        return "media", "Banca dati o rivista giuridica"
    if "studio" in host or "blog" in host:
        return "bassa", "Fonte da verificare con cautela"
    return "media", "Fonte da verificare"


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
    fonte_affidabilita = serializers.SerializerMethodField()
    fonte_label = serializers.SerializerMethodField()

    def get_fonte_affidabilita(self, obj):
        return _qualifica_fonte(obj.fonte)[0]

    def get_fonte_label(self, obj):
        return _qualifica_fonte(obj.fonte)[1]

    class Meta:
        model = SpuntoRicerca
        fields = [
            "id",
            "argomento",
            "query_pseudonimizzata",
            "sintesi",
            "suggerimento",
            "fonte",
            "fonte_affidabilita",
            "fonte_label",
            "origine",
            "created_at",
        ]
