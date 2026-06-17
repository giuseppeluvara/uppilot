from rest_framework.routers import DefaultRouter

from .views import DocumentoViewSet, LavoroViewSet

router = DefaultRouter()
router.register(r"lavori", LavoroViewSet, basename="lavoro")
router.register(r"documenti", DocumentoViewSet, basename="documento")

urlpatterns = router.urls
