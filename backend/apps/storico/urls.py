from django.urls import path

from .views import StoricoListView

urlpatterns = [
    path("storico/", StoricoListView.as_view(), name="storico"),
]
