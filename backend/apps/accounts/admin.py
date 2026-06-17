from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Utente

admin.site.register(Utente, UserAdmin)
