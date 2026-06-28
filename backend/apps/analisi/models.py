from django.conf import settings
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

    class Tipo(models.TextChoices):
        DOMANDA = "domanda", "Domanda"
        DIFESA_ECCEZIONE = "difesa_eccezione", "Difesa/eccezione"
        RICONVENZIONALE = "riconvenzionale", "Domanda riconvenzionale"
        ISTRUTTORIA = "istruttoria", "Istanza istruttoria"
        ALTRO = "altro", "Altro"

    lavoro = models.ForeignKey(
        Lavoro, on_delete=models.CASCADE, related_name="richieste"
    )
    parte_richiedente = models.CharField(max_length=16, choices=Parte.choices)
    testo = models.TextField()
    tipo = models.CharField(max_length=32, choices=Tipo.choices, default=Tipo.DOMANDA)
    confidence = models.FloatField(default=0.65)
    flags = models.JSONField(default=list, blank=True)
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

    # Fonti interne tracciate deterministicamente sugli atti pseudonimizzati.
    fonti_tracciate = models.JSONField(default=list, blank=True)

    ordine = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["ordine", "id"]

    def __str__(self) -> str:
        return f"Richiesta {self.ordine} ({self.get_parte_richiedente_display()})"


class FattoProcessuale(models.Model):
    """Riga della matrice richiesta/prova.

    La matrice rende esplicito il passaggio richiesta -> fatto rilevante ->
    prova/lacuna. Lo stato prova resta una valutazione dell'operatore: gli score
    delle fonti aiutano la verifica ma non decidono automaticamente.
    """

    class StatoProva(models.TextChoices):
        DA_VERIFICARE = "da_verificare", "Da verificare"
        PROVATO = "provato", "Provato"
        NON_PROVATO = "non_provato", "Non provato"
        CONTROVERSO = "controverso", "Controverso"
        INSUFFICIENTE = "insufficiente", "Insufficiente"
        DA_DECIDERE = "da_decidere", "Da decidere"

    class FunzioneFonte(models.TextChoices):
        SUPPORTA = "supporta", "Supporta"
        CONTRADDICE = "contraddice", "Contraddice"
        INTEGRA = "integra", "Integra"
        NEUTRA = "neutra", "Neutra"
        INSUFFICIENTE = "insufficiente", "Insufficiente"
        CONTESTO = "contesto", "Solo contesto"

    class StatoContraddittorio(models.TextChoices):
        PACIFICO = "pacifico", "Pacifico"
        CONTESTATO = "contestato", "Contestato"
        NON_CONTESTATO = "non_contestato", "Non contestato"
        CONTROPROVATO = "controprovato", "Controprovato"
        SILENTE = "silente", "Controparte silente"
        DA_DECIDERE = "da_decidere", "Da decidere"

    richiesta = models.ForeignKey(
        Richiesta, on_delete=models.CASCADE, related_name="fatti_processuali"
    )
    testo = models.TextField()
    stato_prova = models.CharField(
        max_length=24,
        choices=StatoProva.choices,
        default=StatoProva.DA_VERIFICARE,
    )
    funzione_prevalente = models.CharField(
        max_length=24,
        choices=FunzioneFonte.choices,
        default=FunzioneFonte.SUPPORTA,
    )
    stato_contraddittorio = models.CharField(
        max_length=24,
        choices=StatoContraddittorio.choices,
        default=StatoContraddittorio.DA_DECIDERE,
    )
    note_operatore = models.TextField(blank=True)
    note_contraddittorio = models.TextField(blank=True)
    quesito_umano = models.TextField(blank=True)
    ordine = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["richiesta__ordine", "ordine", "id"]

    def __str__(self) -> str:
        return f"Fatto {self.ordine} - richiesta {self.richiesta_id}"


class EventoDecisionale(models.Model):
    """Registro umano/auditabile delle scelte operative sulla bozza.

    Non e' un log tecnico: conserva le modifiche che incidono su prova,
    contraddittorio, motivazione, export e controlli di coerenza.
    """

    class Tipo(models.TextChoices):
        MATRICE_AGGIORNATA = "matrice_aggiornata", "Matrice aggiornata"
        MOTIVAZIONE_AGGIORNATA = "motivazione_aggiornata", "Motivazione aggiornata"
        BOZZA_AGGIORNATA = "bozza_aggiornata", "Bozza aggiornata"
        COMMENTO_EDITOR = "commento_editor", "Commento editor"
        FONTE_AGGIORNATA = "fonte_aggiornata", "Fonte aggiornata"
        AZIONE_LACUNA = "azione_lacuna", "Azione su lacuna"
        AUDIT_ESPORTATO = "audit_esportato", "Audit esportato"
        RED_TEAM_ESEGUITO = "red_team_eseguito", "Red team eseguito"

    lavoro = models.ForeignKey(
        Lavoro, on_delete=models.CASCADE, related_name="eventi_decisionali"
    )
    utente = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="eventi_decisionali",
    )
    richiesta = models.ForeignKey(
        Richiesta,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="eventi_decisionali",
    )
    fatto = models.ForeignKey(
        FattoProcessuale,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="eventi_decisionali",
    )
    tipo = models.CharField(max_length=32, choices=Tipo.choices)
    campo = models.CharField(max_length=255, blank=True)
    descrizione = models.TextField(blank=True)
    valore_precedente = models.JSONField(default=dict, blank=True)
    valore_nuovo = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"{self.get_tipo_display()} - lavoro {self.lavoro_id}"


class CommentoEditor(models.Model):
    """Commento operativo sulla bozza o su una sezione redazionale."""

    class Sezione(models.TextChoices):
        IN_FATTO = "in_fatto", "In fatto"
        IN_DIRITTO = "in_diritto", "In diritto"
        PQM = "pqm", "P.Q.M."
        FONTE = "fonte", "Fonte"
        PRIVACY = "privacy", "Privacy"
        GENERALE = "generale", "Generale"

    lavoro = models.ForeignKey(
        Lavoro, on_delete=models.CASCADE, related_name="commenti_editor"
    )
    utente = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="commenti_editor",
    )
    sezione = models.CharField(
        max_length=24, choices=Sezione.choices, default=Sezione.GENERALE
    )
    riferimento_id = models.PositiveIntegerField(null=True, blank=True)
    testo = models.TextField()
    risolto = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"Commento {self.sezione} - lavoro {self.lavoro_id}"


class SpuntoRicerca(models.Model):
    """Spunto di approfondimento giuridico (§6).

    NON è una citazione autoritativa: è un suggerimento che l'utente valuta e
    integra a sua discrezione. La query è quella (pseudonimizzata) uscita verso
    l'esterno (§134).
    """

    class Origine(models.TextChoices):
        WEB = "web", "Ricerca web"
        MANUALE = "manuale", "Inserito manualmente"

    class StatoFonte(models.TextChoices):
        OK = "ok", "Fonte disponibile"
        INSUFFICIENTE = "insufficiente", "Ricerca insufficiente"

    lavoro = models.ForeignKey(
        Lavoro, on_delete=models.CASCADE, related_name="spunti"
    )
    query_pseudonimizzata = models.CharField(max_length=512, blank=True)
    argomento = models.CharField(max_length=255, blank=True)
    sintesi = models.TextField()
    suggerimento = models.TextField(blank=True)
    fonte = models.CharField(max_length=1000, blank=True)
    stato_fonte = models.CharField(
        max_length=16, choices=StatoFonte.choices, default=StatoFonte.OK
    )
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
