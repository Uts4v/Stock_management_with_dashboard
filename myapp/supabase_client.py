"""
Supabase client configuration for Django.
Handles connection to Supabase PostgreSQL database.
"""
import os
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')


def get_supabase_client():
    """
    Returns a Supabase client instance.
    Only creates the client when called (lazy initialization).
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError(
            "SUPABASE_URL and SUPABASE_KEY environment variables are not set. "
            "Add them to your .env file or Render environment variables."
        )
    
    from supabase import create_client, Client
    client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return client


# ===== Product Operations =====

def get_all_products():
    """Fetch all products from Supabase with their variants."""
    client = get_supabase_client()
    response = client.table('myapp_product').select("*").execute()
    products = response.data
    
    if not products:
        return []
    
    # Fetch all variants
    variants_response = client.table('myapp_productvariant').select("*").execute()
    variants_by_product = {}
    for variant in variants_response.data:
        product_id = variant.get('product_id')
        if product_id not in variants_by_product:
            variants_by_product[product_id] = []
        variants_by_product[product_id].append(variant)
    
    # Attach variants to each product and compute status
    for product in products:
        product_id = product.get('id')
        product['variants'] = variants_by_product.get(product_id, [])
        product['has_variants'] = len(product['variants']) > 0
        
        # Compute status based on stock and min_stock
        stock = product.get('stock', 0)
        min_stock = product.get('min_stock', 0)
        if stock <= 0:
            product['status'] = 'Out of Stock'
        elif stock <= min_stock:
            product['status'] = 'Low'
        elif stock <= min_stock * 1.5:
            product['status'] = 'Near Low'
        else:
            product['status'] = 'OK'
        
        # Also compute is_low_stock flag
        product['is_low_stock'] = stock <= min_stock
    
    return products


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
        "*, myapp_product(name)"
    ).execute()
    return response.data


def get_variant_by_id(variant_id: int):
    """Fetch a single variant by ID."""
    client = get_supabase_client()
    response = client.table('myapp_productvariant').select(
        "*, myapp_product(name)"
    ).eq('id', variant_id).execute()
    return response.data[0] if response.data else None


def get_variants_by_product(product_id: int):
    """Fetch all variants for a specific product."""
    client = get_supabase_client()
    response = client.table('myapp_productvariant').select(
        "*, myapp_product(name)"
    ).eq('product_id', product_id).execute()
    return response.data


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