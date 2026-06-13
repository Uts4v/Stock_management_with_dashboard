from rest_framework import serializers
from .models import Product, StockTransaction


class ProductSerializer(serializers.ModelSerializer):
    """Serializer for Product model"""
    is_low_stock = serializers.BooleanField(read_only=True)
    is_near_low_stock = serializers.BooleanField(read_only=True)
    status = serializers.CharField(read_only=True)
    todays_stock = serializers.SerializerMethodField()
    
    class Meta:
        model = Product
        fields = [
            'id', 'name', 'category', 'barcode', 'stock', 'min_stock',
            'cost_price', 'selling_price', 'created_at',
            'is_low_stock', 'is_near_low_stock', 'status', 'todays_stock'
        ]
        read_only_fields = ['id', 'created_at', 'is_low_stock', 'is_near_low_stock', 'status', 'todays_stock']
    
    def get_todays_stock(self, obj):
        """Get stock for today (same as stock for now, can be enhanced later)"""
        return obj.stock


class StockTransactionSerializer(serializers.ModelSerializer):
    """Serializer for StockTransaction model"""
    product_name = serializers.CharField(source='product.name', read_only=True)
    
    class Meta:
        model = StockTransaction
        fields = [
            'id', 'product', 'product_name', 'transaction_type',
            'quantity', 'note', 'created_at', 'created_by'
        ]
        read_only_fields = ['id', 'created_at', 'created_by']


class SellSerializer(serializers.Serializer):
    """Serializer for sell action"""
    quantity = serializers.IntegerField(min_value=1)
    note = serializers.CharField(required=False, allow_blank=True)


class RestockSerializer(serializers.Serializer):
    """Serializer for restock action"""
    quantity = serializers.IntegerField(min_value=1)
    note = serializers.CharField(required=False, allow_blank=True)


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