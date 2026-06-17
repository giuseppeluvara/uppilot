"""Test della canonicalizzazione dei placeholder a livello di lavoro (export in chiaro)."""
import pytest

from apps.casi.models import Lavoro
from apps.casi.tasks import _canonicalizza


@pytest.fixture
def lavoro(db, django_user_model):
    u = django_user_model.objects.create_user(username="r", password="x")
    return Lavoro.objects.create(utente=u, titolo="Caso")


def test_stessa_entita_stesso_placeholder_tra_documenti(lavoro):
    # Doc 1: PERSON_1 = Tizio
    t1, m1 = _canonicalizza(lavoro, "[PRIVATE_PERSON_1] agisce.", {"[PRIVATE_PERSON_1]": "Tizio"})
    # Doc 2: PERSON_1 = Caio, PERSON_2 = Tizio (numerazione locale diversa!)
    t2, m2 = _canonicalizza(
        lavoro,
        "[PRIVATE_PERSON_1] contro [PRIVATE_PERSON_2]",
        {"[PRIVATE_PERSON_1]": "Caio", "[PRIVATE_PERSON_2]": "Tizio"},
    )

    # Tizio deve avere lo STESSO placeholder canonico in entrambi i documenti.
    ph_tizio_1 = [k for k, v in m1.items() if v == "Tizio"][0]
    ph_tizio_2 = [k for k, v in m2.items() if v == "Tizio"][0]
    assert ph_tizio_1 == ph_tizio_2
    assert ph_tizio_1 in t2  # il testo del doc 2 usa il placeholder canonico di Tizio

    # Il registro del lavoro contiene entrambe le entità, senza duplicati.
    lavoro.refresh_from_db()
    assert set(lavoro.mappa_entita.values()) == {"Tizio", "Caio"}


def test_placeholder_a_doppia_cifra_non_collide(lavoro):
    mappa = {f"[PRIVATE_PERSON_{i}]": f"Persona{i}" for i in range(1, 12)}
    testo = " ".join(mappa.keys())
    t, m = _canonicalizza(lavoro, testo, mappa)
    # Tutti gli 11 placeholder devono essere stati rimappati correttamente (nessuna collisione _1 in _10).
    assert len(m) == 11
    assert "Persona10" in m.values() and "Persona1" in m.values()
