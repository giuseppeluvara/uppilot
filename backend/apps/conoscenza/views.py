from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Arco, GrafoMeta, Nodo
from .tasks import costruisci_grafo_task


class GrafoView(APIView):
    """Restituisce l'intero grafo (nodi + archi). Layout/community lato client."""

    def get(self, request):
        tipo = request.query_params.get("tipo")
        nodi = Nodo.objects.all()
        if tipo:
            nodi = nodi.filter(tipo=tipo)
        archi = Arco.objects.all()
        return Response(
            {
                "nodi": [
                    {
                        "id": n.id,
                        "tipo": n.tipo,
                        "etichetta": n.etichetta,
                        "sintesi": n.sintesi,
                        "documento": n.documento_id,
                        "lavoro": n.lavoro_id,
                    }
                    for n in nodi
                ],
                "archi": [
                    {"id": e.id, "da": e.da_id, "a": e.a_id, "tipo": e.tipo, "peso": e.peso}
                    for e in archi
                ],
            }
        )


class StatoView(APIView):
    def get(self, request):
        meta = GrafoMeta.singleton()
        return Response(
            {
                "in_corso": meta.in_corso,
                "n_nodi": Nodo.objects.count(),
                "n_archi": Arco.objects.count(),
            }
        )


class CostruisciView(APIView):
    """Avvia la (ri)costruzione del grafo dal corpus (async, LLM locale di default)."""

    def post(self, request):
        commerciale = bool(request.data.get("commerciale"))
        costruisci_grafo_task.delay(commerciale)
        return Response({"detail": "Costruzione del grafo avviata."}, status=status.HTTP_202_ACCEPTED)


class NodoView(APIView):
    def delete(self, request, pk):
        get_object_or_404(Nodo, pk=pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ArcoView(APIView):
    def delete(self, request, pk):
        get_object_or_404(Arco, pk=pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
