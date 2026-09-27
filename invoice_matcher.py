"""
DayBook Analytics — Commercial Invoice Parser, Matcher & Archival Engine
Parses supplier commercial invoices (Huabei, Rara, VG, Yiao, etc.), extracts RMB prices,
carton pack sizes, and total shipment quantities. Features two-stage hierarchical matching:
  Stage 1: Macro-matches invoice to the physical DayBook Purchase Voucher.
  Stage 2: Micro-matches invoice line items against voucher items with quantity & landed cost checks.
Stores unique derived items in persistent database and archives processed spreadsheets.
"""

import os
import shutil
import re
import datetime
import gc
import pandas as pd
from typing import List, Dict, Any, Tuple, Optional
from difflib import SequenceMatcher

import db

ARCHIVE_DIR_NAME = "archive"

def clean_str(s: Any) -> str:
    """Normalize a string to lowercase alphanumeric characters only."""
    return re.sub(r'[^a-zA-Z0-9]', '', str(s or '').lower())

def similarity(a: str, b: str) -> float:
    """Compute string similarity ratio between two cleaned strings."""
    s_a = clean_str(a)
    s_b = clean_str(b)
    if not s_a or not s_b:
        return 0.0
    if s_a == s_b or s_a in s_b or s_b in s_a:
        return 1.0
    return SequenceMatcher(None, s_a, s_b).ratio()

def extract_model_or_code(text: str) -> Optional[str]:
    """Extract model numbers like 3398-1, 8288-1A, BL627066 from strings, ignoring carton box marks."""
    if not text or pd.isna(text):
        return None
    # Check for Model NO: pattern
    m = re.search(r'model\s*no\s*[:：]\s*([a-zA-Z0-9\-_/]+)', str(text), re.IGNORECASE)
    if m:
        return m.group(1).strip()
    # Check for standard model codes like 168-15, 3398-1, but not shipping marks like A1-A40 or D1-D150
    m2 = re.search(r'\b[a-zA-Z0-9]{2,6}-[a-zA-Z0-9]{1,4}\b', str(text))
    if m2:
        val = m2.group(0).strip()
        if not re.match(r'^[A-Z]\d+-[A-Z]\d+$', val, re.IGNORECASE):
            return val
    return None

def get_unprocessed_invoices(folder: str = "commercial invoices") -> List[str]:
    """
    Return list of Excel invoice filenames in the folder that have not been archived yet.
    Excludes files inside archive/, temporary files starting with ~ or ., and non-excel files.
    """
    if not os.path.exists(folder):
        os.makedirs(folder, exist_ok=True)
        return []

    files = []
    for f in os.listdir(folder):
        full_p = os.path.join(folder, f)
        if os.path.isfile(full_p) and f.lower().endswith(('.xlsx', '.xls')) and not f.startswith(('~', '.')):
            files.append(f)
    return sorted(files)

def extract_invoice_metadata(filepath: str) -> Dict[str, Any]:
    """
    Extract document metadata from commercial invoice header rows and filename:
      - Supplier name (Huabei, Rara, Yiao, VG, Shivam, etc.)
      - Document / Invoice No (e.g. HB200114, VG 11th)
      - Container No (e.g. MSNU8457890)
      - Invoice Date (YYYY-MM-DD)
    """
    fname = os.path.basename(filepath)
    meta: Dict[str, Any] = {
        'file': fname,
        'supplier': '',
        'doc_no': '',
        'container_no': '',
        'date': None
    }

    # Extract date from filename if present (e.g. 2026.4.18, 2026-2-3)
    m_date = re.search(r'(\d{4})[.\-_](\d{1,2})[.\-_](\d{1,2})', fname)
    if m_date:
        meta['date'] = f"{m_date.group(1)}-{int(m_date.group(2)):02d}-{int(m_date.group(3)):02d}"

    # Extract doc hints from filename (e.g. VG 11th, VG 2nd)
    m_doc = re.search(r'VG\s*(\d+[a-z]*)', fname, re.IGNORECASE)
    if m_doc:
        meta['doc_no'] = m_doc.group(0).strip()

    try:
        with pd.ExcelFile(filepath) as xl:
            for sname in xl.sheet_names:
                df = xl.parse(sname, header=None, nrows=15)
                if df.empty:
                    continue
                text = ' '.join([str(x) for x in df.values.flatten() if pd.notna(x)])

                # Doc No
                m_d = re.search(r'Doc\s*No\s*[:：]\s*([a-zA-Z0-9\-_/]+)', text, re.IGNORECASE)
                if m_d:
                    meta['doc_no'] = m_d.group(1).strip()

                # Container No
                m_c = re.search(r'Container\s*No\s*[:：]\s*([a-zA-Z0-9]+)', text, re.IGNORECASE)
                if m_c:
                    meta['container_no'] = m_c.group(1).strip()

                # Invoice Date inside sheet
                m_dt = re.search(r'Date\s*[:：]\s*(\d{1,2})(?:st|nd|rd|th)?\s*[,.\s-]*([A-Za-z]+)\s*[,.\s-]*(\d{4})', text, re.IGNORECASE)
                if m_dt and not meta['date']:
                    try:
                        month_str = m_dt.group(2).strip()[:3]
                        d_obj = datetime.datetime.strptime(f"{m_dt.group(1)} {month_str} {m_dt.group(3)}", "%d %b %Y")
                        meta['date'] = d_obj.strftime("%Y-%m-%d")
                    except Exception:
                        pass

                # Supplier Detection
                t_lower = text.lower()
                if 'huabei' in t_lower:
                    meta['supplier'] = 'Huabei'
                elif 'yiao' in t_lower:
                    meta['supplier'] = 'Yiao'
                elif 'rara' in t_lower:
                    meta['supplier'] = 'Rara'
                elif 'shivam' in t_lower:
                    meta['supplier'] = 'Shivam'
    except Exception:
        pass

    # Fallback supplier from filename
    if not meta['supplier']:
        f_lower = fname.lower()
        if 'huabei' in f_lower or 'hb' in f_lower:
            meta['supplier'] = 'Huabei'
        elif 'rara' in f_lower:
            meta['supplier'] = 'Rara'
        elif 'vg' in f_lower:
            meta['supplier'] = 'Huabei'
        elif 'shivam' in f_lower:
            meta['supplier'] = 'Shivam'
        else:
            meta['supplier'] = 'Import Supplier'

    return meta

def parse_commercial_invoice(filepath: str) -> List[Dict[str, Any]]:
    """
    Intelligently parse a supplier commercial invoice and return extracted items.
    Handles Format 1 (Shantou Huabei standard) and Format 2 (VG Loaded List workbooks).
    Calculates exact per-piece RMB unit prices, master carton pack sizes,
    and total invoiced quantities and carton counts.
    """
    filename = os.path.basename(filepath)
    extracted_items = []
    meta = extract_invoice_metadata(filepath)
    supplier_name = meta.get('supplier') or "Import Supplier"

    try:
        with pd.ExcelFile(filepath) as xl:
            for sheet_name in xl.sheet_names:
                # Skip offload sheets if loaded list is present
                if 'offload' in sheet_name.lower() and any('loaded' in s.lower() for s in xl.sheet_names):
                    continue

                try:
                    df = xl.parse(sheet_name=sheet_name, header=None)
                except Exception:
                    continue

                if df.empty or len(df) < 2:
                    continue

                # ---------------------------------------------------------------------
                # FORMAT 1: Standard Shantou Huabei format (Headers around row 8: ITEM NO, Description, Price RMB, PCS/CTN, Total Quantity)
                # ---------------------------------------------------------------------
                header_row_idx = None
                for r in range(min(15, len(df))):
                    row_vals = [str(x).strip().lower() for x in df.iloc[r] if pd.notna(x)]
                    row_str = ' '.join(row_vals)
                    if 'item no' in row_str and ('price' in row_str or 'rmb' in row_str or 'pcs' in row_str):
                        header_row_idx = r
                        break

                if header_row_idx is not None:
                    header_row = df.iloc[header_row_idx]
                    sub_row = df.iloc[header_row_idx + 1] if header_row_idx + 1 < len(df) else None
                    has_sub = False
                    if sub_row is not None:
                        s_text = ' '.join([str(x).strip().lower() for x in sub_row if pd.notna(x)])
                        if 'ctns' in s_text or 'pcs' in s_text:
                            has_sub = True

                    col_item_no = None
                    col_desc = None
                    col_price = None
                    col_pcs = None
                    col_ctns = None
                    col_tqty = None
                    col_amt = None

                    for c_idx in range(len(header_row)):
                        v_head = str(header_row[c_idx]).strip().lower() if pd.notna(header_row[c_idx]) else ''
                        v_sub = str(sub_row[c_idx]).strip().lower() if sub_row is not None and c_idx < len(sub_row) and pd.notna(sub_row[c_idx]) else ''

                        if 'item no' in v_head or 'item_no' in v_head or 'model' in v_head:
                            col_item_no = c_idx
                        elif 'description' in v_head:
                            col_desc = c_idx
                        elif ('price' in v_head or 'unit' in v_head) and 'amount' not in v_head:
                            col_price = c_idx
                        elif 'pcs/ctn' in v_head or 'pcs / ctn' in v_head or (('pcs' in v_head or 'ctn' in v_head) and 'total' not in v_head and not col_pcs):
                            col_pcs = c_idx
                        elif 'amount' in v_head or 'amount' in v_sub:
                            col_amt = c_idx

                        if 'ctn' in v_sub:
                            col_ctns = c_idx
                        elif 'pcs' in v_sub:
                            col_tqty = c_idx

                    start_r = header_row_idx + 2 if has_sub else header_row_idx + 1
                    if col_item_no is not None and col_price is not None:
                        for r in range(start_r, len(df)):
                            row = df.iloc[r]
                            raw_item = row[col_item_no] if col_item_no < len(row) else None
                            raw_price = row[col_price] if col_price < len(row) else None

                            if pd.isna(raw_item) or pd.isna(raw_price):
                                continue

                            item_str = str(raw_item).strip()
                            if not item_str or item_str.lower() in ('total', 'subtotal', 'amount', 'ctns', 'pcs', 'nan'):
                                continue

                            # Clean price
                            try:
                                price_val = float(re.sub(r'[^\d.]', '', str(raw_price)))
                            except (ValueError, TypeError):
                                continue

                            if price_val <= 0:
                                continue

                            desc_val = str(row[col_desc]).strip() if col_desc is not None and col_desc < len(row) and pd.notna(row[col_desc]) else ''
                            pcs_val = 0
                            if col_pcs is not None and col_pcs < len(row) and pd.notna(row[col_pcs]):
                                try:
                                    pcs_val = int(float(re.sub(r'[^\d.]', '', str(row[col_pcs]))))
                                except Exception:
                                    pcs_val = 0

                            ctns_val = 0
                            if col_ctns is not None and col_ctns < len(row) and pd.notna(row[col_ctns]):
                                try:
                                    ctns_val = int(float(re.sub(r'[^\d.]', '', str(row[col_ctns]))))
                                except Exception:
                                    ctns_val = 0

                            tqty_val = 0
                            if col_tqty is not None and col_tqty < len(row) and pd.notna(row[col_tqty]):
                                try:
                                    tqty_val = int(float(re.sub(r'[^\d.]', '', str(row[col_tqty]))))
                                except Exception:
                                    tqty_val = 0
                            elif pcs_val > 0 and ctns_val > 0:
                                tqty_val = pcs_val * ctns_val

                            amt_val = 0.0
                            if col_amt is not None and col_amt < len(row) and pd.notna(row[col_amt]):
                                try:
                                    amt_val = float(re.sub(r'[^\d.]', '', str(row[col_amt])))
                                except Exception:
                                    amt_val = 0.0

                            extracted_items.append({
                                'supplier_name': supplier_name,
                                'invoice_file': filename,
                                'sheet_name': sheet_name,
                                'supplier_item_no': item_str,
                                'supplier_desc': desc_val,
                                'rmb_price': round(price_val, 3),
                                'pcs_per_ctn': pcs_val,
                                'invoiced_ctns': ctns_val,
                                'invoiced_qty': tqty_val,
                                'amount_rmb': round(amt_val, 2),
                                'doc_no': meta.get('doc_no', ''),
                                'container_no': meta.get('container_no', ''),
                                'invoice_date': meta.get('date', ''),
                                'raw_label': f"{item_str} {desc_val}".strip()
                            })
                        continue

                # ---------------------------------------------------------------------
                # FORMAT 2: VG Loaded List / Mark format (Row 0 has MARK, CTN NO., 품명, DESCRIPTION, CTN, PCS /CTN, T/QTY, PRICE, etc.)
                # ---------------------------------------------------------------------
                r0_str = ' '.join([str(x).lower() for x in df.iloc[0] if pd.notna(x)])
                if 'mark' in r0_str and ('price' in r0_str or 'amt' in r0_str or 'pcs' in r0_str or 'ctn' in r0_str):
                    col_mark = 0
                    col_pcs = None
                    col_price = None
                    col_amt = None
                    col_tqty = None
                    col_ctn = None

                    for c_idx, val in enumerate(df.iloc[0]):
                        v_str = str(val).strip().lower()
                        if 'pcs' in v_str and 'ctn' in v_str:
                            col_pcs = c_idx
                        elif v_str in ('price', 'unit price', 'price(rmb)', 'unitprice'):
                            col_price = c_idx
                        elif 'amt' in v_str or 'amount' in v_str:
                            col_amt = c_idx
                        elif 't/qty' in v_str or 'total qty' in v_str:
                            col_tqty = c_idx
                        elif v_str in ('ctn', 'ctns'):
                            col_ctn = c_idx

                    for r in range(1, len(df)):
                        row = df.iloc[r]
                        raw_mark = str(row[col_mark]).strip() if pd.notna(row[col_mark]) else ''
                        if not raw_mark or raw_mark.lower().startswith(('total', 'grand total', 'nan')):
                            continue

                        # Clean item description from MARK line (strip carton box info and prefix)
                        clean_desc = raw_mark.split('CTN NO')[0].strip()
                        clean_desc = re.sub(r'^VG[-\s]*', '', clean_desc, flags=re.IGNORECASE).strip()
                        if not clean_desc or clean_desc.lower() in ('total', 'nan'):
                            continue

                        # Extract model code if available; otherwise use clean name as code
                        item_code = ''
                        m = re.search(r'\b[A-Za-z0-9]{2,6}-[A-Za-z0-9]{1,4}\b', clean_desc)
                        if m and not re.match(r'^[A-Z]\d+-[A-Z]\d+$', m.group(0), re.IGNORECASE):
                            item_code = m.group(0).strip()
                        else:
                            item_code = clean_desc[:25].strip()

                        pcs_val = 0
                        if col_pcs is not None and col_pcs < len(row) and pd.notna(row[col_pcs]):
                            try:
                                pcs_val = int(float(re.sub(r'[^\d.]', '', str(row[col_pcs]))))
                            except Exception:
                                pcs_val = 0

                        ctn_val = 0
                        if col_ctn is not None and col_ctn < len(row) and pd.notna(row[col_ctn]):
                            try:
                                ctn_val = int(float(re.sub(r'[^\d.]', '', str(row[col_ctn]))))
                            except Exception:
                                ctn_val = 0

                        raw_p = 0.0
                        if col_price is not None and col_price < len(row) and pd.notna(row[col_price]):
                            try:
                                raw_p = float(re.sub(r'[^\d.]', '', str(row[col_price])))
                            except Exception:
                                raw_p = 0.0

                        amt_val = 0.0
                        if col_amt is not None and col_amt < len(row) and pd.notna(row[col_amt]):
                            try:
                                amt_val = float(re.sub(r'[^\d.]', '', str(row[col_amt])))
                            except Exception:
                                amt_val = 0.0

                        tqty_val = 0.0
                        if col_tqty is not None and col_tqty < len(row) and pd.notna(row[col_tqty]):
                            try:
                                tqty_val = float(re.sub(r'[^\d.]', '', str(row[col_tqty])))
                            except Exception:
                                tqty_val = 0.0

                        unit_price = 0.0
                        if raw_p > 0:
                            if raw_p > 35 and pcs_val > 5:
                                # Carton price entered in spreadsheet: compute per-piece unit price
                                unit_price = round(raw_p / pcs_val, 3)
                            else:
                                unit_price = round(raw_p, 3)
                        elif amt_val > 0 and tqty_val > 0:
                            unit_price = round(amt_val / tqty_val, 3)

                        if unit_price <= 0:
                            continue

                        extracted_items.append({
                            'supplier_name': supplier_name,
                            'invoice_file': filename,
                            'sheet_name': sheet_name,
                            'supplier_item_no': item_code,
                            'supplier_desc': clean_desc,
                            'rmb_price': unit_price,
                            'pcs_per_ctn': pcs_val,
                            'invoiced_ctns': ctn_val,
                            'invoiced_qty': int(tqty_val),
                            'amount_rmb': round(amt_val, 2),
                            'doc_no': meta.get('doc_no', ''),
                            'container_no': meta.get('container_no', ''),
                            'invoice_date': meta.get('date', ''),
                            'raw_label': raw_mark
                        })

    except Exception as e:
        print(f"Error parsing invoice {filepath}: {e}")
    finally:
        gc.collect()

    return extracted_items

def find_candidate_purchase_vouchers(
    invoice_items: List[Dict[str, Any]],
    metadata: Optional[Dict[str, Any]] = None,
    limit: int = 5
) -> List[Dict[str, Any]]:
    """
    Stage 1: Macro Matcher — Score DayBook Purchase Vouchers against the invoice.
    Uses multi-factor scoring:
      - 50% Item Code Overlap: proportion of invoice item codes present in voucher line items.
      - 25% Party / Document Name Match: similarity between invoice doc_no/supplier and voucher party/no.
      - 15% Transit Date Window: 10 to 75 days transit time between factory invoice and Nepal voucher.
      - 10% Item Count Correlation: ratio of item counts.
    Returns ranked list of candidate vouchers with confidence percentages.
    """
    if not invoice_items:
        return []

    if metadata is None:
        fname = invoice_items[0].get('invoice_file', '')
        metadata = {'file': fname, 'supplier': invoice_items[0].get('supplier_name', ''), 'doc_no': invoice_items[0].get('doc_no', ''), 'date': invoice_items[0].get('invoice_date')}

    v_df, li_df = db.load_local_data()
    if v_df.empty or li_df.empty:
        return []

    pv_df = v_df[v_df['voucher_category'] == 'Purchase'].copy()
    p_li_df = li_df[li_df['voucher_category'] == 'Purchase'].copy()
    if p_li_df.empty:
        return []

    # Extract invoice model codes
    item_codes = []
    for it in invoice_items:
        code = str(it.get('supplier_item_no', '')).strip()
        if code and len(code) >= 2:
            item_codes.append(clean_str(code))
        else:
            m = re.search(r'\b[a-zA-Z0-9]{2,6}-[a-zA-Z0-9]{1,4}\b', str(it.get('supplier_desc', '')))
            if m:
                item_codes.append(clean_str(m.group(0)))

    # Parse invoice date safely using standard library
    inv_date = None
    if metadata.get('date'):
        try:
            inv_date = datetime.date.fromisoformat(str(metadata['date'])[:10])
        except Exception:
            pass

    # Group purchase line items by voucher
    vouchers = []
    for (v_no, p_name), group in p_li_df.groupby(['voucher_no', 'party_name']):
        v_rows = pv_df[(pv_df['voucher_no'] == v_no) & (pv_df['party_name'] == p_name)]
        v_date = v_rows['date'].iloc[0] if not v_rows.empty else group['date'].iloc[0]
        c_amt = v_rows['credit_amount'].iloc[0] if not v_rows.empty else group['amount'].sum()
        prods = group['product_name'].dropna().tolist()
        prods_clean = [clean_str(p) for p in prods]

        vouchers.append({
            'voucher_no': str(v_no),
            'party_name': str(p_name),
            'date': str(v_date),
            'credit_amount': float(c_amt),
            'item_count': len(group),
            'products': prods,
            'prods_clean': prods_clean,
            'line_items': group
        })

    candidates = []
    for v in vouchers:
        # 1. Code overlap
        matches = 0
        if item_codes:
            for ic in item_codes:
                if any(ic in pc for pc in v['prods_clean']):
                    matches += 1
            s_codes = matches / len(item_codes)
        else:
            s_codes = 0.0

        # 2. Party & Doc Name score
        s_party = 0.0
        v_label = clean_str(f"{v['voucher_no']} {v['party_name']}")
        sup_clean = clean_str(metadata.get('supplier', ''))
        doc_clean = clean_str(metadata.get('doc_no', ''))

        if sup_clean and sup_clean in v_label:
            s_party = max(s_party, 0.70)
        if doc_clean and doc_clean in v_label:
            s_party = max(s_party, 0.95)

        # Check partial numbers e.g. HB200114 contains 14, voucher is Huabei 14
        m_num = re.search(r'(\d+)', str(metadata.get('doc_no', '')))
        if m_num:
            num_str = m_num.group(1)
            if num_str in v_label and ('huabei' in v_label or 'hb' in v_label or 'rara' in v_label):
                s_party = max(s_party, 0.85)

        # 3. Date score
        s_date = 0.50
        if inv_date and v['date']:
            try:
                vd = datetime.date.fromisoformat(str(v['date'])[:10])
                diff_days = (vd - inv_date).days
                if 10 <= diff_days <= 75:
                    s_date = 1.0
                elif 0 <= diff_days < 10:
                    s_date = 0.70
                elif 75 < diff_days <= 120:
                    s_date = 0.60
                elif -15 < diff_days < 0:
                    s_date = 0.30
                else:
                    s_date = 0.10
            except Exception:
                pass

        # 4. Count score
        count_ratio = 1.0 - min(abs(len(invoice_items) - v['item_count']) / max(len(invoice_items), v['item_count']), 1.0)

        # Weighted total score
        total_score = (0.50 * s_codes) + (0.25 * s_party) + (0.15 * s_date) + (0.10 * count_ratio)

        # Keep candidates with meaningful overlap or similarity
        if matches >= 2 or s_codes >= 0.15 or s_party >= 0.70:
            candidates.append({
                'voucher_no': v['voucher_no'],
                'party_name': v['party_name'],
                'date': v['date'],
                'credit_amount': v['credit_amount'],
                'item_count': v['item_count'],
                'overlap_count': matches,
                'overlap_ratio': round(s_codes, 3),
                'score': round(total_score, 3),
                'confidence_pct': int(round(total_score * 100)),
                'is_auto_matched': bool(total_score >= 0.70 and matches >= 4)
            })

    candidates.sort(key=lambda x: x['score'], reverse=True)
    return candidates[:limit]

def match_invoice_items_against_voucher(
    invoice_items: List[Dict[str, Any]],
    voucher_no: str,
    party_name: Optional[str] = None,
    saved_mappings: Optional[Dict[str, Any]] = None,
    tally_products: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """
    Stage 2: Micro Matcher — Constrains matching of invoice items to the ~25 line items
    present in the physical DayBook purchase voucher.
    Performs:
      1. Saved mappings memory check
      2. Exact code / model number matching (95% - 100% confidence)
      3. Exact quantity matching (invoiced_qty == voucher_qty) + description overlap (90% confidence)
      4. High-confidence fuzzy string matching within voucher items (80% confidence)
      5. Landed cost multiplier sanity check: Landed Rate (NPR) / Invoiced Price (RMB) ~ 18x to 45x
      6. Fallback to wider catalog if item not in voucher.
    """
    if saved_mappings is None:
        saved_mappings = {}

    v_df, li_df = db.load_local_data()
    v_mask = li_df['voucher_no'].astype(str).str.lower() == str(voucher_no).strip().lower()
    if party_name:
        v_mask = v_mask & (li_df['party_name'].astype(str).str.lower() == str(party_name).strip().lower())

    voucher_line_items = li_df[v_mask].copy()

    # Pre-clean voucher items
    v_items_list = []
    for _, r in voucher_line_items.iterrows():
        p_name = str(r['product_name'])
        v_items_list.append({
            'product_name': p_name,
            'clean_name': clean_str(p_name),
            'quantity': float(r.get('quantity', 0)),
            'rate': float(r.get('rate', 0.0)),
            'amount': float(r.get('amount', 0.0)),
            'voucher_no': str(r.get('voucher_no', voucher_no))
        })

    # Pre-clean all tally products for fallback
    tally_prods_clean = {p: clean_str(p) for p in (tally_products or [])}

    results = []

    for item in invoice_items:
        it_no = str(item.get('supplier_item_no', '')).strip()
        it_desc = str(item.get('supplier_desc', '')).strip()
        it_qty = float(item.get('invoiced_qty', 0))
        rmb_price = float(item.get('rmb_price', 0.0))
        c_code = clean_str(it_no)
        c_desc = clean_str(it_desc)
        target_label = f"{it_no} {it_desc}".strip()

        matched_prod = None
        v_qty = 0.0
        v_rate = 0.0
        match_type = "Unmatched"
        confidence = 0.0
        landed_multiplier = 0.0

        # 1. Saved mappings memory check first
        for t_prod, saved_info in saved_mappings.items():
            saved_no = str(saved_info.get('supplier_item_no', '')).strip()
            saved_d = str(saved_info.get('supplier_desc', '')).strip()
            if (saved_no and saved_no.lower() == it_no.lower()) or (saved_d and saved_d.lower() == it_desc.lower()):
                matched_prod = t_prod
                match_type = "Saved Memory"
                confidence = 1.0
                # Lookup rate from voucher items if present
                for vi in v_items_list:
                    if vi['product_name'] == matched_prod:
                        v_qty = vi['quantity']
                        v_rate = vi['rate']
                        break
                break

        # 2. Match within voucher line items
        if not matched_prod and v_items_list:
            best_score = 0.0
            best_vi = None
            best_reason = ""

            for vi in v_items_list:
                v_clean = vi['clean_name']
                item_v_qty = vi['quantity']

                # Priority 2a: Model code match
                if c_code and len(c_code) >= 2 and c_code in v_clean:
                    score = 0.95
                    reason = "Code Match"
                    if it_qty > 0 and abs(it_qty - item_v_qty) < 0.01:
                        score = 1.00
                        reason = "Exact Code + Qty Match"
                    if score > best_score:
                        best_score = score
                        best_vi = vi
                        best_reason = reason

                # Priority 2b: Exact quantity match + description overlap
                elif it_qty > 0 and abs(it_qty - item_v_qty) < 0.01:
                    sim = SequenceMatcher(None, c_desc, v_clean).ratio()
                    if sim > 0.30:
                        score = 0.90
                        reason = "Exact Qty + Sim Match"
                        if score > best_score:
                            best_score = score
                            best_vi = vi
                            best_reason = reason

                # Priority 2c: Fuzzy string match within voucher items
                else:
                    sim = SequenceMatcher(None, clean_str(target_label), v_clean).ratio()
                    if sim > 0.65 and sim > best_score:
                        best_score = sim
                        best_vi = vi
                        best_reason = "Voucher Fuzzy Match"

            if best_vi is not None and best_score >= 0.65:
                matched_prod = best_vi['product_name']
                v_qty = best_vi['quantity']
                v_rate = best_vi['rate']
                match_type = best_reason
                confidence = round(best_score, 2)

        # 3. Fallback to full Tally catalog if still unmatched
        if not matched_prod and tally_prods_clean:
            # Code match across full catalog
            if c_code and len(c_code) >= 3:
                for t_prod, t_clean in tally_prods_clean.items():
                    if c_code in t_clean:
                        matched_prod = t_prod
                        match_type = "Catalog Code Match"
                        confidence = 0.85
                        break

            # Fuzzy match across full catalog
            if not matched_prod:
                b_score = 0.0
                b_prod = None
                for t_prod, t_clean in tally_prods_clean.items():
                    score = similarity(target_label, t_prod)
                    if score > b_score:
                        b_score = score
                        b_prod = t_prod
                if b_score >= 0.75:
                    matched_prod = b_prod
                    match_type = "Catalog Fuzzy Match"
                    confidence = round(b_score, 2)

        # Compute Landed Cost Multiplier
        if matched_prod and v_rate > 0 and rmb_price > 0:
            landed_multiplier = round(v_rate / rmb_price, 1)

        # Multiplier sanity validation
        multiplier_healthy = bool(16.0 <= landed_multiplier <= 48.0) if landed_multiplier > 0 else True

        status = 'Pending'
        if match_type in ('Saved Memory', 'Exact Code + Qty Match', 'Code Match') and multiplier_healthy:
            status = 'Confirmed'
        elif confidence >= 0.85 and multiplier_healthy:
            status = 'Confirmed'

        results.append({
            'supplier_name': item.get('supplier_name', ''),
            'invoice_file': item.get('invoice_file', ''),
            'supplier_item_no': it_no,
            'supplier_desc': it_desc,
            'rmb_price': rmb_price,
            'pcs_per_ctn': item.get('pcs_per_ctn', 0),
            'invoiced_ctns': item.get('invoiced_ctns', 0),
            'invoiced_qty': int(it_qty),
            'amount_rmb': item.get('amount_rmb', 0.0),
            'matched_product_name': matched_prod,
            'voucher_no': voucher_no,
            'voucher_qty': v_qty,
            'voucher_rate': v_rate,
            'landed_multiplier': landed_multiplier,
            'multiplier_healthy': multiplier_healthy,
            'match_type': match_type,
            'confidence': confidence,
            'status': status
        })

    return results

def match_invoice_items_smart(
    invoice_items: List[Dict[str, Any]],
    metadata: Optional[Dict[str, Any]] = None,
    selected_voucher_no: Optional[str] = None,
    saved_mappings: Optional[Dict[str, Any]] = None,
    tally_products: Optional[List[str]] = None
) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Two-Stage Master Matching Coordinator:
      1. Automatically discovers candidate Purchase Vouchers in DayBook.
      2. If selected_voucher_no is provided, or if the top candidate has high confidence (>=70%),
         constrains item matching to that voucher.
      3. Returns (reconciled_items, active_voucher_dict, candidate_vouchers_list).
    """
    if metadata is None and invoice_items:
        metadata = extract_invoice_metadata(invoice_items[0].get('invoice_file', ''))

    candidate_vouchers = find_candidate_purchase_vouchers(invoice_items, metadata=metadata, limit=5)

    active_voucher = None
    if selected_voucher_no and selected_voucher_no != "-- None (Search Full Catalog) --":
        # User explicitly selected a voucher
        for cv in candidate_vouchers:
            if cv['voucher_no'] == selected_voucher_no:
                active_voucher = cv
                break
        if not active_voucher:
            active_voucher = {'voucher_no': selected_voucher_no, 'party_name': '', 'score': 1.0}
    elif candidate_vouchers and candidate_vouchers[0]['score'] >= 0.65:
        # Top auto-match voucher
        active_voucher = candidate_vouchers[0]

    if active_voucher:
        reconciled = match_invoice_items_against_voucher(
            invoice_items=invoice_items,
            voucher_no=active_voucher['voucher_no'],
            party_name=active_voucher.get('party_name'),
            saved_mappings=saved_mappings,
            tally_products=tally_products
        )
    else:
        # Full catalog match
        if tally_products is None:
            li_df = db.get_line_items_df()
            tally_products = sorted(li_df['product_name'].dropna().unique().tolist()) if not li_df.empty else []
        reconciled = match_invoice_items_to_tally(invoice_items, tally_products, saved_mappings)

    return reconciled, active_voucher, candidate_vouchers

def match_invoice_items_to_tally(
    invoice_items: List[Dict[str, Any]],
    tally_products: List[str],
    saved_mappings: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """
    Match invoice items across the full Tally catalog without voucher constraint.
    Maintained for backward compatibility and fallback mode.
    """
    if saved_mappings is None:
        saved_mappings = {}

    results = []
    tally_prods_clean = {p: clean_str(p) for p in tally_products}

    for item in invoice_items:
        it_no = str(item.get('supplier_item_no', '')).strip()
        it_desc = str(item.get('supplier_desc', '')).strip()

        matched_tally_prod = None
        match_type = "Unmatched"
        confidence = 0.0

        # 1. Check saved memory first
        for t_prod, saved_info in saved_mappings.items():
            saved_no = str(saved_info.get('supplier_item_no', '')).strip()
            saved_d = str(saved_info.get('supplier_desc', '')).strip()
            if (saved_no and saved_no.lower() == it_no.lower()) or (saved_d and saved_d.lower() == it_desc.lower()):
                matched_tally_prod = t_prod
                match_type = "Saved Memory"
                confidence = 1.0
                break

        # 2. Exact item_no matching in Tally names
        if not matched_tally_prod and it_no and len(it_no) >= 3:
            it_clean = clean_str(it_no)
            for t_prod, t_clean in tally_prods_clean.items():
                if it_clean in t_clean:
                    matched_tally_prod = t_prod
                    match_type = "Code Match"
                    confidence = 0.95
                    break

        # 3. High-confidence fuzzy string matching
        if not matched_tally_prod:
            best_score = 0.0
            best_prod = None
            target = f"{it_no} {it_desc}" if it_no != it_desc else it_desc

            for t_prod, t_clean in tally_prods_clean.items():
                score = similarity(target, t_prod)
                if score > best_score:
                    best_score = score
                    best_prod = t_prod

            if best_score >= 0.70:
                matched_tally_prod = best_prod
                match_type = "Auto Match"
                confidence = round(best_score, 2)

        results.append({
            'supplier_name': item.get('supplier_name', ''),
            'invoice_file': item.get('invoice_file', ''),
            'supplier_item_no': it_no,
            'supplier_desc': it_desc,
            'rmb_price': item.get('rmb_price', 0.0),
            'pcs_per_ctn': item.get('pcs_per_ctn', 0),
            'invoiced_ctns': item.get('invoiced_ctns', 0),
            'invoiced_qty': item.get('invoiced_qty', 0),
            'amount_rmb': item.get('amount_rmb', 0.0),
            'matched_product_name': matched_tally_prod,
            'voucher_no': '',
            'voucher_qty': 0,
            'voucher_rate': 0,
            'landed_multiplier': 0,
            'multiplier_healthy': True,
            'match_type': match_type,
            'confidence': confidence,
            'status': 'Confirmed' if match_type in ('Saved Memory', 'Code Match') else 'Pending'
        })

    return results

def archive_invoice_file(filename: str, folder: str = "commercial invoices") -> bool:
    """
    Safely move a processed commercial invoice from the active folder into the archive subfolder.
    """
    src_path = os.path.join(folder, filename)
    if not os.path.exists(src_path):
        return False

    archive_dir = os.path.join(folder, ARCHIVE_DIR_NAME)
    os.makedirs(archive_dir, exist_ok=True)

    dest_path = os.path.join(archive_dir, filename)
    if os.path.exists(dest_path):
        base, ext = os.path.splitext(filename)
        dest_path = os.path.join(archive_dir, f"{base}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}{ext}")

    shutil.move(src_path, dest_path)
    return True

def extract_and_archive_all_new_invoices(
    folder: str = "commercial invoices",
    tally_products: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    ETL Ingestion Pipeline:
      1. Scans folder for unarchived commercial invoice Excel files.
      2. Parses items, metadata, quantities, and RMB unit prices.
      3. Macro-matches invoices to DayBook Purchase Vouchers and micro-matches items.
      4. Stores derived items into commercial_invoice_items database table.
      5. Immediately moves processed Excel files to archive/.
    """
    unprocessed = get_unprocessed_invoices(folder)
    if not unprocessed:
        return {
            'status': 'no_files',
            'files_processed': 0,
            'items_extracted': 0,
            'new_items': 0,
            'updated_prices': 0,
            'auto_matched': 0,
            'message': 'No new commercial invoice files found in folder.'
        }

    # Load Tally products if not provided
    if tally_products is None:
        li_df = db.get_line_items_df()
        tally_products = sorted(li_df['product_name'].dropna().unique().tolist()) if not li_df.empty else []

    # Build saved mappings memory lookup
    saved_mappings_df = db.get_product_supplier_mappings()
    saved_lookup = {}
    if not saved_mappings_df.empty:
        for _, r in saved_mappings_df.iterrows():
            saved_lookup[r['product_name']] = {
                'supplier_item_no': str(r.get('supplier_item_no', '')),
                'supplier_desc': str(r.get('supplier_desc', '')),
                'rmb_price': float(r.get('rmb_price', 0.0)),
                'pcs_per_ctn': int(r.get('pcs_per_ctn', 0)),
            }

    total_extracted = 0
    all_matched_items = []
    files_processed = []

    for fname in unprocessed:
        fpath = os.path.join(folder, fname)
        try:
            items = parse_commercial_invoice(fpath)
            if not items:
                continue
            total_extracted += len(items)

            # Smart voucher-constrained matching
            matched, active_v, _ = match_invoice_items_smart(
                invoice_items=items,
                saved_mappings=saved_lookup,
                tally_products=tally_products
            )
            all_matched_items.extend(matched)

            # Move file to archive immediately
            archive_invoice_file(fname, folder=folder)
            files_processed.append(fname)
        except Exception as e:
            print(f"Error processing {fname}: {e}")

    # Upsert all extracted items into database
    stats = db.upsert_commercial_invoice_items(all_matched_items)

    auto_matched_count = sum(1 for it in all_matched_items if it.get('matched_product_name'))

    return {
        'status': 'success',
        'files_processed': len(files_processed),
        'file_names': files_processed,
        'items_extracted': total_extracted,
        'new_items': stats.get('new_items', 0),
        'updated_prices': stats.get('updated_prices', 0),
        'auto_matched': auto_matched_count,
        'total_db_items': stats.get('total', 0),
        'message': f"Successfully ingested {len(files_processed)} file(s), extracted {total_extracted} items, and archived spreadsheets."
    }
