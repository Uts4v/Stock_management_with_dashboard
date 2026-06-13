from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

# Create router for ViewSet
router = DefaultRouter()
router.register(r'products', views.ProductViewSet, basename='product')

urlpatterns = [
    # API endpoints - specific paths BEFORE router
    path('api/products/categories/', views.CategoriesView.as_view(), name='categories'),
    path('api/products/export/excel/', views.export_products_excel, name='export-excel'),
    path('api/products/sync/google-sheets/', views.sync_google_sheet, name='sync-google-sheets'),
    path('api/products/import/google-sheets/', views.import_from_google_sheet, name='import-google-sheets'),
    path('api/reports/revenue/', views.RevenueReportView.as_view(), name='revenue-report'),
    path('api/reports/top-products/', views.TopProductsView.as_view(), name='top-products'),
    path('api/transactions/', views.SalesHistoryView.as_view(), name='transactions'),
    path('api/transactions/summary/', views.SalesSummaryView.as_view(), name='transactions-summary'),
    path('api/transactions/export/excel/', views.export_transactions_excel, name='export-transactions-excel'),
    path('api/transactions/delete/', views.delete_transactions, name='delete-transactions'),
    path('api/', include(router.urls)),
    
    # Template views
    path('', views.index, name='index'),
    path('low-stock/', views.low_stock, name='low-stock'),
    path('sales-history/', views.sales_history, name='sales-history'),
    path('login/', views.user_login, name='login'),
    path('signup/', views.user_signup, name='signup'),
    path('logout/', views.user_logout, name='logout'),
    path('api/auth/me/', views.current_user, name='current-user'),
]