from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.conf import settings
from django.db.models import Sum, Count, Q
from django.db.models.functions import TruncDate, TruncWeek, TruncMonth
from django.utils import timezone
from django.http import HttpResponse
from datetime import timedelta, datetime
import json
import requests
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import Product, ProductVariant, StockTransaction
from .serializers import (
    ProductSerializer, ProductVariantSerializer, StockTransactionSerializer,
    SellSerializer, RestockSerializer, RevenueReportSerializer, TopProductSerializer,
    ProductDictSerializer, ProductVariantDictSerializer,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import SessionAuthentication

# Supabase integration
from .supabase_client import (
    get_supabase_client,
    get_all_products,
    get_product_by_id,
    create_product, update_product, delete_product,
    create_variant, update_variant, delete_variant,
    get_all_variants,
    get_variant_by_id,
    create_transaction,
)

# Try to import openpyxl for Excel export
try:
    import openpyxl
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False


# ─────────────────────────────────────────────
#  Helper: push a StockTransaction to Supabase
# ─────────────────────────────────────────────
def _sync_transaction(transaction):
    """Push a freshly-created StockTransaction row to Supabase."""
    try:
        client = get_supabase_client()
        client.table('myapp_stocktransaction').insert({
            'id': transaction.id,
            'product_id': transaction.product_id,
            'variant_id': transaction.variant_id,
            'transaction_type': transaction.transaction_type,
            'quantity': transaction.quantity,
            'note': transaction.note or '',
            'created_by_id': transaction.created_by_id,
            'created_at': transaction.created_at.isoformat(),
        }).execute()
    except Exception as e:
        print(f"Supabase sync error (transaction): {e}")


# ─────────────────────────────────────────────
#  Auth / utility endpoints
# ─────────────────────────────────────────────
@api_view(['GET'])
def supabase_example(request):
    """GET /api/supabase/example/"""
    try:
        client = get_supabase_client()
        return Response({
            'status': 'success',
            'message': 'Supabase connection successful',
            'url': client.supabase_url,
        })
    except Exception as e:
        return Response({'status': 'error', 'message': str(e)},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def current_user(request):
    """GET /api/auth/me/"""
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


# ─────────────────────────────────────────────
#  ProductViewSet
# ─────────────────────────────────────────────
class ProductViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Product CRUD operations with search functionality.

    Endpoints:
    - GET    /api/products/              - List all products (?search= and ?category=)
    - POST   /api/products/              - Create a new product
    - GET    /api/products/{id}/         - Retrieve a product
    - PUT    /api/products/{id}/         - Update a product
    - DELETE /api/products/{id}/         - Delete a product
    - POST   /api/products/{id}/sell/    - Sell product (deduct stock)
    - POST   /api/products/{id}/restock/ - Restock product (add stock)
    """
    queryset = Product.objects.all()
    serializer_class = ProductSerializer

    def get_queryset(self):
        """
        In production (DEBUG=False): Read directly from Supabase.
        In development (DEBUG=True): Use local SQLite.
        """
        if not settings.DEBUG:
            return self._get_products_from_supabase()
        
        queryset = Product.objects.all()
        search = self.request.query_params.get('search', None)
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) | Q(category__icontains=search)
            )
        category = self.request.query_params.get('category', None)
        if category:
            queryset = queryset.filter(category__iexact=category)
        return queryset

    def _get_products_from_supabase(self):
        """Fetch products directly from Supabase as the single source of truth."""
        try:
            products = get_all_products()
            # Return as a list of dicts for DRF serialization
            return products
        except Exception as e:
            print(f"Supabase fetch error: {e}")
            return []

    def list(self, request, *args, **kwargs):
        """Override list to handle Supabase data (which is not a Django QuerySet)."""
        if not settings.DEBUG:
            queryset = self._get_products_from_supabase()
            # Apply filters manually for Supabase data
            search = request.query_params.get('search', None)
            category = request.query_params.get('category', None)
            if search:
                search_lower = search.lower()
                queryset = [p for p in queryset 
                           if search_lower in p.get('name', '').lower() 
                           or search_lower in p.get('category', '').lower()]
            if category:
                queryset = [p for p in queryset 
                           if p.get('category', '').lower() == category.lower()]
            # Use dict serializer for Supabase data
            serializer = ProductDictSerializer(queryset, many=True)
            return Response(serializer.data)
        return super().list(request, *args, **kwargs)

    def perform_create(self, serializer):
        """Create product in SQLite and sync to Supabase."""
        instance = serializer.save()
        try:
            create_product({
                'id': instance.id,
                'name': instance.name,
                'barcode': instance.barcode or '',
                'category': instance.category or '',
                'stock': instance.stock,
                'min_stock': instance.min_stock,
                'cost_price': float(instance.cost_price),
                'selling_price': float(instance.selling_price),
                'created_at': instance.created_at.isoformat(),
            })
        except Exception as e:
            print(f"Supabase sync error (create product): {e}")

    def perform_update(self, serializer):
        """Update product in SQLite and sync to Supabase."""
        instance = serializer.save()
        try:
            update_product(instance.id, {
                'name': instance.name,
                'barcode': instance.barcode or '',
                'category': instance.category or '',
                'stock': instance.stock,
                'min_stock': instance.min_stock,
                'cost_price': float(instance.cost_price),
                'selling_price': float(instance.selling_price),
                'created_at': instance.created_at.isoformat(),
            })
        except Exception as e:
            print(f"Supabase sync error (update product): {e}")

    def destroy(self, request, *args, **kwargs):
        """Delete a product."""
        if not settings.DEBUG:
            # Production: Delete directly from Supabase
            pk = kwargs.get('pk')
            try:
                delete_product(int(pk))
                return Response(status=status.HTTP_204_NO_CONTENT)
            except Exception as e:
                return Response({'error': str(e)}, status=status.HTTP_404_NOT_FOUND)
        
        # Development: Use local SQLite
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def perform_destroy(self, instance):
        """Delete product from SQLite and sync to Supabase."""
        product_id = instance.id
        instance.delete()
        try:
            delete_product(product_id)
        except Exception as e:
            print(f"Supabase sync error (delete product): {e}")

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    @action(detail=True, methods=['post'])
    def sell(self, request, pk=None):
        """Sell a product – deduct stock and create SALE transaction."""
        serializer = SellSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        quantity = serializer.validated_data['quantity']
        note = serializer.validated_data.get('note', '')
        
        if not settings.DEBUG:
            # Production: Work directly with Supabase
            try:
                product = get_product_by_id(int(pk))
                if not product:
                    return Response({'error': 'Product not found'}, status=status.HTTP_404_NOT_FOUND)
                
                if product['stock'] < quantity:
                    return Response(
                        {'error': f'Insufficient stock. Available: {product["stock"]}'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                
                new_stock = product['stock'] - quantity
                update_product(int(pk), {'stock': new_stock})
                
                # Create transaction in Supabase
                txn_data = {
                    'product_id': int(pk),
                    'transaction_type': 'SALE',
                    'quantity': quantity,
                    'note': note,
                }
                if request.user.is_authenticated:
                    txn_data['created_by_id'] = request.user.id
                create_transaction(txn_data)
                
                return Response({
                    'message': f'Sold {quantity} units of {product["name"]}',
                    'product': {**product, 'stock': new_stock}
                })
            except Exception as e:
                return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        # Development: Use local SQLite
        product = self.get_object()
        if product.stock < quantity:
            return Response(
                {'error': f'Insufficient stock. Available: {product.stock}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        product.stock -= quantity
        product.save()

        txn = StockTransaction.objects.create(
            product=product,
            transaction_type=StockTransaction.TransactionType.SALE,
            quantity=quantity,
            note=note,
            created_by=request.user if request.user.is_authenticated else None
        )

        # Sync to Supabase
        try:
            update_product(product.id, {'stock': product.stock})
        except Exception as e:
            print(f"Supabase sync error (sell product stock): {e}")
        _sync_transaction(txn)

        return Response({
            'message': f'Sold {quantity} units of {product.name}',
            'product': ProductSerializer(product).data
        })

    @action(detail=True, methods=['post'])
    def restock(self, request, pk=None):
        """Restock a product – add stock and create RESTOCK transaction."""
        serializer = RestockSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        quantity = serializer.validated_data['quantity']
        note = serializer.validated_data.get('note', '')
        
        if not settings.DEBUG:
            # Production: Work directly with Supabase
            try:
                product = get_product_by_id(int(pk))
                if not product:
                    return Response({'error': 'Product not found'}, status=status.HTTP_404_NOT_FOUND)
                
                new_stock = product['stock'] + quantity
                update_product(int(pk), {'stock': new_stock})
                
                # Create transaction in Supabase
                txn_data = {
                    'product_id': int(pk),
                    'transaction_type': 'RESTOCK',
                    'quantity': quantity,
                    'note': note,
                }
                if request.user.is_authenticated:
                    txn_data['created_by_id'] = request.user.id
                create_transaction(txn_data)
                
                return Response({
                    'message': f'Restocked {quantity} units of {product["name"]}',
                    'product': {**product, 'stock': new_stock}
                })
            except Exception as e:
                return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        # Development: Use local SQLite
        product = self.get_object()
        product.stock += quantity
        product.save()

        txn = StockTransaction.objects.create(
            product=product,
            transaction_type=StockTransaction.TransactionType.RESTOCK,
            quantity=quantity,
            note=note,
            created_by=request.user if request.user.is_authenticated else None
        )

        # Sync to Supabase
        try:
            update_product(product.id, {'stock': product.stock})
        except Exception as e:
            print(f"Supabase sync error (restock product stock): {e}")
        _sync_transaction(txn)

        return Response({
            'message': f'Restocked {quantity} units of {product.name}',
            'product': ProductSerializer(product).data
        })

    @action(detail=True, methods=['patch'], url_path='update-stock')
    def update_stock(self, request, pk=None):
        """Update product stock directly (for inline editing)."""
        new_stock = request.data.get('stock')
        if new_stock is None:
            return Response({'error': 'stock is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            new_stock = int(new_stock)
            if new_stock < 0:
                return Response({'error': 'stock must be non-negative'}, status=status.HTTP_400_BAD_REQUEST)
        except (ValueError, TypeError):
            return Response({'error': 'stock must be an integer'}, status=status.HTTP_400_BAD_REQUEST)
        
        if not settings.DEBUG:
            # Production: Update directly in Supabase
            try:
                product = get_product_by_id(int(pk))
                if not product:
                    return Response({'error': 'Product not found'}, status=status.HTTP_404_NOT_FOUND)
                
                update_product(int(pk), {'stock': new_stock})
                return Response({'message': 'Stock updated', 'stock': new_stock})
            except Exception as e:
                return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        # Development: Use local SQLite
        product = self.get_object()
        product.stock = new_stock
        product.save()
        
        # Sync to Supabase
        try:
            update_product(product.id, {'stock': new_stock})
        except Exception as e:
            print(f"Supabase sync error (update stock): {e}")
        
        return Response({'message': 'Stock updated', 'stock': new_stock})

    @action(detail=True, methods=['patch'])
    def update_min_stock(self, request, pk=None):
        """Update product min_stock."""
        min_stock = request.data.get('min_stock')
        if min_stock is None:
            return Response({'error': 'min_stock is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            min_stock = int(min_stock)
            if min_stock < 0:
                return Response({'error': 'min_stock must be non-negative'}, status=status.HTTP_400_BAD_REQUEST)
        except (ValueError, TypeError):
            return Response({'error': 'min_stock must be an integer'}, status=status.HTTP_400_BAD_REQUEST)
        
        if not settings.DEBUG:
            # Production: Update directly in Supabase
            try:
                product = get_product_by_id(int(pk))
                if not product:
                    return Response({'error': 'Product not found'}, status=status.HTTP_404_NOT_FOUND)
                
                update_product(int(pk), {'min_stock': min_stock})
                return Response({'message': 'Min stock updated', 'min_stock': min_stock})
            except Exception as e:
                return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        # Development: Use local SQLite
        product = self.get_object()
        product.min_stock = min_stock
        product.save()
        
        # Sync to Supabase
        try:
            update_product(product.id, {'min_stock': min_stock})
        except Exception as e:
            print(f"Supabase sync error (update min_stock): {e}")
        
        return Response({'message': 'Min stock updated', 'min_stock': min_stock})


# ─────────────────────────────────────────────
#  ProductVariantViewSet  (single, unified)
# ─────────────────────────────────────────────
#  Helper: sync variants from Supabase to local SQLite
# ─────────────────────────────────────────────
def _sync_variants_from_supabase():
    """
    Pull all variants from Supabase and upsert them into local SQLite.
    This ensures variants created directly in Supabase appear locally.
    """
    try:
        supabase_variants = get_all_variants()
        for sv in supabase_variants:
            product_id = sv.get('product_id')
            if not product_id:
                continue
            # Check if product exists locally
            if not Product.objects.filter(id=product_id).exists():
                continue
            
            ProductVariant.objects.update_or_create(
                id=sv['id'],
                defaults={
                    'product_id': product_id,
                    'variant_type': sv.get('variant_type', ''),
                    'variant_value': sv.get('variant_value', ''),
                    'stock': sv.get('stock', 0),
                    'min_stock': sv.get('min_stock', 0),
                    'cost_price': sv.get('cost_price') or 0,
                    'selling_price': sv.get('selling_price') or 0,
                    'barcode': sv.get('barcode') or '',
                }
            )
    except Exception as e:
        print(f"Supabase sync error (variants from Supabase): {e}")


# ─────────────────────────────────────────────
class ProductVariantViewSet(viewsets.ModelViewSet):
    """
    ViewSet for ProductVariant CRUD operations.

    Endpoints:
    - GET    /api/variants/                  - List all variants (?product_id= filter)
    - POST   /api/variants/                  - Create a new variant
    - GET    /api/variants/{id}/             - Retrieve a variant
    - PUT    /api/variants/{id}/             - Update a variant
    - DELETE /api/variants/{id}/             - Delete a variant
    - POST   /api/variants/{id}/sell/        - Sell variant (deduct stock)
    - POST   /api/variants/{id}/restock/     - Restock variant (add stock)
    """
    queryset = ProductVariant.objects.all()
    serializer_class = ProductVariantSerializer

    def get_queryset(self):
        """
        In production (DEBUG=False): Read directly from Supabase.
        In development (DEBUG=True): Use local SQLite.
        """
        if not settings.DEBUG:
            return self._get_variants_from_supabase()
        
        queryset = ProductVariant.objects.select_related('product').all()
        product_id = self.request.query_params.get('product_id', None)
        if product_id:
            queryset = queryset.filter(product_id=product_id)
        return queryset

    def _get_variants_from_supabase(self):
        """Fetch variants directly from Supabase as the single source of truth."""
        try:
            variants = get_all_variants()
            return variants
        except Exception as e:
            print(f"Supabase fetch error (variants): {e}")
            return []

    def list(self, request, *args, **kwargs):
        """Override list to handle Supabase data (which is not a Django QuerySet)."""
        if not settings.DEBUG:
            queryset = self._get_variants_from_supabase()
            # Apply product_id filter manually for Supabase data
            product_id = request.query_params.get('product_id', None)
            if product_id:
                queryset = [v for v in queryset if v.get('product_id') == int(product_id)]
            # Use dict serializer for Supabase data
            serializer = ProductVariantDictSerializer(queryset, many=True)
            return Response(serializer.data)
        return super().list(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        """Create a new variant, update product stock, sync to Supabase."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        variant = serializer.save()
        variant.product.update_total_stock()

        try:
            create_variant({
                'id': variant.id,
                'product_id': variant.product_id,
                'variant_type': variant.variant_type,
                'variant_value': variant.variant_value,
                'stock': variant.stock,
                'min_stock': variant.min_stock,
                'cost_price': float(variant.cost_price) if variant.cost_price else None,
                'selling_price': float(variant.selling_price) if variant.selling_price else None,
                'barcode': variant.barcode or '',
                'created_at': variant.created_at.isoformat() if hasattr(variant, 'created_at') and variant.created_at else datetime.now().isoformat(),
            })
        except Exception as e:
            print(f"Supabase sync error (create variant): {e}")

        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        """Update a variant, refresh product stock, sync to Supabase."""
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        variant = serializer.save()
        variant.product.update_total_stock()

        try:
            update_variant(variant.id, {
                'product_id': variant.product_id,
                'variant_type': variant.variant_type,
                'variant_value': variant.variant_value,
                'stock': variant.stock,
                'min_stock': variant.min_stock,
                'cost_price': float(variant.cost_price) if variant.cost_price else None,
                'selling_price': float(variant.selling_price) if variant.selling_price else None,
                'barcode': variant.barcode or '',
            })
        except Exception as e:
            print(f"Supabase sync error (update variant): {e}")

        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        """Delete a variant, update product stock, sync to Supabase."""
        if not settings.DEBUG:
            # Production: Delete directly from Supabase
            pk = kwargs.get('pk')
            try:
                delete_variant(int(pk))
                return Response(status=status.HTTP_204_NO_CONTENT)
            except Exception as e:
                return Response({'error': str(e)}, status=status.HTTP_404_NOT_FOUND)
        
        # Development: Use local SQLite
        instance = self.get_object()
        product = instance.product
        variant_id = instance.id
        instance.delete()
        product.update_total_stock()

        try:
            delete_variant(variant_id)
        except Exception as e:
            print(f"Supabase sync error (delete variant): {e}")

        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'])
    def sell(self, request, pk=None):
        """Sell a variant – deduct stock and create SALE transaction."""
        serializer = SellSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        quantity = serializer.validated_data['quantity']
        note = serializer.validated_data.get('note', '')
        
        if not settings.DEBUG:
            # Production: Work directly with Supabase
            try:
                variant = get_variant_by_id(int(pk))
                if not variant:
                    return Response({'error': 'Variant not found'}, status=status.HTTP_404_NOT_FOUND)
                
                if variant['stock'] < quantity:
                    return Response(
                        {'error': f'Insufficient stock. Available: {variant["stock"]}'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                
                new_stock = variant['stock'] - quantity
                update_variant(int(pk), {'stock': new_stock})
                
                # Create transaction in Supabase
                txn_data = {
                    'product_id': variant['product_id'],
                    'variant_id': int(pk),
                    'transaction_type': 'SALE',
                    'quantity': quantity,
                    'note': note,
                }
                if request.user.is_authenticated:
                    txn_data['created_by_id'] = request.user.id
                create_transaction(txn_data)
                
                return Response({
                    'message': f'Sold {quantity} units of {variant["variant_type"]}: {variant["variant_value"]}',
                    'variant': {**variant, 'stock': new_stock}
                })
            except Exception as e:
                return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        # Development: Use local SQLite
        variant = self.get_object()
        if variant.stock < quantity:
            return Response(
                {'error': f'Insufficient stock. Available: {variant.stock}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        variant.stock -= quantity
        variant.save()
        variant.product.update_total_stock()

        txn = StockTransaction.objects.create(
            product=variant.product,
            variant=variant,
            transaction_type=StockTransaction.TransactionType.SALE,
            quantity=quantity,
            note=note,
            created_by=request.user if request.user.is_authenticated else None
        )

        # Sync to Supabase
        try:
            update_variant(variant.id, {'stock': variant.stock})
        except Exception as e:
            print(f"Supabase sync error (sell variant stock): {e}")
        _sync_transaction(txn)

        return Response({
            'message': f'Sold {quantity} units of {variant.product.name} ({variant.variant_type}: {variant.variant_value})',
            'variant': ProductVariantSerializer(variant).data
        })

    @action(detail=True, methods=['post'])
    def restock(self, request, pk=None):
        """Restock a variant – add stock and create RESTOCK transaction."""
        serializer = RestockSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        quantity = serializer.validated_data['quantity']
        note = serializer.validated_data.get('note', '')
        
        if not settings.DEBUG:
            # Production: Work directly with Supabase
            try:
                variant = get_variant_by_id(int(pk))
                if not variant:
                    return Response({'error': 'Variant not found'}, status=status.HTTP_404_NOT_FOUND)
                
                new_stock = variant['stock'] + quantity
                update_variant(int(pk), {'stock': new_stock})
                
                # Create transaction in Supabase
                txn_data = {
                    'product_id': variant['product_id'],
                    'variant_id': int(pk),
                    'transaction_type': 'RESTOCK',
                    'quantity': quantity,
                    'note': note,
                }
                if request.user.is_authenticated:
                    txn_data['created_by_id'] = request.user.id
                create_transaction(txn_data)
                
                return Response({
                    'message': f'Restocked {quantity} units of {variant["variant_type"]}: {variant["variant_value"]}',
                    'variant': {**variant, 'stock': new_stock}
                })
            except Exception as e:
                return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        # Development: Use local SQLite
        variant = self.get_object()
        variant.stock += quantity
        variant.save()
        variant.product.update_total_stock()

        txn = StockTransaction.objects.create(
            product=variant.product,
            variant=variant,
            transaction_type=StockTransaction.TransactionType.RESTOCK,
            quantity=quantity,
            note=note,
            created_by=request.user if request.user.is_authenticated else None
        )

        # Sync to Supabase
        try:
            update_variant(variant.id, {'stock': variant.stock})
        except Exception as e:
            print(f"Supabase sync error (restock variant stock): {e}")
        _sync_transaction(txn)

        return Response({
            'message': f'Restocked {quantity} units of {variant.product.name} ({variant.variant_type}: {variant.variant_value})',
            'variant': ProductVariantSerializer(variant).data
        })

    @action(detail=True, methods=['patch'], url_path='update-stock')
    def update_stock(self, request, pk=None):
        """Update variant stock directly (for inline editing)."""
        new_stock = request.data.get('stock')
        if new_stock is None:
            return Response({'error': 'stock is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            new_stock = int(new_stock)
            if new_stock < 0:
                return Response({'error': 'stock must be non-negative'}, status=status.HTTP_400_BAD_REQUEST)
        except (ValueError, TypeError):
            return Response({'error': 'stock must be an integer'}, status=status.HTTP_400_BAD_REQUEST)
        
        if not settings.DEBUG:
            # Production: Update directly in Supabase
            try:
                variant = get_variant_by_id(int(pk))
                if not variant:
                    return Response({'error': 'Variant not found'}, status=status.HTTP_404_NOT_FOUND)
                
                update_variant(int(pk), {'stock': new_stock})
                return Response({'message': 'Stock updated', 'stock': new_stock})
            except Exception as e:
                return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        # Development: Use local SQLite
        variant = self.get_object()
        variant.stock = new_stock
        variant.save()
        variant.product.update_total_stock()
        
        # Sync to Supabase
        try:
            update_variant(variant.id, {'stock': new_stock})
        except Exception as e:
            print(f"Supabase sync error (update variant stock): {e}")
        
        return Response({'message': 'Stock updated', 'stock': new_stock})


# ─────────────────────────────────────────────
#  Categories
# ─────────────────────────────────────────────
class CategoriesView(APIView):
    """GET /api/products/categories/ – Return distinct categories."""
    def get(self, request):
        categories = (
            Product.objects.values_list('category', flat=True)
            .distinct().order_by('category')
        )
        return Response(list(categories))


# ─────────────────────────────────────────────
#  Revenue Report
# ─────────────────────────────────────────────
class RevenueReportView(APIView):
    """
    GET /api/reports/revenue/?period=daily|weekly|monthly
    Revenue = quantity x selling_price for SALE transactions only.
    """
    def get(self, request):
        period = request.query_params.get('period', 'daily')

        sales = StockTransaction.objects.filter(
            transaction_type=StockTransaction.TransactionType.SALE
        ).select_related('product', 'variant')

        grouped = {}
        for t in sales:
            unit_price = (
                t.variant.selling_price
                if t.variant and t.variant.selling_price
                else t.product.selling_price
            )
            revenue = float(t.quantity * unit_price)

            if period == 'weekly':
                day = t.created_at.date()
                key = day - timedelta(days=day.weekday())
            elif period == 'monthly':
                key = t.created_at.date().replace(day=1)
            else:
                key = t.created_at.date()

            if key not in grouped:
                grouped[key] = {'total_revenue': 0.0, 'total_quantity': 0}
            grouped[key]['total_revenue'] += revenue
            grouped[key]['total_quantity'] += t.quantity

        final_report = [
            {
                'date': date,
                'total_revenue': round(data['total_revenue'], 2),
                'total_quantity': data['total_quantity'],
            }
            for date, data in sorted(grouped.items())
        ]
        return Response(final_report)


# ─────────────────────────────────────────────
#  Top Products
# ─────────────────────────────────────────────
class TopProductsView(APIView):
    """
    GET /api/reports/top-products/?search=optional
    Top 5 products by units sold this week (Monday to today).
    """
    def get(self, request):
        today = timezone.now().date()
        start_of_week = today - timedelta(days=today.weekday())

        sales = StockTransaction.objects.filter(
            transaction_type=StockTransaction.TransactionType.SALE,
            created_at__date__gte=start_of_week,
            created_at__date__lte=today,
        ).select_related('product', 'variant')

        search = request.query_params.get('search', None)

        product_stats = {}
        for sale in sales:
            unit_price = (
                sale.variant.selling_price
                if sale.variant and sale.variant.selling_price
                else sale.product.selling_price
            )
            pid = sale.product.id
            if pid not in product_stats:
                product_stats[pid] = {
                    'product_id': pid,
                    'product_name': sale.product.name,
                    'total_units_sold': 0,
                    'total_revenue': 0.0,
                }
            product_stats[pid]['total_units_sold'] += sale.quantity
            product_stats[pid]['total_revenue'] += float(sale.quantity * unit_price)

        sorted_products = sorted(
            product_stats.values(),
            key=lambda x: x['total_units_sold'],
            reverse=True
        )[:5]

        for p in sorted_products:
            p['total_revenue'] = round(p['total_revenue'], 2)

        if search:
            search_lower = search.lower()
            filtered = [p for p in sorted_products if search_lower in p['product_name'].lower()]
            if not filtered:
                return Response({
                    'message': f'"{search}" not found in top 5 products this week',
                    'search_term': search,
                    'top_products': sorted_products,
                })
            return Response({
                'search_term': search,
                'highlighted_products': filtered,
                'top_products': sorted_products,
            })

        return Response(sorted_products)


# ─────────────────────────────────────────────
#  Sales History
# ─────────────────────────────────────────────
class SalesHistoryView(APIView):
    """
    GET /api/transactions/
    Supports: ?type=SALE|RESTOCK|ADJUSTMENT &start_date=YYYY-MM-DD &end_date=YYYY-MM-DD &product_id=1
    """
    def get(self, request):
        queryset = StockTransaction.objects.select_related('product', 'variant').all()

        trans_type = request.query_params.get('type', None)
        if trans_type:
            queryset = queryset.filter(transaction_type=trans_type)

        start_date = request.query_params.get('start_date', None)
        end_date = request.query_params.get('end_date', None)
        if start_date:
            queryset = queryset.filter(created_at__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__date__lte=end_date)

        product_id = request.query_params.get('product_id', None)
        if product_id:
            queryset = queryset.filter(product_id=product_id)

        queryset = queryset.order_by('-created_at')

        transactions = []
        for t in queryset[:500]:
            unit_price = (
                t.variant.selling_price
                if t.variant and t.variant.selling_price
                else t.product.selling_price
            )
            revenue = (
                float(t.quantity * unit_price)
                if t.transaction_type == StockTransaction.TransactionType.SALE
                else None
            )
            transactions.append({
                'id': t.id,
                'product_id': t.product.id,
                'product_name': t.product.name,
                'variant_id': t.variant_id,
                'variant_label': (
                    f"{t.variant.variant_type}: {t.variant.variant_value}"
                    if t.variant else None
                ),
                'transaction_type': t.transaction_type,
                'quantity': t.quantity,
                'unit_price': float(unit_price),
                'revenue': revenue,
                'note': t.note or '',
                'created_at': t.created_at.isoformat(),
            })

        return Response(transactions)


# ─────────────────────────────────────────────
#  Sales Summary
# ─────────────────────────────────────────────
class SalesSummaryView(APIView):
    """
    GET /api/transactions/summary/
    Returns: total_transactions, total_quantity_sold, total_revenue, average_sale_value
    """
    def get(self, request):
        start_date = request.query_params.get('start_date', None)
        end_date = request.query_params.get('end_date', None)

        queryset = StockTransaction.objects.filter(
            transaction_type=StockTransaction.TransactionType.SALE
        ).select_related('product', 'variant')

        if start_date:
            queryset = queryset.filter(created_at__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__date__lte=end_date)

        total_sales = queryset.count()
        total_quantity = queryset.aggregate(Sum('quantity'))['quantity__sum'] or 0

        total_revenue = 0.0
        for t in queryset:
            unit_price = (
                t.variant.selling_price
                if t.variant and t.variant.selling_price
                else t.product.selling_price
            )
            total_revenue += float(t.quantity * unit_price)

        avg_sale_value = total_revenue / total_sales if total_sales > 0 else 0

        return Response({
            'total_transactions': total_sales,
            'total_quantity_sold': total_quantity,
            'total_revenue': round(total_revenue, 2),
            'average_sale_value': round(avg_sale_value, 2),
        })


# ─────────────────────────────────────────────
#  Delete Transactions
# ─────────────────────────────────────────────
@api_view(['DELETE'])
def delete_transactions(request):
    """
    DELETE /api/transactions/
    Body: {"ids": [1, 2, 3]}  OR  {"clear_all": true}
    """
    clear_all = request.data.get('clear_all', False)

    if clear_all:
        count = StockTransaction.objects.count()
        StockTransaction.objects.all().delete()
        return Response({'message': f'Deleted {count} transactions', 'deleted_count': count})

    ids = request.data.get('ids', [])
    if not ids:
        return Response({'error': 'No transaction IDs provided'},
                        status=status.HTTP_400_BAD_REQUEST)

    deleted_count = StockTransaction.objects.filter(id__in=ids).delete()[0]
    return Response({'message': f'Deleted {deleted_count} transactions',
                     'deleted_count': deleted_count})


# ─────────────────────────────────────────────
#  Excel Export – Products
# ─────────────────────────────────────────────
@api_view(['GET'])
def export_products_excel(request):
    """GET /api/products/export/excel/"""
    if not OPENPYXL_AVAILABLE:
        return Response(
            {'error': 'openpyxl not installed. Run: pip install openpyxl'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    products = Product.objects.all().order_by('-created_at')
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Products"

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    thin_border = Border(
        left=Side(style='thin'), right=Side(style='thin'),
        top=Side(style='thin'), bottom=Side(style='thin')
    )

    headers = ['S.N', 'Product Name', 'Barcode', 'Category',
               'Stock', 'Min Stock', 'Cost Price', 'Selling Price', 'Status']
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center')
        cell.border = thin_border

    for row, product in enumerate(products, 2):
        ws.cell(row=row, column=1, value=row - 1).border = thin_border
        ws.cell(row=row, column=2, value=product.name).border = thin_border
        ws.cell(row=row, column=3, value=product.barcode or '').border = thin_border
        ws.cell(row=row, column=4, value=product.category or '').border = thin_border
        ws.cell(row=row, column=5, value=product.stock).border = thin_border
        ws.cell(row=row, column=6, value=product.min_stock).border = thin_border
        ws.cell(row=row, column=7, value=float(product.cost_price)).border = thin_border
        ws.cell(row=row, column=8, value=float(product.selling_price)).border = thin_border
        ws.cell(row=row, column=9, value=product.status).border = thin_border

    column_widths = [5, 30, 15, 15, 10, 10, 12, 12, 10]
    for i, width in enumerate(column_widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = width

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = (
        f'attachment; filename=Stock_Management_{datetime.now().strftime("%Y%m%d")}.xlsx'
    )
    wb.save(response)
    return response


# ─────────────────────────────────────────────
#  Excel Export – Transactions
# ─────────────────────────────────────────────
@api_view(['POST'])
def export_transactions_excel(request):
    """POST /api/transactions/export/excel/  Body: {"transactions": [...]}"""
    if not OPENPYXL_AVAILABLE:
        return Response(
            {'error': 'openpyxl not installed. Run: pip install openpyxl'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    transactions = request.data.get('transactions', [])
    if not transactions:
        return Response({'error': 'No transactions to export'},
                        status=status.HTTP_400_BAD_REQUEST)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sales History"

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="28a745", end_color="28a745", fill_type="solid")
    thin_border = Border(
        left=Side(style='thin'), right=Side(style='thin'),
        top=Side(style='thin'), bottom=Side(style='thin')
    )

    headers = ['S.N', 'Date', 'Time', 'Product', 'Type', 'Quantity', 'Unit Price', 'Total Value', 'Note']
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center')
        cell.border = thin_border

    for row, t in enumerate(transactions, 2):
        created_at = datetime.fromisoformat(t['created_at'].replace('Z', '+00:00'))
        ws.cell(row=row, column=1, value=row - 1).border = thin_border
        ws.cell(row=row, column=2, value=created_at.strftime('%Y-%m-%d')).border = thin_border
        ws.cell(row=row, column=3, value=created_at.strftime('%H:%M')).border = thin_border
        ws.cell(row=row, column=4, value=t['product_name']).border = thin_border
        ws.cell(row=row, column=5, value=t['transaction_type']).border = thin_border
        ws.cell(row=row, column=6, value=t['quantity']).border = thin_border
        ws.cell(row=row, column=7, value=float(t['unit_price'])).border = thin_border
        total_value = t.get('revenue')
        ws.cell(row=row, column=8,
                value=float(total_value) if total_value is not None else '').border = thin_border
        ws.cell(row=row, column=9, value=t.get('note') or '').border = thin_border

    column_widths = [5, 12, 10, 30, 12, 10, 12, 12, 25]
    for i, width in enumerate(column_widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = width

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = (
        f'attachment; filename=Sales_History_{datetime.now().strftime("%Y%m%d")}.xlsx'
    )
    wb.save(response)
    return response


# ─────────────────────────────────────────────
#  Google Sheets – Export
# ─────────────────────────────────────────────
@api_view(['POST'])
def sync_google_sheet(request):
    """
    POST /api/products/sync/google-sheets/
    Body: {"sheet_id": "...", "api_key": "..."}
    Sheet must be shared with "Anyone with the link can edit".
    """
    sheet_id = request.data.get('sheet_id')
    api_key = request.data.get('api_key')

    if not sheet_id or not api_key:
        return Response({'error': 'sheet_id and api_key are required'},
                        status=status.HTTP_400_BAD_REQUEST)

    try:
        products = Product.objects.all().order_by('-created_at')
        values = [
            ['Name', 'Barcode', 'Category', 'Stock', 'Min Stock',
             'Cost Price', 'Selling Price', 'Status', 'Last Updated']
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
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            ])

        range_name = f'Sheet1!A1:I{len(values)}'
        response = requests.put(
            f'https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{range_name}',
            params={'key': api_key, 'valueInputOption': 'USER_ENTERED'},
            json={'values': values}
        )

        if response.status_code == 200:
            return Response({
                'message': f'Successfully synced {len(products)} products to Google Sheets',
                'products_count': len(products),
            })

        error_detail = response.json() if response.text else {}
        error_message = error_detail.get('error', {}).get('message', response.text)

        if 'PERMISSION_DENIED' in str(error_message) or response.status_code == 403:
            return Response(
                {'error': 'Permission denied. Share your Google Sheet with "Anyone with the link can edit".'},
                status=status.HTTP_400_BAD_REQUEST
            )
        return Response({'error': f'Google Sheets API error: {error_message}'},
                        status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ─────────────────────────────────────────────
#  Google Sheets – Import
# ─────────────────────────────────────────────
@api_view(['POST'])
def import_from_google_sheet(request):
    """
    POST /api/products/import/google-sheets/
    Body: {"sheet_id": "...", "api_key": "...", "range": "Sheet1!A1:I100"}
    """
    sheet_id = request.data.get('sheet_id')
    api_key = request.data.get('api_key')
    range_name = request.data.get('range', 'Sheet1!A1:I100')

    if not sheet_id or not api_key:
        return Response({'error': 'sheet_id and api_key are required'},
                        status=status.HTTP_400_BAD_REQUEST)

    try:
        url = f'https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{range_name}'
        response = requests.get(url, params={'key': api_key})

        if response.status_code != 200:
            return Response({'error': f'Google Sheets API error: {response.text}'},
                            status=status.HTTP_400_BAD_REQUEST)

        values = response.json().get('values', [])
        if not values or len(values) < 2:
            return Response({'error': 'No data found in the specified range'},
                            status=status.HTTP_400_BAD_REQUEST)

        imported_count = 0
        errors = []

        for i, row in enumerate(values[1:], 2):
            try:
                if len(row) < 6:
                    errors.append(f'Row {i}: Not enough columns')
                    continue

                name = row[0] if len(row) > 0 else ''
                if not name:
                    errors.append(f'Row {i}: Product name is required')
                    continue

                barcode      = row[1] if len(row) > 1 else ''
                category     = row[2] if len(row) > 2 else ''
                stock        = int(row[3])   if len(row) > 3 and row[3] else 0
                min_stock    = int(row[4])   if len(row) > 4 and row[4] else 10
                cost_price   = float(row[5]) if len(row) > 5 and row[5] else 0
                selling_price= float(row[6]) if len(row) > 6 and row[6] else 0

                product, created = Product.objects.get_or_create(
                    name=name,
                    defaults={
                        'barcode': barcode, 'category': category,
                        'stock': stock, 'min_stock': min_stock,
                        'cost_price': cost_price, 'selling_price': selling_price,
                    }
                )

                if not created:
                    product.barcode       = barcode
                    product.category      = category
                    product.stock         = stock
                    product.min_stock     = min_stock
                    product.cost_price    = cost_price
                    product.selling_price = selling_price
                    product.save()

                # Sync to Supabase
                try:
                    if created:
                        create_product({
                            'id': product.id,
                            'name': product.name,
                            'barcode': product.barcode or '',
                            'category': product.category or '',
                            'stock': product.stock,
                            'min_stock': product.min_stock,
                            'cost_price': float(product.cost_price),
                            'selling_price': float(product.selling_price),
                            'created_at': product.created_at.isoformat(),
                        })
                    else:
                        update_product(product.id, {
                            'barcode': product.barcode or '',
                            'category': product.category or '',
                            'stock': product.stock,
                            'min_stock': product.min_stock,
                            'cost_price': float(product.cost_price),
                            'selling_price': float(product.selling_price),
                        })
                except Exception as sup_err:
                    print(f"Supabase sync error (import row {i}): {sup_err}")

                imported_count += 1

            except Exception as e:
                errors.append(f'Row {i}: {str(e)}')

        return Response({
            'message': f'Successfully imported {imported_count} products',
            'imported_count': imported_count,
            'errors': errors if errors else None,
        })

    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ─────────────────────────────────────────────
#  Template views (login-protected)
# ─────────────────────────────────────────────
@login_required
def index(request):
    return render(request, 'index.html')

@login_required
def low_stock(request):
    return render(request, 'low-stock.html')

@login_required
def sales_history(request):
    return render(request, 'sales-history.html')


# ─────────────────────────────────────────────
#  Auth views
# ─────────────────────────────────────────────
def user_login(request):
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
            return redirect(request.GET.get('next', 'index'))
        else:
            messages.error(request, 'Invalid username or password.')

    return render(request, 'login.html')


def user_signup(request):
    if request.user.is_authenticated:
        return redirect('index')

    if request.method == 'POST':
        username         = request.POST.get('username', '').strip()
        email            = request.POST.get('email', '').strip()
        password         = request.POST.get('password', '').strip()
        password_confirm = request.POST.get('confirm_password', '').strip()

        if not username or not email or not password:
            messages.error(request, 'All fields are required.')
            return render(request, 'signup.html')

        if password != password_confirm:
            messages.error(request, 'Passwords do not match.')
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

        User.objects.create_user(username=username, email=email, password=password)
        messages.success(request, 'Account created successfully! Please login.')
        return redirect('login')

    return render(request, 'signup.html')


def user_logout(request):
    logout(request)
    messages.success(request, 'You have been logged out.')
    return redirect('login')