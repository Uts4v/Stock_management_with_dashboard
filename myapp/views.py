from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.db.models import Sum, Count, Q
from django.db.models.functions import TruncDate, TruncWeek, TruncMonth
from django.utils import timezone
from django.http import HttpResponse
from datetime import timedelta, datetime
import json
import requests
from io import BytesIO
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import Product, StockTransaction
from .serializers import (
    ProductSerializer, StockTransactionSerializer,
    SellSerializer, RestockSerializer, RevenueReportSerializer, TopProductSerializer
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import SessionAuthentication

# Supabase integration
from .supabase_client import get_supabase_client

@api_view(['GET'])
def supabase_example(request):
    """
    Example view demonstrating Supabase integration.
    GET /api/supabase/example/
    """
    try:
        client = get_supabase_client()
        # Example: Fetch data from a table (replace 'your_table' with actual table name)
        # response = client.table('your_table').select("*").execute()
        return Response({
            'status': 'success',
            'message': 'Supabase connection successful',
            'url': client.supabase_url,
        })
    except Exception as e:
        return Response({
            'status': 'error',
            'message': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
def current_user(request):
    """
    Return the currently logged-in user's profile.
    GET /api/auth/me/
    """
    if not request.user.is_authenticated:
        return Response({'error': 'Not authenticated'}, status=status.HTTP_401_UNAUTHORIZED)
    
    user = request.user
    return Response({
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'date_joined': user.date_joined.isoformat(),
        'is_staff': user.is_staff,
    })

# Try to import openpyxl for Excel export
try:
    import openpyxl
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False


class ProductViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Product CRUD operations with search functionality.
    
    Endpoints:
    - GET /api/products/ - List all products (supports ?search= and ?category= query params)
    - POST /api/products/ - Create a new product
    - GET /api/products/{id}/ - Retrieve a product
    - PUT /api/products/{id}/ - Update a product
    - DELETE /api/products/{id}/ - Delete a product
    - POST /api/products/{id}/sell/ - Sell product (deduct stock)
    - POST /api/products/{id}/restock/ - Restock product (add stock)
    """
    queryset = Product.objects.all()
    serializer_class = ProductSerializer

    def get_queryset(self):
        """
        Filter products based on search query and category.
        Supports case-insensitive partial matching on name and category.
        """
        queryset = Product.objects.all()
        
        # Get search parameter
        search = self.request.query_params.get('search', None)
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) | Q(category__icontains=search)
            )
        
        # Get category filter
        category = self.request.query_params.get('category', None)
        if category:
            queryset = queryset.filter(category__iexact=category)
        
        return queryset

    def create(self, request, *args, **kwargs):
        """Create a new product"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    @action(detail=True, methods=['post'])
    def sell(self, request, pk=None):
        """
        Sell a product - deduct stock and create SALE transaction.
        
        Request body: {"quantity": int, "note": "optional string"}
        """
        product = self.get_object()
        serializer = SellSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        quantity = serializer.validated_data['quantity']
        note = serializer.validated_data.get('note', '')
        
        # Check if enough stock
        if product.stock < quantity:
            return Response(
                {'error': f'Insufficient stock. Available: {product.stock}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Deduct stock
        product.stock -= quantity
        product.save()
        
        # Create transaction
        StockTransaction.objects.create(
            product=product,
            transaction_type=StockTransaction.TransactionType.SALE,
            quantity=quantity,
            note=note,
            created_by=request.user if request.user.is_authenticated else None
        )
        
        return Response({
            'message': f'Sold {quantity} units of {product.name}',
            'product': ProductSerializer(product).data
        })

    @action(detail=True, methods=['post'])
    def restock(self, request, pk=None):
        """
        Restock a product - add stock and create RESTOCK transaction.
        
        Request body: {"quantity": int, "note": "optional string"}
        """
        product = self.get_object()
        serializer = RestockSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        quantity = serializer.validated_data['quantity']
        note = serializer.validated_data.get('note', '')
        
        # Add stock
        product.stock += quantity
        product.save()
        
        # Create transaction
        StockTransaction.objects.create(
            product=product,
            transaction_type=StockTransaction.TransactionType.RESTOCK,
            quantity=quantity,
            note=note,
            created_by=request.user if request.user.is_authenticated else None
        )
        
        return Response({
            'message': f'Restocked {quantity} units of {product.name}',
            'product': ProductSerializer(product).data
        })


class CategoriesView(APIView):
    """
    View to get distinct list of all product categories.
    
    GET /api/products/categories/
    """
    
    def get(self, request):
        """Return distinct categories"""
        categories = Product.objects.values_list('category', flat=True).distinct().order_by('category')
        return Response(list(categories))


class RevenueReportView(APIView):
    """
    View to get revenue reports grouped by date period.
    
    GET /api/reports/revenue/?period=daily|weekly|monthly
    
    Revenue = quantity × selling_price for SALE transactions only.
    """
    
    def get(self, request):
        period = request.query_params.get('period', 'daily')
        
        # Filter only SALE transactions
        sales = StockTransaction.objects.filter(
            transaction_type=StockTransaction.TransactionType.SALE
        ).select_related('product')
        
        # Determine truncation based on period
        if period == 'weekly':
            trunc_func = TruncWeek
        elif period == 'monthly':
            trunc_func = TruncMonth
        else:
            trunc_func = TruncDate
        
        # Group by date and aggregate
        report = sales.annotate(
            date=trunc_func('created_at')
        ).values('date').annotate(
            total_revenue=Sum('product__selling_price'),
            total_quantity=Sum('quantity')
        ).order_by('date')
        
        # Calculate revenue per transaction
        result = []
        for item in sales:
            revenue = item.quantity * item.product.selling_price
            result.append({
                'date': item.created_at.date(),
                'revenue': float(revenue)
            })
        
        # Group by date
        grouped = {}
        for item in result:
            date = item['date']
            if date not in grouped:
                grouped[date] = {'total_revenue': 0, 'total_quantity': 0}
            grouped[date]['total_revenue'] += item['revenue']
            grouped[date]['total_quantity'] += 1
        
        # Convert to list
        final_report = [
            {
                'date': date,
                'total_revenue': round(data['total_revenue'], 2),
                'total_quantity': data['total_quantity']
            }
            for date, data in sorted(grouped.items())
        ]
        
        return Response(final_report)


class TopProductsView(APIView):
    """
    View to get top 5 products by units sold this week (Monday to today).
    
    GET /api/reports/top-products/?search=optional_search_term
    
    Returns: product name, total units sold, total revenue
    """
    
    def get(self, request):
        # Get start of current week (Monday)
        today = timezone.now().date()
        start_of_week = today - timedelta(days=today.weekday())
        
        # Filter sales from start of week to today
        sales = StockTransaction.objects.filter(
            transaction_type=StockTransaction.TransactionType.SALE,
            created_at__date__gte=start_of_week,
            created_at__date__lte=today
        ).select_related('product')
        
        # Get optional search filter
        search = request.query_params.get('search', None)
        
        # Aggregate by product
        product_stats = {}
        for sale in sales:
            product_id = sale.product.id
            if product_id not in product_stats:
                product_stats[product_id] = {
                    'product_id': product_id,
                    'product_name': sale.product.name,
                    'total_units_sold': 0,
                    'total_revenue': 0
                }
            product_stats[product_id]['total_units_sold'] += sale.quantity
            product_stats[product_id]['total_revenue'] += float(sale.quantity * sale.product.selling_price)
        
        # Sort by units sold and get top 5
        sorted_products = sorted(
            product_stats.values(),
            key=lambda x: x['total_units_sold'],
            reverse=True
        )[:5]
        
        # Round revenue
        for product in sorted_products:
            product['total_revenue'] = round(product['total_revenue'], 2)
        
        # Apply search filter if provided
        if search:
            search_lower = search.lower()
            filtered = [p for p in sorted_products if search_lower in p['product_name'].lower()]
            if not filtered:
                return Response({
                    'message': f'"{search}" not found in top 5 products this week',
                    'search_term': search,
                    'top_products': sorted_products
                })
            return Response({
                'search_term': search,
                'highlighted_products': filtered,
                'top_products': sorted_products
            })
        
        return Response(sorted_products)


# Template views (protected - require login)
@login_required
def index(request):
    """Products page - index.html"""
    return render(request, 'index.html')

@login_required
def low_stock(request):
    """Low stock alerts page - low-stock.html"""
    return render(request, 'low-stock.html')

@login_required
def sales_history(request):
    """Sales history page - sales-history.html"""
    return render(request, 'sales-history.html')


def user_login(request):
    """
    Handle user login.
    
    GET /login/ - Show login form
    POST /login/ - Process login credentials
    """
    if request.user.is_authenticated:
        return redirect('index')
    
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        
        if not username or not password:
            messages.error(request, 'Please provide both username and password.')
            return render(request, 'login.html')
        
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            login(request, user)
            messages.success(request, f'Welcome back, {user.username}!')
            next_url = request.GET.get('next', 'index')
            return redirect(next_url)
        else:
            messages.error(request, 'Invalid username or password.')
            return render(request, 'login.html')
    
    return render(request, 'login.html')


def user_signup(request):
    """
    Handle user registration.
    
    GET /signup/ - Show signup form
    POST /signup/ - Process registration data
    """
    if request.user.is_authenticated:
        return redirect('index')
    
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '').strip()
        password_confirm = request.POST.get('confirm_password', '').strip()
        
        # Debug: Check raw values
        print(f"DEBUG - Full POST: {dict(request.POST)}")
        print(f"DEBUG - password: '{password}', password_confirm: '{password_confirm}'")
        print(f"DEBUG - password == password_confirm: {password == password_confirm}")
        print(f"DEBUG - password repr: {repr(password)}")
        print(f"DEBUG - password_confirm repr: {repr(password_confirm)}")
        
        # Validation
        if not username or not email or not password:
            messages.error(request, 'All fields are required.')
            return render(request, 'signup.html')
        
        if password != password_confirm:
            messages.error(request, f'Passwords do not match. Got: "{password}" vs "{password_confirm}"')
            return render(request, 'signup.html')
        
        if len(password) < 8:
            messages.error(request, 'Password must be at least 8 characters.')
            return render(request, 'signup.html')
        
        if User.objects.filter(username=username).exists():
            messages.error(request, 'Username already exists.')
            return render(request, 'signup.html')
        
        if User.objects.filter(email=email).exists():
            messages.error(request, 'Email already registered.')
            return render(request, 'signup.html')
        
        # Create user
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password
        )
        
        messages.success(request, 'Account created successfully! Please login.')
        return redirect('login')
    
    return render(request, 'signup.html')


def user_logout(request):
    """Handle user logout."""
    logout(request)
    messages.success(request, 'You have been logged out.')
    return redirect('login')


class SalesHistoryView(APIView):
    """
    View to get all transactions (sales, restocks, adjustments).
    
    GET /api/transactions/
    Supports filtering: ?type=SALE|RESTOCK|ADJUSTMENT&start_date=YYYY-MM-DD&end_date=YYYY-MM-DD&product_id=1
    """
    
    def get(self, request):
        queryset = StockTransaction.objects.select_related('product').all()
        
        # Filter by transaction type
        trans_type = request.query_params.get('type', None)
        if trans_type:
            queryset = queryset.filter(transaction_type=trans_type)
        
        # Filter by date range
        start_date = request.query_params.get('start_date', None)
        end_date = request.query_params.get('end_date', None)
        if start_date:
            queryset = queryset.filter(created_at__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__date__lte=end_date)
        
        # Filter by product
        product_id = request.query_params.get('product_id', None)
        if product_id:
            queryset = queryset.filter(product_id=product_id)
        
        # Order by most recent first
        queryset = queryset.order_by('-created_at')
        
        # Calculate revenue for each transaction
        transactions = []
        for t in queryset[:500]:  # Limit to 500 most recent
            revenue = None
            if t.transaction_type == StockTransaction.TransactionType.SALE:
                revenue = float(t.quantity * t.product.selling_price)
            
            transactions.append({
                'id': t.id,
                'product_id': t.product.id,
                'product_name': t.product.name,
                'transaction_type': t.transaction_type,
                'quantity': t.quantity,
                'unit_price': float(t.product.selling_price),
                'revenue': revenue,
                'note': t.note or '',
                'created_at': t.created_at.isoformat(),
            })
        
        return Response(transactions)


class SalesSummaryView(APIView):
    """
    View to get sales summary statistics.
    
    GET /api/transactions/summary/
    Returns: total sales, total revenue, average sale value for date range
    """
    
    def get(self, request):
        start_date = request.query_params.get('start_date', None)
        end_date = request.query_params.get('end_date', None)
        
        queryset = StockTransaction.objects.filter(
            transaction_type=StockTransaction.TransactionType.SALE
        ).select_related('product')
        
        if start_date:
            queryset = queryset.filter(created_at__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__date__lte=end_date)
        
        total_sales = queryset.count()
        total_quantity = queryset.aggregate(Sum('quantity'))['quantity__sum'] or 0
        total_revenue = sum(t.quantity * t.product.selling_price for t in queryset)
        avg_sale_value = total_revenue / total_sales if total_sales > 0 else 0
        
        return Response({
            'total_transactions': total_sales,
            'total_quantity_sold': total_quantity,
            'total_revenue': round(float(total_revenue), 2),
            'average_sale_value': round(float(avg_sale_value), 2),
        })
    


# ===== Excel Export View =====
@api_view(['GET'])
def export_products_excel(request):
    """
    Export all products to Excel file.
    
    GET /api/products/export/excel/
    """
    if not OPENPYXL_AVAILABLE:
        return Response(
            {'error': 'openpyxl library not installed. Run: pip install openpyxl'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    
    # Get all products
    products = Product.objects.all().order_by('-created_at')
    
    # Create workbook
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Products"
    
    # Define styles
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    
    # Headers
    headers = ['S.N', 'Product Name', 'Barcode', 'Category', 'Stock', 'Min Stock', 'Cost Price', 'Selling Price', 'Status']
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center')
        cell.border = thin_border
    
    # Data rows
    for row, product in enumerate(products, 2):
        ws.cell(row=row, column=1, value=row-1).border = thin_border
        ws.cell(row=row, column=2, value=product.name).border = thin_border
        ws.cell(row=row, column=3, value=product.barcode or '').border = thin_border
        ws.cell(row=row, column=4, value=product.category or '').border = thin_border
        ws.cell(row=row, column=5, value=product.stock).border = thin_border
        ws.cell(row=row, column=6, value=product.min_stock).border = thin_border
        ws.cell(row=row, column=7, value=float(product.cost_price)).border = thin_border
        ws.cell(row=row, column=8, value=float(product.selling_price)).border = thin_border
        ws.cell(row=row, column=9, value=product.status).border = thin_border
    
    # Set column widths
    column_widths = [5, 30, 15, 15, 10, 10, 12, 12, 10]
    for i, width in enumerate(column_widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = width
    
    # Create response
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename=Stock_Management_{datetime.now().strftime("%Y%m%d")}.xlsx'
    
    wb.save(response)
    return response


@api_view(['POST'])
def export_transactions_excel(request):
    """
    Export transactions to Excel file.
    
    POST /api/transactions/export/excel/
    Body: {"transactions": [...]}
    """
    if not OPENPYXL_AVAILABLE:
        return Response(
            {'error': 'openpyxl library not installed. Run: pip install openpyxl'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    
    transactions = request.data.get('transactions', [])
    
    if not transactions:
        return Response(
            {'error': 'No transactions to export'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Create workbook
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sales History"
    
    # Define styles
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="28a745", end_color="28a745", fill_type="solid")
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    
    # Headers
    headers = ['S.N', 'Date', 'Time', 'Product', 'Type', 'Quantity', 'Unit Price', 'Total Value', 'Note']
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center')
        cell.border = thin_border
    
    # Data rows
    for row, t in enumerate(transactions, 2):
        created_at = datetime.fromisoformat(t['created_at'].replace('Z', '+00:00'))
        
        ws.cell(row=row, column=1, value=row-1).border = thin_border
        ws.cell(row=row, column=2, value=created_at.strftime('%Y-%m-%d')).border = thin_border
        ws.cell(row=row, column=3, value=created_at.strftime('%H:%M')).border = thin_border
        ws.cell(row=row, column=4, value=t['product_name']).border = thin_border
        ws.cell(row=row, column=5, value=t['transaction_type']).border = thin_border
        ws.cell(row=row, column=6, value=t['quantity']).border = thin_border
        ws.cell(row=row, column=7, value=float(t['unit_price'])).border = thin_border
        
        total_value = t.get('revenue') if t.get('revenue') is not None else ''
        if total_value != '':
            ws.cell(row=row, column=8, value=float(total_value)).border = thin_border
        else:
            ws.cell(row=row, column=8, value='').border = thin_border
        
        ws.cell(row=row, column=9, value=t.get('note') or '').border = thin_border
    
    # Set column widths
    column_widths = [5, 12, 10, 30, 12, 10, 12, 12, 25]
    for i, width in enumerate(column_widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = width
    
    # Create response
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename=Sales_History_{datetime.now().strftime("%Y%m%d")}.xlsx'
    
    wb.save(response)
    return response


@api_view(['DELETE'])
def delete_transactions(request):
    """
    Delete transactions by IDs or clear all.
    
    DELETE /api/transactions/
    Body: {"ids": [1, 2, 3]} OR {"clear_all": true}
    """
    clear_all = request.data.get('clear_all', False)
    
    if clear_all:
        count = StockTransaction.objects.count()
        StockTransaction.objects.all().delete()
        return Response({
            'message': f'Deleted {count} transactions',
            'deleted_count': count
        })
    
    ids = request.data.get('ids', [])
    if not ids:
        return Response(
            {'error': 'No transaction IDs provided'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    deleted_count = StockTransaction.objects.filter(id__in=ids).delete()[0]
    return Response({
        'message': f'Deleted {deleted_count} transactions',
        'deleted_count': deleted_count
    })


# ===== Google Sheets Sync View =====
@api_view(['POST'])
def sync_google_sheet(request):
    """
    Sync products to Google Sheets.
    
    POST /api/products/sync/google-sheets/
    Body: {"sheet_id": "...", "api_key": "..."}
    """
    sheet_id = request.data.get('sheet_id')
    api_key = request.data.get('api_key')
    
    if not sheet_id or not api_key:
        return Response(
            {'error': 'sheet_id and api_key are required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        # Get all products
        products = Product.objects.all().order_by('-created_at')
        
        # Prepare data for Google Sheets
        values = [
            ['Name', 'Barcode', 'Category', 'Stock', 'Min Stock', 'Cost Price', 'Selling Price', 'Status', 'Last Updated']
        ]
        
        for product in products:
            values.append([
                product.name,
                product.barcode or '',
                product.category or '',
                product.stock,
                product.min_stock,
                float(product.cost_price),
                float(product.selling_price),
                product.status,
                datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            ])
        
        # Google Sheets API call
        range_name = f'Sheet1!A1:I{len(values)}'
        url = f'https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{range_name}'
        
        payload = {
            'values': values
        }
        
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
        
        # Note: For actual API key auth, use ?key= parameter instead
        # This is a simplified version - in production, use OAuth2
        params = {'key': api_key, 'valueInputOption': 'RAW'}
        
        response = requests.put(
            f'https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{range_name}',
            params=params,
            json=payload
        )
        
        if response.status_code == 200:
            return Response({
                'message': f'Successfully synced {len(products)} products to Google Sheets',
                'products_count': len(products)
            })
        else:
            return Response(
                {'error': f'Google Sheets API error: {response.text}'},
                status=status.HTTP_400_BAD_REQUEST
            )
            
    except Exception as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
def import_from_google_sheet(request):
    """
    Import products from Google Sheets.
    
    POST /api/products/import/google-sheets/
    Body: {"sheet_id": "...", "api_key": "...", "range": "Sheet1!A1:I100"}
    """
    sheet_id = request.data.get('sheet_id')
    api_key = request.data.get('api_key')
    range_name = request.data.get('range', 'Sheet1!A1:I100')
    
    if not sheet_id or not api_key:
        return Response(
            {'error': 'sheet_id and api_key are required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        # Google Sheets API call to read data
        url = f'https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{range_name}'
        params = {'key': api_key}
        
        response = requests.get(url, params=params)
        
        if response.status_code != 200:
            return Response(
                {'error': f'Google Sheets API error: {response.text}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        data = response.json()
        values = data.get('values', [])
        
        if not values or len(values) < 2:
            return Response(
                {'error': 'No data found in the specified range'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Skip header row
        imported_count = 0
        errors = []
        
        for i, row in enumerate(values[1:], 2):  # Skip header
            try:
                if len(row) < 6:
                    errors.append(f'Row {i}: Not enough columns')
                    continue
                
                # Parse row data
                name = row[0] if len(row) > 0 else ''
                barcode = row[1] if len(row) > 1 else ''
                category = row[2] if len(row) > 2 else ''
                stock = int(row[3]) if len(row) > 3 and row[3] else 0
                min_stock = int(row[4]) if len(row) > 4 and row[4] else 10
                cost_price = float(row[5]) if len(row) > 5 and row[5] else 0
                selling_price = float(row[6]) if len(row) > 6 and row[6] else 0
                
                if not name:
                    errors.append(f'Row {i}: Product name is required')
                    continue
                
                # Check if product exists (by name)
                product, created = Product.objects.get_or_create(
                    name=name,
                    defaults={
                        'barcode': barcode,
                        'category': category,
                        'stock': stock,
                        'min_stock': min_stock,
                        'cost_price': cost_price,
                        'selling_price': selling_price
                    }
                )
                
                if not created:
                    # Update existing product
                    product.barcode = barcode
                    product.category = category
                    product.stock = stock
                    product.min_stock = min_stock
                    product.cost_price = cost_price
                    product.selling_price = selling_price
                    product.save()
                
                imported_count += 1
                
            except Exception as e:
                errors.append(f'Row {i}: {str(e)}')
        
        return Response({
            'message': f'Successfully imported {imported_count} products',
            'imported_count': imported_count,
            'errors': errors if errors else None
        })
        
    except Exception as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    