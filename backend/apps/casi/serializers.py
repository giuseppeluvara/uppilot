from rest_framework import serializers

from .models import Documento, Lavoro, SezioneDocumenti


class DocumentoSerializer(serializers.ModelSerializer):
    utilizzabile = serializers.BooleanField(read_only=True)

    class Meta:
        model = Documento
        fields = [
            "id",
            "file",
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
            "created_at",
        ]
        read_only_fields = fields


class DocumentoUploadSerializer(serializers.ModelSerializer):
    """Upload di un file in una sezione. L'estrazione parte in modo asincrono."""

    class Meta:
        model = Documento
        fields = ["id", "sezione", "file"]

    def validate_sezione(self, sezione: SezioneDocumenti) -> SezioneDocumenti:
        # La sezione deve appartenere a un lavoro dell'utente autenticato.
        utente = self.context["request"].user
        if sezione.lavoro.utente_id != utente.id:
            raise serializers.ValidationError("Sezione non accessibile.")
        return sezione


class SezioneDocumentiSerializer(serializers.ModelSerializer):
    documenti = DocumentoSerializer(many=True, read_only=True)

    class Meta:
        model = SezioneDocumenti
        fields = ["id", "tipo", "documenti"]


class LavoroSerializer(serializers.ModelSerializer):
    sezioni = SezioneDocumentiSerializer(many=True, read_only=True)

    class Meta:
        model = Lavoro
        fields = [
            "id",
            "titolo",
            "stato",
            "analisi_stato",
            "analisi_errore",
            "approfondimento_stato",
            "approfondimento_errore",
            "ricerca_stato",
            "ricerca_errore",
            "sezioni",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "stato",
            "analisi_stato",
            "analisi_errore",
            "approfondimento_stato",
            "approfondimento_errore",
            "ricerca_stato",
            "ricerca_errore",
            "sezioni",
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
