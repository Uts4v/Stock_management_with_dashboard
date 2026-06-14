from rest_framework import serializers
from .models import Product, ProductVariant, StockTransaction


class ProductVariantSerializer(serializers.ModelSerializer):
    """Serializer for ProductVariant model"""
    is_low_stock = serializers.BooleanField(read_only=True)
    status = serializers.CharField(read_only=True)
    effective_cost_price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    effective_selling_price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    
    class Meta:
        model = ProductVariant
        fields = [
            'id', 'product', 'variant_type', 'variant_value', 'barcode',
            'stock', 'min_stock', 'cost_price', 'selling_price',
            'is_low_stock', 'status', 'effective_cost_price', 'effective_selling_price',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'is_low_stock', 'status']


class ProductSerializer(serializers.ModelSerializer):
    """Serializer for Product model"""
    is_low_stock = serializers.BooleanField(read_only=True)
    is_near_low_stock = serializers.BooleanField(read_only=True)
    status = serializers.CharField(read_only=True)
    todays_stock = serializers.SerializerMethodField()
    variants = ProductVariantSerializer(many=True, read_only=True)
    has_variants = serializers.SerializerMethodField()
    
    class Meta:
        model = Product
        fields = [
            'id', 'name', 'category', 'barcode', 'stock', 'min_stock',
            'cost_price', 'selling_price', 'created_at',
            'is_low_stock', 'is_near_low_stock', 'status', 'todays_stock',
            'variants', 'has_variants'
        ]
        read_only_fields = ['id', 'created_at', 'is_low_stock', 'is_near_low_stock', 'status', 'todays_stock']
    
    def get_todays_stock(self, obj):
        """Get stock for today (same as stock for now, can be enhanced later)"""
        return obj.stock
    
    def get_has_variants(self, obj):
        """Check if product has variants"""
        return obj.variants.exists()


class StockTransactionSerializer(serializers.ModelSerializer):
    """Serializer for StockTransaction model"""
    product_name = serializers.CharField(source='product.name', read_only=True)
    variant_info = serializers.SerializerMethodField()
    
    class Meta:
        model = StockTransaction
        fields = [
            'id', 'product', 'product_name', 'variant', 'variant_info',
            'transaction_type', 'quantity', 'note', 'created_at', 'created_by'
        ]
        read_only_fields = ['id', 'created_at', 'created_by']
    
    def get_variant_info(self, obj):
        """Get variant info if exists"""
        if obj.variant:
            return f"{obj.variant.variant_type}: {obj.variant.variant_value}"
        return None


class SellSerializer(serializers.Serializer):
    """Serializer for sell action"""
    quantity = serializers.IntegerField(min_value=1)
    note = serializers.CharField(required=False, allow_blank=True)
    variant_id = serializers.IntegerField(required=False, allow_null=True)


class RestockSerializer(serializers.Serializer):
    """Serializer for restock action"""
    quantity = serializers.IntegerField(min_value=1)
    note = serializers.CharField(required=False, allow_blank=True)
    variant_id = serializers.IntegerField(required=False, allow_null=True)


class RevenueReportSerializer(serializers.Serializer):
    """Serializer for revenue report"""
    date = serializers.DateField()
    total_revenue = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_quantity = serializers.IntegerField()


class TopProductSerializer(serializers.Serializer):
    """Serializer for top products report"""
    product_id = serializers.IntegerField()
    product_name = serializers.CharField()
    total_units_sold = serializers.IntegerField()
    total_revenue = serializers.DecimalField(max_digits=12, decimal_places=2)


# ============================================================
# Serializers for Supabase data (Option 1 - dict-based)
# ============================================================

class ProductDictSerializer(serializers.Serializer):
    """Serializer for product data from Supabase (plain dict)."""
    id = serializers.IntegerField()
    name = serializers.CharField()
    category = serializers.CharField()
    barcode = serializers.CharField(allow_blank=True, allow_null=True)
    stock = serializers.IntegerField()
    min_stock = serializers.IntegerField()
    cost_price = serializers.DecimalField(max_digits=10, decimal_places=2, allow_null=True)
    selling_price = serializers.DecimalField(max_digits=10, decimal_places=2, allow_null=True)
    created_at = serializers.CharField(allow_null=True)
    # Computed fields from Supabase (if included in query)
    is_low_stock = serializers.BooleanField(required=False)
    is_near_low_stock = serializers.BooleanField(required=False)
    status = serializers.CharField(required=False)
    has_variants = serializers.BooleanField(required=False, default=False)


class ProductVariantDictSerializer(serializers.Serializer):
    """Serializer for variant data from Supabase (plain dict)."""
    id = serializers.IntegerField()
    product_id = serializers.IntegerField()
    variant_type = serializers.CharField()
    variant_value = serializers.CharField()
    barcode = serializers.CharField(allow_blank=True, allow_null=True)
    stock = serializers.IntegerField()
    min_stock = serializers.IntegerField()
    cost_price = serializers.DecimalField(max_digits=10, decimal_places=2, allow_null=True)
    selling_price = serializers.DecimalField(max_digits=10, decimal_places=2, allow_null=True)
    created_at = serializers.CharField(allow_null=True)
    updated_at = serializers.CharField(allow_null=True)
    # Computed fields from Supabase (if included in query)
    is_low_stock = serializers.BooleanField(required=False)
    status = serializers.CharField(required=False)
    effective_cost_price = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
    effective_selling_price = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)