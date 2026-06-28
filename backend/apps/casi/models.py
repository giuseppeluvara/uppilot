from django.conf import settings
from django.db import models

from .states import StatoLavoro, TransizioneNonValida, puo_transizionare


class Lavoro(models.Model):
    """Il caso/fascicolo di lavoro storicizzato (§166)."""

    class StatoAnalisi(models.TextChoices):
        IN_ATTESA = "in_attesa", "In attesa"
        IN_CORSO = "in_corso", "In corso"
        COMPLETATA = "completata", "Completata"
        ERRORE = "errore", "Errore"

    utente = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="lavori",
    )
    titolo = models.CharField(max_length=255)
    stato = models.CharField(
        max_length=32,
        choices=StatoLavoro.choices,
        default=StatoLavoro.BOZZA_IN_CORSO,
    )
    # Avanzamento dell'analisi LLM (per il feedback alla UI, §82).
    analisi_stato = models.CharField(
        max_length=16,
        choices=StatoAnalisi.choices,
        default=StatoAnalisi.IN_ATTESA,
    )
    analisi_errore = models.TextField(blank=True)
    analisi_progresso = models.JSONField(default=dict, blank=True)
    # ID del task Celery in corso: serve per poterlo revocare (interruzione utente).
    analisi_task_id = models.CharField(max_length=255, blank=True)
    # Avanzamento del ragionamento "in diritto" per richiesta (M2).
    approfondimento_stato = models.CharField(
        max_length=16,
        choices=StatoAnalisi.choices,
        default=StatoAnalisi.IN_ATTESA,
    )
    approfondimento_errore = models.TextField(blank=True)
    approfondimento_progresso = models.JSONField(default=dict, blank=True)
    approfondimento_task_id = models.CharField(max_length=255, blank=True)
    # Avanzamento della ricerca giuridica "spunti" (M2, §6).
    ricerca_stato = models.CharField(
        max_length=16,
        choices=StatoAnalisi.choices,
        default=StatoAnalisi.IN_ATTESA,
    )
    ricerca_errore = models.TextField(blank=True)
    ricerca_progresso = models.JSONField(default=dict, blank=True)
    ricerca_task_id = models.CharField(max_length=255, blank=True)
    # Registro entità a livello di lavoro: placeholder canonico -> valore reale.
    # Garantisce placeholder coerenti tra i documenti e abilita l'export "in chiaro".
    mappa_entita = models.JSONField(default=dict, blank=True)
    # Modello di redazione (facoltativo): sample/template che definisce impostazione
    # (suddivisione in paragrafi) e metodo di scrittura della bozza. Guida l'analisi.
    modello_testo = models.TextField(blank=True)
    assegnato_a = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lavori_assegnati",
    )
    revisore = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lavori_da_revisionare",
    )
    stato_revisione = models.CharField(
        max_length=24,
        choices=[
            ("da_rivedere", "Da rivedere"),
            ("in_revisione", "In revisione"),
            ("validato", "Validato"),
            ("esportato", "Esportato"),
        ],
        default="da_rivedere",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return f"{self.titolo} ({self.get_stato_display()})"

    def transiziona(self, nuovo_stato: str) -> None:
        """Applica una transizione di stato validandola (§45)."""
        if not puo_transizionare(self.stato, nuovo_stato):
            raise TransizioneNonValida(
                f"Transizione non ammessa: {self.stato} -> {nuovo_stato}"
            )
        self.stato = nuovo_stato
        self.save(update_fields=["stato", "updated_at"])


class SezioneDocumenti(models.Model):
    """Le tre sezioni di upload del fascicolo (§102)."""

    class Tipo(models.TextChoices):
        GENERICI = "generici", "Documenti generici"
        ATTORE = "attore", "Fascicolo dell'attore"
        CONVENUTO = "convenuto", "Fascicolo del convenuto/ricorrente"

    lavoro = models.ForeignKey(
        Lavoro, on_delete=models.CASCADE, related_name="sezioni"
    )
    tipo = models.CharField(max_length=16, choices=Tipo.choices)

    class Meta:
        unique_together = ("lavoro", "tipo")

    def __str__(self) -> str:
        return f"{self.lavoro.titolo} — {self.get_tipo_display()}"


class Documento(models.Model):
    """Documento caricato, con esito estrazione, OCR e pseudonimizzazione (§168)."""

    class MetodoEstrazione(models.TextChoices):
        PDF_NATIVO = "pdf_nativo", "PDF nativo (testo selezionabile)"
        GLM_OCR = "glm_ocr", "GLM-OCR (scansione/immagine/manoscritto)"

    class StatoAccettazione(models.TextChoices):
        # Vincolo privacy (§119): solo i documenti accettati entrano nelle fasi successive.
        DA_VERIFICARE = "da_verificare", "Da verificare"
        VERIFICATO = "verificato", "Verificato"
        ACCETTATO_SENZA_VERIFICA = "accettato_senza_verifica", "Accettato senza verifica"

    class StatoEstrazione(models.TextChoices):
        IN_ATTESA = "in_attesa", "In attesa"
        IN_CORSO = "in_corso", "In corso"
        COMPLETATO = "completato", "Completato"
        ERRORE = "errore", "Errore"

    class StatoAnonimizzazione(models.TextChoices):
        IN_ATTESA = "in_attesa", "In attesa"
        IN_CORSO = "in_corso", "In corso"
        COMPLETATA = "completata", "Completata"
        ERRORE = "errore", "Errore"

    sezione = models.ForeignKey(
        SezioneDocumenti, on_delete=models.CASCADE, related_name="documenti"
    )
    file = models.FileField(upload_to="documenti/%Y/%m/")
    nome_logico = models.CharField(max_length=255, blank=True)
    ordine = models.PositiveIntegerField(default=0)
    tipo_rilevato = models.CharField(max_length=64, blank=True)

    # Estrazione testo
    stato_estrazione = models.CharField(
        max_length=16,
        choices=StatoEstrazione.choices,
        default=StatoEstrazione.IN_ATTESA,
    )
    errore_estrazione = models.TextField(blank=True)
    metodo_estrazione = models.CharField(
        max_length=16, choices=MetodoEstrazione.choices, blank=True
    )
    testo_estratto = models.TextField(blank=True)
    ocr_confidenza = models.FloatField(null=True, blank=True)
    flag_bassa_confidenza = models.BooleanField(default=False)
    passaggi_incerti = models.JSONField(default=list, blank=True)

    # Privacy / pseudonimizzazione (§119)
    pseudonimizzato = models.BooleanField(default=False)
    stato_anonimizzazione = models.CharField(
        max_length=16,
        choices=StatoAnonimizzazione.choices,
        default=StatoAnonimizzazione.IN_ATTESA,
    )
    errore_anonimizzazione = models.TextField(blank=True)
    testo_pseudonimizzato = models.TextField(blank=True)
    # Mappa entità del documento con placeholder CANONICI a livello di lavoro.
    mappa_entita = models.JSONField(default=dict, blank=True)
    stato_accettazione = models.CharField(
        max_length=32,
        choices=StatoAccettazione.choices,
        default=StatoAccettazione.DA_VERIFICARE,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.file.name

    @property
    def utilizzabile(self) -> bool:
        """True se il documento può entrare nelle fasi LLM (§123).

        Richiede sia la pseudonimizzazione (vincolo tassativo §119) sia
        l'accettazione esplicita da parte dell'utente.
        """
        return self.pseudonimizzato and self.stato_accettazione in {
            self.StatoAccettazione.VERIFICATO,
            self.StatoAccettazione.ACCETTATO_SENZA_VERIFICA,
        }
