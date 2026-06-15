from django.db import models
from django.contrib.auth.models import User


class Product(models.Model):
    """Product model for stock management"""
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=100, blank=True, default='')
    barcode = models.CharField(max_length=100, blank=True, default='')
    stock = models.IntegerField(default=0)
    min_stock = models.IntegerField(default=10)
    cost_price = models.DecimalField(max_digits=10, decimal_places=2)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Products"
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    @property
    def is_low_stock(self):
        return self.stock < self.min_stock

    @property
    def is_near_low_stock(self):
        return self.min_stock <= self.stock < (self.min_stock * 1.5)

    @property
    def status(self):
        if self.stock <= 0:
            return 'Out of Stock'
        if self.is_low_stock:
            return 'Low'
        elif self.is_near_low_stock:
            return 'Near Low'
        return 'OK'

    def update_total_stock(self):
        """Update the parent product's total stock based on sum of variants"""
        total = self.variants.aggregate(total=models.Sum('stock'))['total'] or 0
        self.stock = total
        self.save(update_fields=['stock'])


class ProductVariant(models.Model):
    """Product variant model for managing product variations (size, weight, color, etc.)"""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    variant_type = models.CharField(max_length=50, default='weight')
    variant_value = models.CharField(max_length=100)
    barcode = models.CharField(max_length=100, blank=True, default='')
    stock = models.IntegerField(default=0)
    min_stock = models.IntegerField(default=5)
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['variant_type', 'variant_value']
        unique_together = ['product', 'variant_type', 'variant_value']

    def __str__(self):
        return f"{self.product.name} - {self.variant_value}"

    @property
    def is_low_stock(self):
        return self.stock < self.min_stock

    @property
    def status(self):
        if self.stock <= 0:
            return 'Out of Stock'
        if self.is_low_stock:
            return 'Low'
        return 'OK'

    def get_effective_cost_price(self):
        """Get variant cost price or fall back to parent product"""
        return self.cost_price if self.cost_price is not None else self.product.cost_price

    def get_effective_selling_price(self):
        """Get variant selling price or fall back to parent product"""
        return self.selling_price if self.selling_price is not None else self.product.selling_price


class StockTransaction(models.Model):
    """Stock transaction model for tracking sales, restocks, and adjustments"""
    class TransactionType(models.TextChoices):
        SALE = 'SALE', 'Sale'
        RESTOCK = 'RESTOCK', 'Restock'
        ADJUSTMENT = 'ADJUSTMENT', 'Adjustment'

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='transactions')
    variant = models.ForeignKey(ProductVariant, on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions')
    transaction_type = models.CharField(max_length=20, choices=TransactionType.choices)
    quantity = models.IntegerField()
    note = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        variant_info = f" ({self.variant.variant_value})" if self.variant else ""
        return f"{self.transaction_type} - {self.product.name}{variant_info} - {self.quantity}"
