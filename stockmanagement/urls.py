from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
import os

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('myapp.urls'))
]

# Serve static files in development
if settings.DEBUG:
    # Serve from the static directory (not staticfiles)
    static_dir = os.path.join(settings.BASE_DIR, 'static')
    urlpatterns += static(settings.STATIC_URL, document_root=static_dir)
