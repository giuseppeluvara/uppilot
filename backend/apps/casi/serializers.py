from django.conf import settings
from rest_framework import serializers

from .models import Documento, Lavoro, SezioneDocumenti
from .privacy import privacy_report


class DocumentoSerializer(serializers.ModelSerializer):
    utilizzabile = serializers.BooleanField(read_only=True)
    privacy_report = serializers.SerializerMethodField()
    # URL RELATIVO (/media/...) anziché assoluto: l'assoluto incorporerebbe
    # l'hostname interno del container (backend:8000), non raggiungibile dal
    # browser. Relativo, l'anteprima resta nell'origine della SPA e passa dal proxy.
    file = serializers.SerializerMethodField()

    def get_file(self, obj):
        return obj.file.url if obj.file else None

    def get_privacy_report(self, obj):
        return privacy_report(obj.testo_pseudonimizzato or "", obj.mappa_entita or {})

    class Meta:
        model = Documento
        fields = [
            "id",
            "file",
            "nome_logico",
            "ordine",
            "tipo_rilevato",
            "stato_estrazione",
            "errore_estrazione",
            "metodo_estrazione",
            "ocr_confidenza",
            "flag_bassa_confidenza",
            "passaggi_incerti",
            # Privacy: campi per la review dell'anonimizzazione (§122)
            "stato_anonimizzazione",
            "errore_anonimizzazione",
            "pseudonimizzato",
            "testo_pseudonimizzato",
            "mappa_entita",
            "stato_accettazione",
            "utilizzabile",
            "privacy_report",
            "created_at",
        ]
        read_only_fields = fields


class DocumentoUploadSerializer(serializers.ModelSerializer):
    """Upload di un file in una sezione. L'estrazione parte in modo asincrono."""

    ESTENSIONI_AMMESSE = (
        ".pdf",
        ".png",
        ".jpg",
        ".jpeg",
        ".tiff",
        ".tif",
        ".bmp",
        ".webp",
    )

    class Meta:
        model = Documento
        fields = ["id", "sezione", "file"]

    def validate_sezione(self, sezione: SezioneDocumenti) -> SezioneDocumenti:
        # La sezione deve appartenere a un lavoro dell'utente autenticato.
        utente = self.context["request"].user
        if sezione.lavoro.utente_id != utente.id:
            raise serializers.ValidationError("Sezione non accessibile.")
        return sezione

    def validate_file(self, file):
        if file.size > settings.UPPILOT_MAX_UPLOAD_BYTES:
            limite = settings.UPPILOT_MAX_UPLOAD_BYTES // (1024 * 1024)
            raise serializers.ValidationError(f"File troppo grande. Limite: {limite} MB.")
        if not file.name.lower().endswith(self.ESTENSIONI_AMMESSE):
            raise serializers.ValidationError(
                "Tipo di file non supportato. Usa PDF o immagini."
            )
        return file


class SezioneDocumentiSerializer(serializers.ModelSerializer):
    documenti = DocumentoSerializer(many=True, read_only=True)

    class Meta:
        model = SezioneDocumenti
        fields = ["id", "tipo", "documenti"]


class LavoroSerializer(serializers.ModelSerializer):
    sezioni = SezioneDocumentiSerializer(many=True, read_only=True)
    checklist = serializers.SerializerMethodField()
    privacy_report = serializers.SerializerMethodField()
    documenti_statistiche = serializers.SerializerMethodField()

    def _documenti(self, obj):
        return list(
            Documento.objects.filter(sezione__lavoro=obj).select_related("sezione")
        )

    def get_documenti_statistiche(self, obj):
        documenti = self._documenti(obj)
        in_lavorazione = [
            d
            for d in documenti
            if d.stato_estrazione in {
                Documento.StatoEstrazione.IN_ATTESA,
                Documento.StatoEstrazione.IN_CORSO,
            }
            or d.stato_anonimizzazione == Documento.StatoAnonimizzazione.IN_CORSO
        ]
        da_verificare = [
            d
            for d in documenti
            if d.pseudonimizzato
            and d.stato_accettazione == Documento.StatoAccettazione.DA_VERIFICARE
        ]
        return {
            "totali": len(documenti),
            "in_lavorazione": len(in_lavorazione),
            "pseudonimizzati": sum(1 for d in documenti if d.pseudonimizzato),
            "accettati": sum(1 for d in documenti if d.utilizzabile),
            "da_verificare": len(da_verificare),
        }

    def get_checklist(self, obj):
        from apps.analisi.models import Bozza, Richiesta

        stats = self.get_documenti_statistiche(obj)
        richieste_totali = obj.richieste.count()
        richieste_approfondite = obj.richieste.filter(
            stato=Richiesta.Stato.APPROFONDITA
        ).count()
        motivazioni = obj.richieste.exclude(motivazione="").count()
        bozza = Bozza.objects.filter(lavoro=obj).first()
        return {
            "documenti_caricati": stats["totali"],
            "documenti_pronti": stats["accettati"],
            "documenti_da_verificare": stats["da_verificare"],
            "documenti_in_lavorazione": stats["in_lavorazione"],
            "analisi_pronta": stats["accettati"] > 0 and stats["in_lavorazione"] == 0,
            "analisi_parziale": stats["accettati"] > 0 and stats["da_verificare"] > 0,
            "analisi_completata": obj.analisi_stato == Lavoro.StatoAnalisi.COMPLETATA,
            "richieste_totali": richieste_totali,
            "richieste_approfondite": richieste_approfondite,
            "motivazioni_redatte": motivazioni,
            "pqm_compilato": bool(bozza and bozza.pqm.strip()),
        }

    def get_privacy_report(self, obj):
        from apps.analisi.models import Bozza

        testi = [d.testo_pseudonimizzato for d in self._documenti(obj)]
        bozza = Bozza.objects.filter(lavoro=obj).first()
        if bozza:
            testi.extend([bozza.in_fatto, bozza.pqm])
        for r in obj.richieste.all():
            testi.extend(
                [
                    r.testo,
                    r.onere_probatorio,
                    r.motivazione,
                    "\n".join(r.non_contestazioni or []),
                    "\n".join(r.quesiti_aperti or []),
                ]
            )
        return privacy_report(testi, obj.mappa_entita or {}, extra_values=[obj.titolo])

    class Meta:
        model = Lavoro
        fields = [
            "id",
            "titolo",
            "stato",
            "analisi_stato",
            "analisi_errore",
            "analisi_progresso",
            "approfondimento_stato",
            "approfondimento_errore",
            "approfondimento_progresso",
            "ricerca_stato",
            "ricerca_errore",
            "ricerca_progresso",
            "modello_testo",
            "assegnato_a",
            "revisore",
            "stato_revisione",
            "sezioni",
            "documenti_statistiche",
            "checklist",
            "privacy_report",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "stato",
            "analisi_stato",
            "analisi_errore",
            "analisi_progresso",
            "approfondimento_stato",
            "approfondimento_errore",
            "approfondimento_progresso",
            "ricerca_stato",
            "ricerca_errore",
            "ricerca_progresso",
            "sezioni",
            "documenti_statistiche",
            "checklist",
            "privacy_report",
            "created_at",
            "updated_at",
        ]

    def create(self, validated_data):
        validated_data["utente"] = self.context["request"].user
        lavoro = super().create(validated_data)
        # Crea automaticamente le tre sezioni di upload (§102).
        SezioneDocumenti.objects.bulk_create(
            SezioneDocumenti(lavoro=lavoro, tipo=tipo)
            for tipo in SezioneDocumenti.Tipo.values
        )
        return lavoro
