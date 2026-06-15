"""
Supabase client configuration for Django.
Handles connection to Supabase PostgreSQL database.
"""
import os
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')


_client = None


def get_supabase_client():
    """
    Returns a Supabase client instance (cached singleton).
    Only creates the client when called (lazy initialization).
    """
    global _client
    if _client is not None:
        return _client

    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError(
            "SUPABASE_URL and SUPABASE_KEY environment variables are not set. "
            "Add them to your .env file or Render environment variables."
        )
    
    from supabase import create_client, Client
    _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


def _compute_variant_fields(variant: dict, parent_product: dict = None):
    """Compute is_low_stock, status, effective_cost_price, and effective_selling_price for a variant."""
    stock = variant.get('stock', 0)
    min_stock = variant.get('min_stock', 5)
    
    variant['is_low_stock'] = stock < min_stock
    variant['status'] = 'Low' if variant['is_low_stock'] else 'OK'
    
    # Cost price
    cost_price = variant.get('cost_price')
    if cost_price is None and parent_product:
        cost_price = parent_product.get('cost_price')
    variant['effective_cost_price'] = cost_price
    
    # Selling price
    selling_price = variant.get('selling_price')
    if selling_price is None and parent_product:
        selling_price = parent_product.get('selling_price')
    variant['effective_selling_price'] = selling_price
    
    return variant


# ===== Product Operations =====

def _compute_product_fields(product: dict):
    """Compute has_variants, status, and low-stock flags for one product dict."""
    variants = product.get('variants') or []
    product['has_variants'] = len(variants) > 0

    stock = product.get('stock') or 0
    min_stock = product.get('min_stock') or 0
    if stock <= 0:
        product['status'] = 'Out of Stock'
    elif stock <= min_stock:
        product['status'] = 'Low'
    elif stock <= min_stock * 1.5:
        product['status'] = 'Near Low'
    else:
        product['status'] = 'OK'

    product['is_low_stock'] = stock <= min_stock
    return product


def _attach_variants_to_products(products: list):
    """Attach variants only for the products being returned, instead of loading all variants every time."""
    if not products:
        return []

    client = get_supabase_client()
    product_ids = [p.get('id') for p in products if p.get('id') is not None]
    variants_by_product = {}

    if product_ids:
        variants_response = (
            client.table('myapp_productvariant')
            .select('*')
            .in_('product_id', product_ids)
            .execute()
        )
        for variant in variants_response.data or []:
            product_id = variant.get('product_id')
            variants_by_product.setdefault(product_id, []).append(variant)

    for product in products:
        product_id = product.get('id')
        product_variants = variants_by_product.get(product_id, [])
        for v in product_variants:
            _compute_variant_fields(v, product)
        product['variants'] = product_variants
        _compute_product_fields(product)

    return products


def get_all_products():
    """Fetch all products from Supabase with their variants. Kept for backward compatibility."""
    return get_products_filtered()


def get_products_filtered(search: str = None, category: str = None, limit: int = None):
    """
    Fetch filtered products from Supabase with variants.
    This avoids fetching every product and filtering in Python.
    """
    client = get_supabase_client()
    query = client.table('myapp_product').select('*').order('created_at', desc=True)

    if search:
        safe = str(search).replace('%', '').replace(',', ' ').strip()
        if safe:
            query = query.or_(f"name.ilike.%{safe}%,category.ilike.%{safe}%")

    if category:
        query = query.eq('category', category)

    if limit:
        query = query.limit(int(limit))

    response = query.execute()
    products = response.data or []
    return _attach_variants_to_products(products)


def get_categories():
    """Fetch only product categories. This is much faster than loading products + variants."""
    client = get_supabase_client()
    response = client.table('myapp_product').select('category').execute()
    return sorted({p.get('category') for p in (response.data or []) if p.get('category')})


def get_product_by_id(product_id: int):
    """Fetch a single product by ID."""
    client = get_supabase_client()
    response = client.table('myapp_product').select("*").eq('id', product_id).execute()
    return response.data[0] if response.data else None


def create_product(data: dict):
    """
    Insert a new product into Supabase.
    
    data = {
        'name': str,
        'barcode': str,
        'category': str,
        'stock': int,
        'min_stock': int,
        'cost_price': float,
        'selling_price': float,
    }
    """
    client = get_supabase_client()
    response = client.table('myapp_product').insert(data).execute()
    return response.data


def update_product(product_id: int, data: dict):
    """Update an existing product by ID."""
    client = get_supabase_client()
    response = client.table('myapp_product').update(data).eq('id', product_id).execute()
    return response.data


def delete_product(product_id: int):
    """Delete a product by ID."""
    client = get_supabase_client()
    response = client.table('myapp_product').delete().eq('id', product_id).execute()
    return response.data


def get_low_stock_products(min_stock_threshold: int = None):
    """
    Fetch products where stock is below min_stock.
    If threshold provided, use that instead.
    """
    client = get_supabase_client()
    if min_stock_threshold:
        response = client.table('myapp_product').select("*").lt('stock', min_stock_threshold).execute()
    else:
        # stock less than min_stock column
        response = client.table('myapp_product').select("*").execute()
        # Filter in Python since Supabase doesn't support column-to-column comparison directly
        products = [p for p in response.data if p['stock'] < p['min_stock']]
        return products
    return response.data


# ===== Transaction Operations =====

def get_all_transactions():
    """Fetch all stock transactions with product info."""
    client = get_supabase_client()
    response = client.table('myapp_stocktransaction').select(
        "*, myapp_product(name, selling_price)"
    ).order('created_at', desc=True).execute()
    return response.data


def get_transactions_by_type(transaction_type: str):
    """
    Fetch transactions filtered by type.
    transaction_type: 'SALE', 'RESTOCK', or 'ADJUSTMENT'
    """
    client = get_supabase_client()
    response = client.table('myapp_stocktransaction').select(
        "*, myapp_product(name, selling_price)"
    ).eq('transaction_type', transaction_type).order('created_at', desc=True).execute()
    return response.data


def get_transactions_by_date_range(start_date: str, end_date: str):
    """
    Fetch transactions within a date range.
    start_date, end_date: 'YYYY-MM-DD' format
    """
    client = get_supabase_client()
    response = client.table('myapp_stocktransaction').select(
        "*, myapp_product(name, selling_price)"
    ).gte('created_at', start_date).lte('created_at', end_date).execute()
    return response.data


def create_transaction(data: dict):
    """
    Insert a new stock transaction.
    
    data = {
        'product_id': int,
        'variant_id': int (optional),
        'transaction_type': str,  # 'SALE', 'RESTOCK', 'ADJUSTMENT'
        'quantity': int,
        'note': str,
        'created_by_id': int (optional),
    }
    """
    client = get_supabase_client()
    # Add created_at timestamp
    from datetime import datetime, timezone
    insert_data = {
        'product_id': data.get('product_id'),
        'transaction_type': data.get('transaction_type'),
        'quantity': data.get('quantity'),
        'note': data.get('note', ''),
        'created_at': datetime.now(timezone.utc).isoformat(),
    }
    # Add optional fields only if they exist
    if 'variant_id' in data and data['variant_id']:
        insert_data['variant_id'] = data['variant_id']
    if 'created_by_id' in data and data['created_by_id']:
        insert_data['created_by_id'] = data['created_by_id']
    response = client.table('myapp_stocktransaction').insert(insert_data).execute()
    return response.data


def delete_transaction(transaction_id: int):
    """Delete a transaction by ID."""
    client = get_supabase_client()
    response = client.table('myapp_stocktransaction').delete().eq('id', transaction_id).execute()
    return response.data


def delete_all_transactions():
    """Delete all transactions — use with caution."""
    client = get_supabase_client()
    response = client.table('myapp_stocktransaction').delete().neq('id', 0).execute()
    return response.data


# ===== Revenue & Reports =====

def get_sales_revenue():
    """
    Fetch all SALE transactions with product prices for revenue calculation.
    """
    client = get_supabase_client()
    response = client.table('myapp_stocktransaction').select(
        "id, quantity, created_at, myapp_product(name, selling_price)"
    ).eq('transaction_type', 'SALE').order('created_at').execute()
    return response.data


def get_top_products_this_week(start_of_week: str, today: str):
    """
    Fetch sales from start of week to today for top products report.
    start_of_week, today: 'YYYY-MM-DD' format
    """
    client = get_supabase_client()
    response = client.table('myapp_stocktransaction').select(
        "quantity, product_id, myapp_product(name, selling_price)"
    ).eq('transaction_type', 'SALE').gte(
        'created_at', start_of_week
    ).lte('created_at', today).execute()
    return response.data


# ===== User Operations =====

def get_user_by_username(username: str):
    """Fetch a Django auth user by username."""
    client = get_supabase_client()
    response = client.table('auth_user').select(
        "id, username, email, first_name, last_name, date_joined, is_staff"
    ).eq('username', username).execute()
    return response.data[0] if response.data else None


# ===== ProductVariant Operations =====

def get_all_variants():
    """Fetch all product variants from Supabase."""
    client = get_supabase_client()
    response = client.table('myapp_productvariant').select(
        "*, myapp_product(name, cost_price, selling_price)"
    ).execute()
    variants = response.data or []
    for v in variants:
        parent = v.get('myapp_product') or {}
        _compute_variant_fields(v, parent)
    return variants


def get_variant_by_id(variant_id: int):
    """Fetch a single variant by ID."""
    client = get_supabase_client()
    response = client.table('myapp_productvariant').select(
        "*, myapp_product(name, cost_price, selling_price)"
    ).eq('id', variant_id).execute()
    if response.data:
        v = response.data[0]
        parent = v.get('myapp_product') or {}
        _compute_variant_fields(v, parent)
        return v
    return None


def get_variants_by_ids(variant_ids: list):
    """Fetch multiple variants by their IDs in a single query."""
    if not variant_ids:
        return []
    client = get_supabase_client()
    response = client.table('myapp_productvariant').select(
        "*, myapp_product(name, cost_price, selling_price)"
    ).in_('id', variant_ids).execute()
    variants = response.data or []
    for v in variants:
        parent = v.get('myapp_product') or {}
        _compute_variant_fields(v, parent)
    return variants


def get_variants_by_product(product_id: int):
    """Fetch all variants for a specific product."""
    client = get_supabase_client()
    response = client.table('myapp_productvariant').select(
        "*, myapp_product(name, cost_price, selling_price)"
    ).eq('product_id', product_id).execute()
    variants = response.data or []
    for v in variants:
        parent = v.get('myapp_product') or {}
        _compute_variant_fields(v, parent)
    return variants


def create_variant(data: dict):
    """
    Insert a new product variant into Supabase.
    
    data = {
        'product_id': int,
        'variant_type': str,
        'variant_value': str,
        'stock': int,
        'min_stock': int,
        'cost_price': float,
        'selling_price': float,
        'barcode': str,
    }
    """
    client = get_supabase_client()
    response = client.table('myapp_productvariant').insert(data).execute()
    return response.data


def update_variant(variant_id: int, data: dict):
    """Update an existing variant by ID."""
    client = get_supabase_client()
    response = client.table('myapp_productvariant').update(data).eq('id', variant_id).execute()
    return response.data


def delete_variant(variant_id: int):
    """Delete a variant by ID."""
    client = get_supabase_client()
    response = client.table('myapp_productvariant').delete().eq('id', variant_id).execute()
    return response.data