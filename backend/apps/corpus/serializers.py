from rest_framework import serializers

from .models import DocumentoCorpus


class DocumentoCorpusSerializer(serializers.ModelSerializer):
    n_frammenti = serializers.IntegerField(source="frammenti.count", read_only=True)
    eliminabile = serializers.SerializerMethodField()

    def get_eliminabile(self, obj):
        request = self.context.get("request")
        if request is None:
            return False
        user = request.user
        return bool(user.is_staff or obj.creato_da_id == user.id)

    class Meta:
        model = DocumentoCorpus
        fields = [
            "id",
            "titolo",
            "fonte",
            "categoria",
            "stato",
            "errore",
            "n_frammenti",
            "eliminabile",
            "created_at",
        ]
        read_only_fields = ["stato", "errore", "n_frammenti", "eliminabile", "created_at"]
