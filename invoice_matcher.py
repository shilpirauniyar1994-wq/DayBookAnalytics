"""
DayBook Analytics — Commercial Invoice Parser, Matcher & Archival Engine
Parses supplier commercial invoices (Huabei, Rara, VG, etc.), extracts RMB prices
and carton pack sizes, auto-matches to Tally products, stores unique derived items
in the persistent database, and immediately archives processed invoice files.
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

def similarity(a: str, b: str) -> float:
    """Compute string similarity ratio between two cleaned strings."""
    s_a = re.sub(r'[^a-zA-Z0-9]', '', str(a).lower())
    s_b = re.sub(r'[^a-zA-Z0-9]', '', str(b).lower())
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

def parse_commercial_invoice(filepath: str) -> List[Dict[str, Any]]:
    """
    Intelligently parse a supplier commercial invoice and return extracted items.
    Handles Format 1 (Shantou Huabei standard) and Format 2 (VG Loaded List workbooks).
    Calculates exact per-piece RMB unit prices and master carton pack sizes.
    """
    filename = os.path.basename(filepath)
    extracted_items = []

    # Detect supplier name from filename or header
    supplier_name = "Import Supplier"
    f_lower = filename.lower()
    if 'huabei' in f_lower or 'hb' in f_lower:
        supplier_name = "Huabei"
    elif 'rara' in f_lower:
        supplier_name = "Rara"
    elif 'shivam' in f_lower:
        supplier_name = "Shivam"
    elif 'vg' in f_lower:
        supplier_name = "Huabei"  # VG corresponds to Vidhi / Huabei shipments

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

                # Check for company headers in the first 10 rows
                header_text = ' '.join([str(x) for x in df.iloc[:10].values.flatten() if pd.notna(x)])
                if 'huabei' in header_text.lower():
                    supplier_name = "Huabei"
                elif 'rara' in header_text.lower():
                    supplier_name = "Rara"

                # ---------------------------------------------------------------------
                # FORMAT 1: Standard Shantou Huabei format (Headers around row 8: ITEM NO, Description, Price RMB, PCS/CTN)
                # ---------------------------------------------------------------------
                header_row_idx = None
                col_item_no = None
                col_desc = None
                col_price = None
                col_pcs = None

                for r in range(min(15, len(df))):
                    row_vals = [str(x).strip().lower() for x in df.iloc[r] if pd.notna(x)]
                    row_str = ' '.join(row_vals)
                    if 'item no' in row_str and ('price' in row_str or 'rmb' in row_str or 'pcs' in row_str):
                        header_row_idx = r
                        break

                if header_row_idx is not None:
                    header_row = df.iloc[header_row_idx]
                    for c_idx, val in enumerate(header_row):
                        if pd.isna(val):
                            continue
                        v_str = str(val).strip().lower()
                        if 'item no' in v_str or 'item_no' in v_str or 'model' in v_str:
                            col_item_no = c_idx
                        elif 'description' in v_str:
                            col_desc = c_idx
                        elif ('price' in v_str or 'unit' in v_str) and 'amount' not in v_str:
                            col_price = c_idx
                        elif 'pcs/ctn' in v_str or 'pcs / ctn' in v_str or (('pcs' in v_str or 'ctn' in v_str) and 'total' not in v_str):
                            if col_pcs is None:
                                col_pcs = c_idx

                    if col_item_no is not None and col_price is not None:
                        for r in range(header_row_idx + 1, len(df)):
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

                            extracted_items.append({
                                'supplier_name': supplier_name,
                                'invoice_file': filename,
                                'sheet_name': sheet_name,
                                'supplier_item_no': item_str,
                                'supplier_desc': desc_val,
                                'rmb_price': round(price_val, 3),
                                'pcs_per_ctn': pcs_val,
                                'raw_label': f"{item_str} {desc_val}".strip()
                            })
                        continue

                # ---------------------------------------------------------------------
                # FORMAT 2: VG Loaded List / Mark format (Row 0 has MARK, 品名, DESCRIPTION, PCS /CTN, PRICE, etc.)
                # ---------------------------------------------------------------------
                r0_str = ' '.join([str(x).lower() for x in df.iloc[0] if pd.notna(x)])
                if 'mark' in r0_str and ('price' in r0_str or 'amt' in r0_str or 'pcs' in r0_str or 'ctn' in r0_str):
                    col_mark = 0
                    col_pcs = None
                    col_price = None
                    col_amt = None
                    col_tqty = None

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
                            'raw_label': raw_mark
                        })

    except Exception as e:
        print(f"Error parsing invoice {filepath}: {e}")
    finally:
        gc.collect()

    return extracted_items

def match_invoice_items_to_tally(
    invoice_items: List[Dict[str, Any]],
    tally_products: List[str],
    saved_mappings: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """
    Match each invoice item to a Tally product name using:
      1. Saved mappings memory lookup
      2. Exact code / model number matching
      3. High-confidence fuzzy string matching
    """
    if saved_mappings is None:
        saved_mappings = {}

    results = []
    tally_prods_clean = {p: re.sub(r'[^a-zA-Z0-9]', '', p.lower()) for p in tally_products}

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
            it_clean = re.sub(r'[^a-zA-Z0-9]', '', it_no.lower())
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
            'supplier_name': item['supplier_name'],
            'invoice_file': item['invoice_file'],
            'supplier_item_no': it_no,
            'supplier_desc': it_desc,
            'rmb_price': item['rmb_price'],
            'pcs_per_ctn': item['pcs_per_ctn'],
            'matched_product_name': matched_tally_prod,
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
    # If file with same name exists in archive, append timestamp
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
      2. Parses items and calculates true RMB unit prices.
      3. Performs intelligent auto-matching against Tally catalog.
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
            total_extracted += len(items)
            matched = match_invoice_items_to_tally(items, tally_products, saved_lookup)
            all_matched_items.extend(matched)
            # Move file to archive immediately
            archive_invoice_file(fname, folder=folder)
            files_processed.append(fname)
        except Exception as e:
            # Leave file in folder with error note
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
