from celery import current_app
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Arco, GrafoMeta, Nodo
from .tasks import costruisci_grafo_task


def _nodi_visibili(user):
    """Corpus condiviso (lavoro nullo) + SOLO i casi dell'utente."""
    qs = Nodo.objects.select_related("documento", "lavoro")
    if user.is_staff:
        return qs
    return qs.filter(
        Q(lavoro__utente=user)
        | Q(lavoro__isnull=True, documento__isnull=True)
        | Q(lavoro__isnull=True, documento__creato_da__isnull=True)
        | Q(lavoro__isnull=True, documento__creato_da=user)
    )


def _puo_eliminare_nodo(user, nodo: Nodo) -> bool:
    if user.is_staff:
        return True
    if nodo.lavoro_id:
        return nodo.lavoro.utente_id == user.id
    if nodo.documento_id:
        return nodo.documento.creato_da_id == user.id
    return False


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
                        "documento_titolo": n.documento.titolo if n.documento_id else "",
                        "lavoro": n.lavoro_id,
                        "origine": "fascicolo"
                        if n.lavoro_id
                        else "corpus"
                        if n.documento_id
                        else "globale",
                        "snippet": (n.documento.testo[:240] if n.documento_id else n.sintesi[:240]),
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
                "progresso": meta.progresso or {},
                "changelog": meta.changelog or [],
            }
        )


class CostruisciView(APIView):
    """Avvia la (ri)costruzione del grafo (corpus + casi dell'utente; LLM locale)."""

    def post(self, request):
        meta = GrafoMeta.singleton()
        if meta.in_corso:
            return Response(
                {"detail": "Costruzione del grafo già in corso."},
                status=status.HTTP_409_CONFLICT,
            )
        commerciale = bool(request.data.get("commerciale"))
        scope = request.data.get("scope") or "tutto"
        if scope not in {"tutto", "corpus", "fascicoli", "lavoro"}:
            return Response(
                {"detail": "Scope non valido: usa tutto, corpus, fascicoli o lavoro."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        lavoro_id = request.data.get("lavoro_id")
        if lavoro_id is not None:
            try:
                lavoro_id = int(lavoro_id)
            except (TypeError, ValueError):
                return Response({"detail": "lavoro_id non valido."}, status=status.HTTP_400_BAD_REQUEST)
        res = costruisci_grafo_task.delay(commerciale, request.user.id, scope, lavoro_id)
        meta.task_id = res.id
        meta.in_corso = True
        meta.save(update_fields=["task_id", "in_corso", "aggiornato_at"])
        return Response(
            {"detail": "Costruzione del grafo avviata.", "task_id": res.id},
            status=status.HTTP_202_ACCEPTED,
        )


class AnnullaCostruzioneView(APIView):
    """Interrompe la costruzione del grafo in corso."""

    def post(self, request):
        meta = GrafoMeta.singleton()
        if meta.task_id:
            current_app.control.revoke(meta.task_id, terminate=True, signal="SIGTERM")
        meta.in_corso = False
        meta.task_id = ""
        meta.progresso = {
            "fase": "interrotta",
            "corrente": 0,
            "totale": 1,
            "percentuale": 0,
            "messaggio": "Costruzione del grafo interrotta dall'utente",
        }
        meta.save(update_fields=["in_corso", "task_id", "progresso", "aggiornato_at"])
        return Response({"detail": "Costruzione interrotta."})


class NodoView(APIView):
    def delete(self, request, pk):
        nodo = get_object_or_404(_nodi_visibili(request.user), pk=pk)
        if not _puo_eliminare_nodo(request.user, nodo):
            raise PermissionDenied("Puoi eliminare solo nodi dei tuoi casi o del tuo corpus.")
        nodo.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ArcoView(APIView):
    def delete(self, request, pk):
        ids = set(_nodi_visibili(request.user).values_list("id", flat=True))
        arco = get_object_or_404(Arco, pk=pk, da_id__in=ids, a_id__in=ids)
        if not request.user.is_staff and (
            not _puo_eliminare_nodo(request.user, arco.da)
            or not _puo_eliminare_nodo(request.user, arco.a)
        ):
            raise PermissionDenied("Puoi eliminare solo relazioni dei tuoi casi o del tuo corpus.")
        arco.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
