import re

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
    avvisi = serializers.SerializerMethodField()

    _NUMERO_RE = re.compile(
        r"(?:€\s*)?\b\d{1,3}(?:[.\s]\d{3})+(?:,\d+)?\b|\b\d+/\d{2,4}\b|"
        r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
        re.IGNORECASE,
    )

    def _numeri(self, testo: str) -> set[str]:
        return {
            re.sub(r"\s+", "", m.group(0).replace("€", ""))
            for m in self._NUMERO_RE.finditer(testo or "")
        }

    def get_avvisi(self, obj):
        avvisi = list(obj.flags or [])
        sorgente = self._numeri(obj.testo)
        if sorgente:
            generati = set()
            for testo in [
                obj.onere_probatorio,
                obj.motivazione,
                "\n".join(obj.non_contestazioni or []),
                "\n".join(obj.quesiti_aperti or []),
            ]:
                generati |= self._numeri(testo)
            estranei = sorted(generati - sorgente)
            if estranei:
                avvisi.append(
                    "Numeri/importi da verificare: "
                    + ", ".join(estranei[:5])
                    + " non compaiono nel testo della richiesta."
                )
        return list(dict.fromkeys(avvisi))

    class Meta:
        model = Richiesta
        fields = [
            "id",
            "ordine",
            "parte_richiedente",
            "tipo",
            "testo",
            "confidence",
            "flags",
            "avvisi",
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
            "tipo",
            "testo",
            "confidence",
            "flags",
            "avvisi",
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
        if obj.stato_fonte == SpuntoRicerca.StatoFonte.INSUFFICIENTE:
            return "insufficiente"
        if obj.origine == SpuntoRicerca.Origine.MANUALE and not obj.fonte:
            return "media"
        return _qualifica_fonte(obj.fonte)[0]

    def get_fonte_label(self, obj):
        if obj.stato_fonte == SpuntoRicerca.StatoFonte.INSUFFICIENTE:
            return "Ricerca insufficiente"
        if obj.origine == SpuntoRicerca.Origine.MANUALE and not obj.fonte:
            return "Materiale manuale da verificare"
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
            "stato_fonte",
            "fonte_affidabilita",
            "fonte_label",
            "origine",
            "created_at",
        ]
