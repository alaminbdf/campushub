from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("library/", include("apps.library.urls")),
    path("lost-found/", include("apps.lost_found.urls")),
    path("facilities/", include("apps.facilities.urls")),
    path("forecasting/", include("apps.forecasting.urls")),
    path("", include("apps.dashboards.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)