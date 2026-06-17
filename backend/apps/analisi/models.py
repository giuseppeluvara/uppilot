from django.db import models

from apps.casi.models import Documento, Lavoro


class Richiesta(models.Model):
    """Una domanda/richiesta di una parte, con gli esiti dell'analisi (§169).

    Coerente con il principio §1: gli esiti oggettivi sono testo; i punti
    discrezionali vivono in `quesiti_aperti` come interrogativi all'utente.
    """

    class Parte(models.TextChoices):
        ATTORE = "attore", "Attore"
        CONVENUTO = "convenuto", "Convenuto/ricorrente"

    class Stato(models.TextChoices):
        DA_ANALIZZARE = "da_analizzare", "Da analizzare"
        ANALIZZATA = "analizzata", "Analizzata"
        APPROFONDITA = "approfondita", "Approfondita (in diritto)"

    lavoro = models.ForeignKey(
        Lavoro, on_delete=models.CASCADE, related_name="richieste"
    )
    parte_richiedente = models.CharField(max_length=16, choices=Parte.choices)
    testo = models.TextField()
    stato = models.CharField(
        max_length=16, choices=Stato.choices, default=Stato.DA_ANALIZZARE
    )

    # Esiti dell'analisi (oggettivi -> testo strutturato)
    onere_probatorio = models.TextField(blank=True)
    allegati_collegati = models.ManyToManyField(
        Documento, blank=True, related_name="richieste"
    )
    non_contestazioni = models.JSONField(default=list, blank=True)

    # Punti discrezionali posti come interrogativi all'umano (§23)
    quesiti_aperti = models.JSONField(default=list, blank=True)

    # Motivazione "in diritto" redatta dall'operatore (il discrezionale, §1).
    motivazione = models.TextField(blank=True)

    ordine = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["ordine", "id"]

    def __str__(self) -> str:
        return f"Richiesta {self.ordine} ({self.get_parte_richiedente_display()})"


class SpuntoRicerca(models.Model):
    """Spunto di approfondimento giuridico (§6).

    NON è una citazione autoritativa: è un suggerimento che l'utente valuta e
    integra a sua discrezione. La query è quella (pseudonimizzata) uscita verso
    l'esterno (§134).
    """

    class Origine(models.TextChoices):
        WEB = "web", "Ricerca web"
        MANUALE = "manuale", "Inserito manualmente"

    lavoro = models.ForeignKey(
        Lavoro, on_delete=models.CASCADE, related_name="spunti"
    )
    query_pseudonimizzata = models.CharField(max_length=512, blank=True)
    argomento = models.CharField(max_length=255, blank=True)
    sintesi = models.TextField()
    suggerimento = models.TextField(blank=True)
    fonte = models.CharField(max_length=1000, blank=True)
    origine = models.CharField(max_length=16, choices=Origine.choices, default=Origine.WEB)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return self.argomento or self.query_pseudonimizzata


class Bozza(models.Model):
    """La bozza generata: sezione 'in fatto' + contenuto per-richiesta (§170)."""

    lavoro = models.OneToOneField(
        Lavoro, on_delete=models.CASCADE, related_name="bozza"
    )
    in_fatto = models.TextField(blank=True)
    contenuto_per_richiesta = models.JSONField(default=dict, blank=True)
    # P.Q.M. compilato dall'operatore (§7).
    pqm = models.TextField(blank=True)
    versione = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Bozza di {self.lavoro.titolo} (v{self.versione})"
