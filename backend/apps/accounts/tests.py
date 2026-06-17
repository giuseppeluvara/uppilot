import pytest
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_me_non_autenticato_403():
    assert APIClient().get("/api/auth/me/").status_code == 403


@pytest.mark.django_db
def test_login_e_me(django_user_model):
    django_user_model.objects.create_user(username="r", password="segreta")
    client = APIClient()

    ko = client.post("/api/auth/login/", {"username": "r", "password": "errata"}, format="json")
    assert ko.status_code == 401

    ok = client.post("/api/auth/login/", {"username": "r", "password": "segreta"}, format="json")
    assert ok.status_code == 200
    assert ok.data["username"] == "r"

    me = client.get("/api/auth/me/")
    assert me.status_code == 200
    assert me.data["username"] == "r"
