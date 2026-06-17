from django.contrib.auth.models import AbstractUser
from django.db import models


class Utente(AbstractUser):
    """Utente redattore.

    M1 prevede un singolo utente redattore, ma il campo `ruolo` lascia aperta
    la possibilità di ruoli futuri senza modifiche allo schema (§157).
    """

    class Ruolo(models.TextChoices):
        REDATTORE = "redattore", "Redattore"

    ruolo = models.CharField(
        max_length=32,
        choices=Ruolo.choices,
        default=Ruolo.REDATTORE,
    )

    def __str__(self) -> str:
        return self.get_username()
