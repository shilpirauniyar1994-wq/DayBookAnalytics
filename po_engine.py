"""
DayBook Analytics — Purchase Order Suggestion Engine
Calculates sales velocity, estimates stock, evaluates lead-time reorder points,
and generates supplier-grouped purchase orders.
"""

import pandas as pd
import datetime
import re
from typing import Dict, List, Tuple, Any, Optional

# ---------------------------------------------------------------------------
# Supplier Consolidation Aliases
# Chinese import suppliers shipping through the same agent are consolidated
# under a single unified supplier name for Purchase Order generation.
# ---------------------------------------------------------------------------
SUPPLIER_ALIASES = {
    'Ayreen': ['rara', 'maxra', 'ayreen'],
    'Ben': ['huabei', 'ben'],
}

def resolve_supplier_alias(party_name: str, voucher_no: str = "") -> str:
    """Map party names or invoice numbers to consolidated supplier name.
    All purchases with party name or invoice number beginning with rara, maxra, ayreen
    are consolidated under supplier 'Ayreen'.
    All purchases with party name or invoice number beginning with huabei, ben
    are consolidated under supplier 'Ben'.
    """
    p = re.sub(r'[^a-z0-9]', '', str(party_name or '').strip().lower())
    v = re.sub(r'[^a-z0-9]', '', str(voucher_no or '').strip().lower())
    for alias, prefixes in SUPPLIER_ALIASES.items():
        for prefix in prefixes:
            if p.startswith(prefix) or v.startswith(prefix) or (prefix == 'huabei' and ('huabei' in p or 'huabei' in v)):
                return alias
    return str(party_name).strip() if party_name else 'Unknown'

def to_date_obj(v) -> Optional[datetime.date]:
    """Helper to convert any date/datetime/string/Timestamp into a datetime.date."""
    if v is None or pd.isna(v):
        return None
    if isinstance(v, datetime.date) and not isinstance(v, datetime.datetime):
        return v
    if hasattr(v, 'date'):
        return v.date()
    if isinstance(v, str) and len(v) >= 10:
        try:
            return datetime.date.fromisoformat(v[:10])
        except Exception:
            return None
    return None

def calculate_sales_velocity(
    line_items_df: pd.DataFrame,
    lookback_days: int = 30,
    as_of_date: Optional[datetime.date] = None
) -> pd.DataFrame:
    """
    Calculate average daily and weekly sales velocity per product over the lookback window.
    """
    if line_items_df.empty:
        return pd.DataFrame(columns=[
            'product_name', 'product_group', 'total_qty_sold',
            'total_revenue', 'selling_days', 'last_sale', 'daily_velocity', 'weekly_velocity'
        ])

    df = line_items_df.copy()
    df = df.assign(date_obj=df['date'].apply(to_date_obj))

    if as_of_date is None:
        valid_dates = df['date_obj'].dropna()
        as_of_date = max(valid_dates) if not valid_dates.empty else datetime.date.today()

    cutoff = as_of_date - datetime.timedelta(days=lookback_days)

    sales_mask = (df['voucher_category'] == 'Sales') & df['date_obj'].apply(lambda d: d >= cutoff if d else False)
    sales = df[sales_mask]

    if sales.empty:
        sales = df[df['voucher_category'] == 'Sales']
        valid_dates = df['date_obj'].dropna()
        period_days = max(1, (as_of_date - min(valid_dates)).days) if not valid_dates.empty else lookback_days
        actual_lookback = period_days
    else:
        actual_lookback = max(1, lookback_days)

    velocity = sales.groupby(['product_name', 'product_group']).agg(
        total_qty_sold=('quantity', 'sum'),
        total_revenue=('amount', 'sum'),
        selling_days=('date_obj', 'nunique'),
        last_sale=('date_obj', 'max'),
    ).reset_index()

    velocity = velocity.assign(
        daily_velocity=velocity['total_qty_sold'] / float(actual_lookback),
        weekly_velocity=(velocity['total_qty_sold'] / float(actual_lookback)) * 7.0
    )

    return velocity

def estimate_current_stock(
    line_items_df: pd.DataFrame,
    opening_stock_df: Optional[pd.DataFrame] = None
) -> pd.DataFrame:
    """
    Estimate stock per product = Opening Stock + Total Purchases - Total Sales.
    Categorizes all products into the 6 official business categories:
    Big Toys, Birthday Items, Factory Item, Fancy Toys, General, Indian Item.
    """
    from stksum_parser import infer_product_group

    if opening_stock_df is None:
        try:
            import db
            opening_stock_df = db.get_opening_stock_df()
        except Exception:
            opening_stock_df = pd.DataFrame()

    df = line_items_df.copy() if not line_items_df.empty else pd.DataFrame()

    if not df.empty:
        purchases = df[df['voucher_category'] == 'Purchase'] \
            .groupby('product_name')['quantity'].sum().rename('qty_purchased')
        sales = df[df['voucher_category'] == 'Sales'] \
            .groupby('product_name')['quantity'].sum().rename('qty_sold')
    else:
        purchases = pd.Series(dtype=float, name='qty_purchased')
        sales = pd.Series(dtype=float, name='qty_sold')

    if opening_stock_df is not None and not opening_stock_df.empty and 'product_name' in opening_stock_df.columns:
        op_qty = opening_stock_df.groupby('product_name')['opening_qty'].sum().rename('opening_qty')
        op_val = opening_stock_df.groupby('product_name')['opening_value'].sum().rename('opening_value') if 'opening_value' in opening_stock_df.columns else pd.Series(dtype=float, name='opening_value')
        op_rate = opening_stock_df.groupby('product_name')['opening_rate'].mean().rename('opening_rate') if 'opening_rate' in opening_stock_df.columns else pd.Series(dtype=float, name='opening_rate')
    else:
        op_qty = pd.Series(dtype=float, name='opening_qty')
        op_val = pd.Series(dtype=float, name='opening_value')
        op_rate = pd.Series(dtype=float, name='opening_rate')

    # Merge opening stock, purchases, and sales
    stock = pd.DataFrame({
        'opening_qty': op_qty,
        'qty_purchased': purchases,
        'qty_sold': sales,
        'opening_value': op_val,
        'opening_rate': op_rate,
    }).fillna(0.0).copy()

    # Fundamental Stock Formula: Opening Stock + Total Purchases - Total Sales
    stock = stock.assign(est_stock=stock['opening_qty'] + stock['qty_purchased'] - stock['qty_sold'])
    stock = stock.reset_index().rename(columns={'index': 'product_name'})
    stock = stock.assign(product_group=stock['product_name'].apply(infer_product_group))

    return stock

def calculate_aging(
    line_items_df: pd.DataFrame,
    opening_stock_df: Optional[pd.DataFrame] = None,
    as_of_date: Optional[datetime.date] = None
) -> pd.DataFrame:
    """
    Calculate inventory aging metrics using Opening Stock + Purchases - Sales.
    Classifies all products into the 6 official business categories.
    """
    from stksum_parser import infer_product_group

    if opening_stock_df is None:
        try:
            import db
            opening_stock_df = db.get_opening_stock_df()
        except Exception:
            opening_stock_df = pd.DataFrame()

    df = line_items_df.copy() if not line_items_df.empty else pd.DataFrame()
    if not df.empty:
        df = df.assign(date_obj=df['date'].apply(to_date_obj))

    if as_of_date is None:
        valid_dates = df['date_obj'].dropna() if not df.empty else pd.Series(dtype=object)
        as_of_date = max(valid_dates) if not valid_dates.empty else datetime.date.today()

    if not df.empty:
        purchases = df[df['voucher_category'] == 'Purchase']
        sales = df[df['voucher_category'] == 'Sales']

        purch_agg = purchases.groupby('product_name').agg(
            qty_purchased=('quantity', 'sum'),
            last_purchase=('date_obj', 'max'),
            purchase_count=('product_name', 'count'),
        ).reset_index()

        sales_agg = sales.groupby('product_name').agg(
            qty_sold=('quantity', 'sum'),
            last_sale=('date_obj', 'max'),
            sale_count=('product_name', 'count'),
        ).reset_index()
    else:
        purch_agg = pd.DataFrame(columns=['product_name', 'qty_purchased', 'last_purchase', 'purchase_count'])
        sales_agg = pd.DataFrame(columns=['product_name', 'qty_sold', 'last_sale', 'sale_count'])

    # Opening stock lookup
    if opening_stock_df is not None and not opening_stock_df.empty and 'product_name' in opening_stock_df.columns:
        op_agg = opening_stock_df.groupby('product_name').agg(
            opening_qty=('opening_qty', 'sum'),
            opening_rate=('opening_rate', 'mean') if 'opening_rate' in opening_stock_df.columns else ('opening_qty', lambda x: 0.0),
            opening_value=('opening_value', 'sum') if 'opening_value' in opening_stock_df.columns else ('opening_qty', lambda x: 0.0),
        ).reset_index()
    else:
        op_agg = pd.DataFrame(columns=['product_name', 'opening_qty', 'opening_rate', 'opening_value'])

    # Combine opening stock, purchases, and sales
    merged = op_agg.merge(purch_agg, on='product_name', how='outer')
    aging = merged.merge(sales_agg, on='product_name', how='outer').copy()

    aging = aging.assign(
        opening_qty=aging['opening_qty'].fillna(0.0),
        qty_purchased=aging['qty_purchased'].fillna(0.0),
        qty_sold=aging['qty_sold'].fillna(0.0),
        purchase_count=aging['purchase_count'].fillna(0).astype(int),
        sale_count=aging['sale_count'].fillna(0).astype(int),
    )

    # Fundamental Stock Formula: Opening Stock + Total Purchases - Total Sales
    aging = aging.assign(
        est_stock=aging['opening_qty'] + aging['qty_purchased'] - aging['qty_sold'],
        product_group=aging['product_name'].apply(infer_product_group)
    )

    # Days since movement
    # If item has opening stock but no new purchase date, default to opening date June 15, 2025
    op_date = datetime.date(2025, 6, 15)
    def compute_purchase_days(last_date, op_q):
        if pd.notna(last_date) and last_date is not None:
            return (as_of_date - last_date).days
        elif op_q > 0:
            return (as_of_date - op_date).days
        return 9999

    def compute_sale_days(last_date):
        if pd.isna(last_date) or last_date is None:
            return 9999
        return (as_of_date - last_date).days

    sale_days = aging['last_sale'].apply(compute_sale_days)
    purch_days = [
        compute_purchase_days(d, q) for d, q in zip(aging['last_purchase'], aging['opening_qty'])
    ]

    def assign_bucket(days):
        if days <= 30:
            return '0-30 days'
        elif days <= 60:
            return '31-60 days'
        elif days <= 90:
            return '61-90 days'
        elif days <= 180:
            return '91-180 days'
        elif days <= 360:
            return '181-360 days'
        elif days < 9999:
            return '360+ days'
        else:
            return 'Never Sold'

    aging = aging.assign(
        days_since_sale=sale_days,
        days_since_purchase=purch_days,
        aging_bucket=sale_days.apply(assign_bucket)
    )
    return aging.sort_values('days_since_sale', ascending=False)

def resolve_lead_time(
    product_name: str,
    supplier: str,
    product_group: str,
    config_df: Optional[pd.DataFrame] = None
) -> Tuple[int, int]:
    """
    Resolve lead time days and safety stock days with hierarchy:
    product_group override -> supplier override -> global default (7 days lead, 3 days safety)
    """
    if config_df is None or config_df.empty:
        return 7, 3

    # 1. Product group config
    if 'config_type' in config_df.columns:
        grp_cfg = config_df[(config_df['config_type'] == 'product_group') & (config_df['config_key'] == product_group)]
        if not grp_cfg.empty:
            r = grp_cfg.iloc[0]
            return int(r['lead_time_days']), int(r['safety_stock_days'])

        # 2. Supplier config
        sup_cfg = config_df[(config_df['config_type'] == 'supplier') & (config_df['config_key'].astype(str).str.lower() == str(supplier).lower())]
        if not sup_cfg.empty:
            r = sup_cfg.iloc[0]
            lead_d = int(r['lead_time_days'])
            safety_d = int(r['safety_stock_days'])
            if str(supplier).lower() == 'ben' and lead_d <= 14:
                hb_cfg = config_df[(config_df['config_type'] == 'supplier') & (config_df['config_key'].astype(str).str.lower() == 'huabei')]
                if not hb_cfg.empty:
                    return int(hb_cfg.iloc[0]['lead_time_days']), int(hb_cfg.iloc[0]['safety_stock_days'])
            return lead_d, safety_d

        # Fallback for Ben to Huabei config if not found
        if str(supplier).lower() == 'ben':
            hb_cfg = config_df[(config_df['config_type'] == 'supplier') & (config_df['config_key'].astype(str).str.lower() == 'huabei')]
            if not hb_cfg.empty:
                return int(hb_cfg.iloc[0]['lead_time_days']), int(hb_cfg.iloc[0]['safety_stock_days'])

        # 3. Global default
        def_cfg = config_df[config_df['config_type'] == 'default']
        if not def_cfg.empty:
            r = def_cfg.iloc[0]
            return int(r['lead_time_days']), int(r['safety_stock_days'])

    return 7, 3

def generate_po_suggestions(
    line_items_df: pd.DataFrame,
    supplier_products_df: Optional[pd.DataFrame] = None,
    lead_time_config_df: Optional[pd.DataFrame] = None,
    rmb_mappings_df: Optional[pd.DataFrame] = None,
    lookback_days: int = 30,
    cover_days: int = 60,
    seasonal_factor: float = 1.0,
) -> pd.DataFrame:
    """
    Generate automated PO suggestions based on sales velocity, estimated stock,
    reorder points, supplier mappings, and RMB commercial invoice pricing.
    """
    import math

    velocity_df = calculate_sales_velocity(line_items_df, lookback_days)
    stock_df = estimate_current_stock(line_items_df)

    if velocity_df.empty:
        return pd.DataFrame()

    merged = velocity_df.merge(stock_df, on='product_name', how='left').fillna(0)

    # Attach supplier information
    if supplier_products_df is not None and not supplier_products_df.empty:
        sp = supplier_products_df.copy()
        if 'is_preferred' in sp.columns and sp['is_preferred'].any():
            preferred = sp[sp['is_preferred'] == True]
            remaining = sp[~sp['product_name'].isin(preferred['product_name'])].sort_values('purchase_count', ascending=False).drop_duplicates('product_name')
            suppliers_map = pd.concat([preferred, remaining])
        else:
            suppliers_map = sp.sort_values('purchase_count', ascending=False).drop_duplicates('product_name')

        cols_to_merge = ['product_name', 'supplier_name', 'last_purchase_rate']
        available_cols = [c for c in cols_to_merge if c in suppliers_map.columns]
        merged = merged.merge(suppliers_map[available_cols], on='product_name', how='left')
    else:
        purchases = line_items_df[line_items_df['voucher_category'] == 'Purchase'].copy()
        if not purchases.empty:
            purchases['supplier_name'] = purchases.apply(
                lambda r: resolve_supplier_alias(r.get('party_name', ''), r.get('voucher_no', '')),
                axis=1
            )
            sup_agg = purchases.groupby(['product_name', 'supplier_name']).agg(
                last_purchase_rate=('rate', 'last'),
                count=('product_name', 'count')
            ).reset_index()
            best_sup = sup_agg.sort_values('count', ascending=False).drop_duplicates('product_name')
            merged = merged.merge(best_sup[['product_name', 'supplier_name', 'last_purchase_rate']], on='product_name', how='left')
        else:
            merged['supplier_name'] = 'Unknown'
            merged['last_purchase_rate'] = 0.0

    merged = merged.assign(
        supplier_name=merged['supplier_name'].fillna('General Supplier'),
        last_purchase_rate=merged['last_purchase_rate'].fillna(0.0)
    )

    # Build RMB lookup if provided
    rmb_dict = {}
    if rmb_mappings_df is not None and not rmb_mappings_df.empty:
        for _, r in rmb_mappings_df.iterrows():
            rmb_dict[r['product_name']] = {
                'rmb_price': float(r['rmb_price']) if pd.notna(r.get('rmb_price')) else 0.0,
                'pcs_per_ctn': int(r['pcs_per_ctn']) if pd.notna(r.get('pcs_per_ctn')) and r['pcs_per_ctn'] else 0,
                'supplier_item_no': str(r.get('supplier_item_no', '')),
                'supplier_desc': str(r.get('supplier_desc', ''))
            }

    suggestions = []
    for _, row in merged.iterrows():
        v = row['daily_velocity'] * seasonal_factor
        if v <= 0:
            continue

        prod_name = row['product_name']
        group = row.get('product_group', 'Others')
        supplier = row.get('supplier_name', 'General Supplier')
        stock = row['est_stock']

        lead_days, safety_days = resolve_lead_time(prod_name, supplier, group, lead_time_config_df)
        reorder_point = v * (lead_days + safety_days)
        days_of_stock = (stock / v) if v > 0 else 9999.0

        # Check if reorder condition met (or stock is below buffer)
        if stock <= reorder_point or days_of_stock <= (lead_days + safety_days + 7):
            suggested_qty = max(0.0, (v * cover_days) - stock + (v * safety_days))
            if suggested_qty <= 0 and stock <= reorder_point:
                suggested_qty = reorder_point

            # Check for RMB mapping
            rmb_info = rmb_dict.get(prod_name)
            if rmb_info and rmb_info['rmb_price'] > 0:
                rate = rmb_info['rmb_price']
                currency = 'RMB ¥'
                pcs_ctn = rmb_info['pcs_per_ctn']
                item_no = rmb_info['supplier_item_no']
                cartons = int(math.ceil(suggested_qty / pcs_ctn)) if pcs_ctn > 0 else 0
                if pcs_ctn > 0:
                    suggested_qty = float(cartons * pcs_ctn)
            else:
                rate = float(row['last_purchase_rate'])
                currency = 'Rs.'
                pcs_ctn = 0
                item_no = ''
                cartons = 0

            amount = round(suggested_qty * rate, 2)

            if days_of_stock <= lead_days:
                urgency = 'Critical (Out of Stock Risk)'
            elif days_of_stock <= (lead_days + safety_days):
                urgency = 'Warning (Reorder Now)'
            else:
                urgency = 'Normal'

            suggestions.append({
                'product_name': prod_name,
                'supplier_item_no': item_no,
                'product_group': group,
                'supplier_name': supplier,
                'daily_velocity': round(v, 2),
                'weekly_velocity': round(row['weekly_velocity'] * seasonal_factor, 1),
                'est_stock': round(stock, 0),
                'days_of_stock': round(days_of_stock, 1),
                'lead_time_days': lead_days,
                'reorder_point': round(reorder_point, 0),
                'suggested_qty': round(suggested_qty, 0),
                'cartons': cartons,
                'pcs_per_ctn': pcs_ctn,
                'estimated_rate': round(rate, 2),
                'estimated_amount': amount,
                'currency': currency,
                'urgency': urgency,
            })

    res_df = pd.DataFrame(suggestions)
    if not res_df.empty:
        return res_df.sort_values('days_of_stock', ascending=True)
    return res_df

def export_po_to_excel(supplier: str, items_df: pd.DataFrame) -> bytes:
    """Generate a formatted Excel workbook in memory for the purchase order."""
    import io

    try:
        import xlsxwriter
        has_xlsxwriter = True
    except ImportError:
        has_xlsxwriter = False

    output = io.BytesIO()

    # Determine currency
    is_rmb = False
    if 'currency' in items_df.columns:
        is_rmb = items_df['currency'].astype(str).str.contains('RMB').any() or any(k in supplier.lower() for k in ('huabei', 'rara', 'maxra', 'ayreen', 'ben'))

    curr_sym = "¥" if is_rmb else "Rs. "

    if has_xlsxwriter:
        import xlsxwriter
        wb = xlsxwriter.Workbook(output, {'in_memory': True})
        ws = wb.add_worksheet('Purchase Order')

        title_fmt = wb.add_format({'bold': True, 'font_size': 16, 'font_color': '#1E3A8A'})
        meta_fmt = wb.add_format({'font_size': 10, 'font_color': '#475569'})
        header_fmt = wb.add_format({
            'bold': True, 'font_color': 'white', 'bg_color': '#2563EB',
            'border': 1, 'align': 'center', 'valign': 'vcenter'
        })
        cell_fmt = wb.add_format({'border': 1, 'valign': 'vcenter'})
        num_fmt = wb.add_format({'border': 1, 'num_format': '#,##0', 'align': 'right'})
        curr_fmt = wb.add_format({'border': 1, 'num_format': f'{curr_sym}#,##0.00', 'align': 'right'})
        total_fmt = wb.add_format({'bold': True, 'border': 1, 'bg_color': '#F1F5F9', 'num_format': f'{curr_sym}#,##0.00', 'align': 'right'})
        total_lbl = wb.add_format({'bold': True, 'border': 1, 'bg_color': '#F1F5F9', 'align': 'right'})

        ws.write(0, 0, f"Purchase Order — {supplier} ({'RMB Yuan' if is_rmb else 'NPR'})", title_fmt)
        ws.write(1, 0, f"Generated: {datetime.date.today().strftime('%d-%b-%Y')} | Buyer: Demo Khelauna | Currency: {curr_sym}", meta_fmt)

        headers = [
            "Item No / Code", "Product Name", "Order Qty (Pcs)", "Cartons (CTN)",
            f"Unit Rate ({curr_sym})", f"Total Amount ({curr_sym})", "Current Stock", "Days Left"
        ]
        for col_idx, h in enumerate(headers):
            ws.write(3, col_idx, h, header_fmt)

        start_row = 4
        for idx, (_, row) in enumerate(items_df.iterrows()):
            r = start_row + idx
            ws.write(r, 0, str(row.get('supplier_item_no', '')), cell_fmt)
            ws.write(r, 1, str(row['product_name']), cell_fmt)
            ws.write(r, 2, row['suggested_qty'], num_fmt)
            ws.write(r, 3, row.get('cartons', 0), num_fmt)
            ws.write(r, 4, row['estimated_rate'], curr_fmt)
            ws.write(r, 5, row['estimated_amount'], curr_fmt)
            ws.write(r, 6, row.get('est_stock', 0.0), num_fmt)
            ws.write(r, 7, row.get('days_of_stock', 0.0), num_fmt)

        total_r = start_row + len(items_df)
        ws.write(total_r, 0, "TOTAL", total_lbl)
        for c in range(1, 5):
            ws.write(total_r, c, "", total_lbl)
        total_amt = items_df['estimated_amount'].sum() if not items_df.empty else 0.0
        ws.write(total_r, 5, total_amt, total_fmt)
        for c in range(6, 8):
            ws.write(total_r, c, "", total_lbl)

        ws.set_column(0, 0, 18)
        ws.set_column(1, 1, 32)
        ws.set_column(2, 3, 14)
        ws.set_column(4, 5, 20)
        ws.set_column(6, 7, 14)

        wb.close()
    else:
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            export_cols = ['supplier_item_no', 'product_name', 'suggested_qty', 'cartons', 'estimated_rate', 'estimated_amount', 'currency']
            avail_cols = [c for c in export_cols if c in items_df.columns]
            items_df[avail_cols].to_excel(writer, sheet_name='Purchase Order', index=False)

    output.seek(0)
    return output.getvalue()
