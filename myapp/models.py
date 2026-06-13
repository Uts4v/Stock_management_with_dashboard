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
        if self.is_low_stock:
            return 'Low'
        elif self.is_near_low_stock:
            return 'Near Low'
        return 'OK'


class StockTransaction(models.Model):
    """Stock transaction model for tracking sales, restocks, and adjustments"""
    
    class TransactionType(models.TextChoices):
        SALE = 'SALE', 'Sale'
        RESTOCK = 'RESTOCK', 'Restock'
        ADJUSTMENT = 'ADJUSTMENT', 'Adjustment'

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='transactions')
    transaction_type = models.CharField(max_length=20, choices=TransactionType.choices)
    quantity = models.IntegerField()
    note = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.transaction_type} - {self.product.name} - {self.quantity}"


