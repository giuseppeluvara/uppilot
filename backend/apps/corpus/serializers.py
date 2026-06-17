from rest_framework import serializers

from .models import DocumentoCorpus


class DocumentoCorpusSerializer(serializers.ModelSerializer):
    n_frammenti = serializers.IntegerField(source="frammenti.count", read_only=True)

    class Meta:
        model = DocumentoCorpus
        fields = ["id", "titolo", "fonte", "categoria", "stato", "errore", "n_frammenti", "created_at"]
        read_only_fields = ["stato", "errore", "n_frammenti", "created_at"]
