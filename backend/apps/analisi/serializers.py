import re

from rest_framework import serializers
from urllib.parse import urlparse

from .models import (
    Bozza,
    CommentoEditor,
    EventoDecisionale,
    FattoProcessuale,
    Richiesta,
    SpuntoRicerca,
)
from .services import documenti_utilizzabili, traccia_fonti_richiesta


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


def _tipo_fonte_giuridica(spunto: SpuntoRicerca) -> str:
    testo = f"{spunto.argomento} {spunto.sintesi} {spunto.fonte}".casefold()
    if any(x in testo for x in ("normattiva", "gazzettaufficiale", "art.", "codice", "d.lgs", "legge")):
        return "norma"
    if any(x in testo for x in ("cassazione", "tribunale", "corte", "sentenza", "ordinanza")):
        return "giurisprudenza"
    if any(x in testo for x in ("massima", "principio di diritto")):
        return "massima"
    if any(x in testo for x in ("rivista", "commento", "dottrina", "autore")):
        return "dottrina"
    if spunto.origine == SpuntoRicerca.Origine.MANUALE:
        return "materiale manuale"
    return "fonte web"


def _fonti_tracciate_richiesta(obj: Richiesta):
    if obj.fonti_tracciate:
        return obj.fonti_tracciate
    documenti = list(documenti_utilizzabili(obj.lavoro))
    allegati = list(obj.allegati_collegati.values_list("id", flat=True))
    return traccia_fonti_richiesta(
        obj.testo,
        obj.parte_richiedente,
        obj.tipo,
        documenti,
        allegati,
    )


def _parte_opposta(parte: str) -> str:
    return Richiesta.Parte.CONVENUTO if parte == Richiesta.Parte.ATTORE else Richiesta.Parte.ATTORE


class RichiestaSerializer(serializers.ModelSerializer):
    allegati_collegati = serializers.PrimaryKeyRelatedField(many=True, read_only=True)
    avvisi = serializers.SerializerMethodField()
    fonti_tracciate = serializers.SerializerMethodField()

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

    def get_fonti_tracciate(self, obj):
        return _fonti_tracciate_richiesta(obj)

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
            "fonti_tracciate",
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
            "fonti_tracciate",
        ]


class FattoProcessualeSerializer(serializers.ModelSerializer):
    richiesta_id = serializers.IntegerField(source="richiesta.id", read_only=True)
    richiesta_testo = serializers.CharField(source="richiesta.testo", read_only=True)
    parte_richiedente = serializers.CharField(source="richiesta.parte_richiedente", read_only=True)
    tipo = serializers.CharField(source="richiesta.tipo", read_only=True)
    onere_probatorio = serializers.CharField(source="richiesta.onere_probatorio", read_only=True)
    motivazione = serializers.CharField(source="richiesta.motivazione", read_only=True)
    quesiti_aperti = serializers.JSONField(source="richiesta.quesiti_aperti", read_only=True)
    allegati_collegati = serializers.SerializerMethodField()
    fonti = serializers.SerializerMethodField()
    fonti_count = serializers.SerializerMethodField()
    score_massimo = serializers.SerializerMethodField()
    affidabilita_massima = serializers.SerializerMethodField()
    lacune = serializers.SerializerMethodField()
    stato_suggerito = serializers.SerializerMethodField()
    stato_suggerito_label = serializers.SerializerMethodField()
    stato_prova_label = serializers.SerializerMethodField()
    funzione_prevalente_label = serializers.SerializerMethodField()
    stato_contraddittorio_label = serializers.SerializerMethodField()
    stato_contraddittorio_suggerito = serializers.SerializerMethodField()
    stato_contraddittorio_suggerito_label = serializers.SerializerMethodField()
    fonti_attore = serializers.SerializerMethodField()
    fonti_convenuto = serializers.SerializerMethodField()
    fonti_generiche = serializers.SerializerMethodField()
    fonti_supporto = serializers.SerializerMethodField()
    fonti_controparte = serializers.SerializerMethodField()
    contraddittorio_lacune = serializers.SerializerMethodField()

    def _fonti(self, obj) -> list[dict]:
        return [
            f
            for f in _fonti_tracciate_richiesta(obj.richiesta)
            if isinstance(f, dict)
        ]

    def _score_massimo(self, obj) -> float:
        scores = [float(f.get("score") or 0) for f in self._fonti(obj)]
        return max(scores) if scores else 0.0

    def _fonti_sezione(self, obj, sezione: str) -> list[dict]:
        return [f for f in self._fonti(obj) if f.get("sezione") == sezione]

    def _fonti_supporto(self, obj) -> list[dict]:
        parte = obj.richiesta.parte_richiedente
        return [
            f
            for f in self._fonti(obj)
            if f.get("sezione") in {parte, "generici"}
        ]

    def _fonti_controparte(self, obj) -> list[dict]:
        return self._fonti_sezione(obj, _parte_opposta(obj.richiesta.parte_richiedente))

    def _stato_contraddittorio_suggerito(self, obj):
        supporto = self._fonti_supporto(obj)
        controparte = self._fonti_controparte(obj)
        non_contestazioni = obj.richiesta.non_contestazioni or []
        if supporto and controparte:
            return FattoProcessuale.StatoContraddittorio.CONTESTATO
        if controparte and not supporto:
            return FattoProcessuale.StatoContraddittorio.CONTROPROVATO
        if supporto and non_contestazioni:
            return FattoProcessuale.StatoContraddittorio.NON_CONTESTATO
        if supporto:
            return FattoProcessuale.StatoContraddittorio.SILENTE
        return FattoProcessuale.StatoContraddittorio.DA_DECIDERE

    def get_allegati_collegati(self, obj):
        return list(obj.richiesta.allegati_collegati.values_list("id", flat=True))

    def get_fonti(self, obj):
        return self._fonti(obj)

    def get_fonti_count(self, obj):
        return len(self._fonti(obj))

    def get_score_massimo(self, obj):
        return round(self._score_massimo(obj), 3)

    def get_affidabilita_massima(self, obj):
        priorita = {"alta": 3, "media": 2, "bassa": 1}
        fonti = self._fonti(obj)
        if not fonti:
            return "assente"
        return max(
            (str(f.get("affidabilita") or "bassa") for f in fonti),
            key=lambda v: priorita.get(v, 0),
        )

    def get_lacune(self, obj):
        richiesta = obj.richiesta
        fonti = self._fonti(obj)
        score = self._score_massimo(obj)
        lacune = []
        if not (richiesta.onere_probatorio or "").strip():
            lacune.append("Onere probatorio non ancora esplicitato.")
        if not fonti:
            lacune.append("Nessuna fonte interna agganciata alla richiesta.")
        elif score < 0.45:
            lacune.append("Fonti presenti ma con pertinenza debole: verifica manuale necessaria.")
        if richiesta.quesiti_aperti:
            lacune.append(f"{len(richiesta.quesiti_aperti)} quesiti aperti da decidere.")
        lacune.extend(self.get_contraddittorio_lacune(obj))
        if not (richiesta.motivazione or "").strip():
            lacune.append("Motivazione in diritto non ancora consolidata.")
        return lacune

    def get_stato_suggerito(self, obj):
        fonti = self._fonti(obj)
        score = self._score_massimo(obj)
        if not fonti or score < 0.45:
            return FattoProcessuale.StatoProva.INSUFFICIENTE
        if obj.richiesta.quesiti_aperti:
            return FattoProcessuale.StatoProva.DA_DECIDERE
        return FattoProcessuale.StatoProva.DA_VERIFICARE

    def get_stato_suggerito_label(self, obj):
        return FattoProcessuale.StatoProva(self.get_stato_suggerito(obj)).label

    def get_stato_prova_label(self, obj):
        return obj.get_stato_prova_display()

    def get_funzione_prevalente_label(self, obj):
        return obj.get_funzione_prevalente_display()

    def get_stato_contraddittorio_label(self, obj):
        return obj.get_stato_contraddittorio_display()

    def get_stato_contraddittorio_suggerito(self, obj):
        return self._stato_contraddittorio_suggerito(obj)

    def get_stato_contraddittorio_suggerito_label(self, obj):
        return FattoProcessuale.StatoContraddittorio(
            self._stato_contraddittorio_suggerito(obj)
        ).label

    def get_fonti_attore(self, obj):
        return self._fonti_sezione(obj, Richiesta.Parte.ATTORE)

    def get_fonti_convenuto(self, obj):
        return self._fonti_sezione(obj, Richiesta.Parte.CONVENUTO)

    def get_fonti_generiche(self, obj):
        return self._fonti_sezione(obj, "generici")

    def get_fonti_supporto(self, obj):
        return self._fonti_supporto(obj)

    def get_fonti_controparte(self, obj):
        return self._fonti_controparte(obj)

    def get_contraddittorio_lacune(self, obj):
        supporto = self._fonti_supporto(obj)
        controparte = self._fonti_controparte(obj)
        stato = self._stato_contraddittorio_suggerito(obj)
        lacune = []
        if supporto and not controparte and not obj.richiesta.non_contestazioni:
            lacune.append("Non risultano fonti della controparte su questa richiesta.")
        if stato == FattoProcessuale.StatoContraddittorio.CONTROPROVATO:
            lacune.append("Le fonti agganciate provengono solo dalla controparte.")
        if stato == FattoProcessuale.StatoContraddittorio.DA_DECIDERE and not supporto:
            lacune.append("Contraddittorio non leggibile: mancano fonti di supporto.")
        return lacune

    class Meta:
        model = FattoProcessuale
        fields = [
            "id",
            "richiesta_id",
            "ordine",
            "testo",
            "parte_richiedente",
            "tipo",
            "richiesta_testo",
            "onere_probatorio",
            "motivazione",
            "allegati_collegati",
            "quesiti_aperti",
            "fonti",
            "fonti_count",
            "score_massimo",
            "affidabilita_massima",
            "lacune",
            "stato_prova",
            "stato_prova_label",
            "stato_suggerito",
            "stato_suggerito_label",
            "funzione_prevalente",
            "funzione_prevalente_label",
            "stato_contraddittorio",
            "stato_contraddittorio_label",
            "stato_contraddittorio_suggerito",
            "stato_contraddittorio_suggerito_label",
            "fonti_attore",
            "fonti_convenuto",
            "fonti_generiche",
            "fonti_supporto",
            "fonti_controparte",
            "contraddittorio_lacune",
            "note_operatore",
            "note_contraddittorio",
            "quesito_umano",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "richiesta_id",
            "ordine",
            "parte_richiedente",
            "tipo",
            "richiesta_testo",
            "onere_probatorio",
            "motivazione",
            "allegati_collegati",
            "quesiti_aperti",
            "fonti",
            "fonti_count",
            "score_massimo",
            "affidabilita_massima",
            "lacune",
            "stato_prova_label",
            "stato_suggerito",
            "stato_suggerito_label",
            "funzione_prevalente_label",
            "stato_contraddittorio_label",
            "stato_contraddittorio_suggerito",
            "stato_contraddittorio_suggerito_label",
            "fonti_attore",
            "fonti_convenuto",
            "fonti_generiche",
            "fonti_supporto",
            "fonti_controparte",
            "contraddittorio_lacune",
            "created_at",
            "updated_at",
        ]


class EventoDecisionaleSerializer(serializers.ModelSerializer):
    tipo_label = serializers.CharField(source="get_tipo_display", read_only=True)
    utente_username = serializers.CharField(source="utente.username", read_only=True, default="")

    class Meta:
        model = EventoDecisionale
        fields = [
            "id",
            "lavoro",
            "richiesta",
            "fatto",
            "utente",
            "utente_username",
            "tipo",
            "tipo_label",
            "campo",
            "descrizione",
            "valore_precedente",
            "valore_nuovo",
            "created_at",
        ]
        read_only_fields = fields


class CommentoEditorSerializer(serializers.ModelSerializer):
    utente_username = serializers.CharField(source="utente.username", read_only=True, default="")
    sezione_label = serializers.CharField(source="get_sezione_display", read_only=True)

    class Meta:
        model = CommentoEditor
        fields = [
            "id",
            "lavoro",
            "utente",
            "utente_username",
            "sezione",
            "sezione_label",
            "riferimento_id",
            "testo",
            "risolto",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "lavoro",
            "utente",
            "utente_username",
            "sezione_label",
            "created_at",
            "updated_at",
        ]


class BozzaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bozza
        fields = ["lavoro", "in_fatto", "pqm", "contenuto_per_richiesta", "versione", "updated_at"]


class SpuntoRicercaSerializer(serializers.ModelSerializer):
    fonte_affidabilita = serializers.SerializerMethodField()
    fonte_label = serializers.SerializerMethodField()
    tipo_fonte = serializers.SerializerMethodField()
    motivazione_affidabilita = serializers.SerializerMethodField()

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

    def get_tipo_fonte(self, obj):
        return _tipo_fonte_giuridica(obj)

    def get_motivazione_affidabilita(self, obj):
        if obj.stato_fonte == SpuntoRicerca.StatoFonte.INSUFFICIENTE:
            return "La ricerca non ha restituito fonti sufficientemente verificabili."
        livello = self.get_fonte_affidabilita(obj)
        if livello == "alta":
            return "Fonte istituzionale o primaria: usare comunque previa verifica del testo vigente."
        if livello == "media":
            return "Fonte utile per orientarsi, da confrontare con norma o provvedimento originale."
        if livello == "bassa":
            return "Fonte potenzialmente fragile: non citarla senza riscontro autonomo."
        return "Fonte non indicata: trattala come appunto interno, non come citazione."

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
            "tipo_fonte",
            "motivazione_affidabilita",
            "origine",
            "created_at",
        ]
