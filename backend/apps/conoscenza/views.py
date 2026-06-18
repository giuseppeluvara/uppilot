from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Arco, GrafoMeta, Nodo
from .tasks import costruisci_grafo_task


def _nodi_visibili(user):
    """Corpus condiviso (lavoro nullo) + SOLO i casi dell'utente."""
    return Nodo.objects.filter(Q(lavoro__isnull=True) | Q(lavoro__utente=user))


class GrafoView(APIView):
    """Restituisce il grafo visibile all'utente (corpus + suoi casi)."""

    def get(self, request):
        tipo = request.query_params.get("tipo")
        nodi = _nodi_visibili(request.user)
        if tipo:
            nodi = nodi.filter(tipo=tipo)
        ids = set(nodi.values_list("id", flat=True))
        archi = Arco.objects.filter(da_id__in=ids, a_id__in=ids)
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
        nodi = _nodi_visibili(request.user)
        ids = set(nodi.values_list("id", flat=True))
        return Response(
            {
                "in_corso": meta.in_corso,
                "n_nodi": len(ids),
                "n_archi": Arco.objects.filter(da_id__in=ids, a_id__in=ids).count(),
            }
        )


class CostruisciView(APIView):
    """Avvia la (ri)costruzione del grafo (corpus + casi dell'utente; LLM locale)."""

    def post(self, request):
        commerciale = bool(request.data.get("commerciale"))
        costruisci_grafo_task.delay(commerciale, request.user.id)
        return Response({"detail": "Costruzione del grafo avviata."}, status=status.HTTP_202_ACCEPTED)


class NodoView(APIView):
    def delete(self, request, pk):
        get_object_or_404(_nodi_visibili(request.user), pk=pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ArcoView(APIView):
    def delete(self, request, pk):
        ids = set(_nodi_visibili(request.user).values_list("id", flat=True))
        arco = get_object_or_404(Arco, pk=pk, da_id__in=ids, a_id__in=ids)
        arco.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
