-- =============================================================================
-- DayBook Analytics — Supabase PostgreSQL Schema
-- Run this in your Supabase Project -> SQL Editor
-- =============================================================================

-- ============================================
-- TABLE 1: upload_history (CREATE FIRST — referenced by vouchers)
-- ============================================
CREATE TABLE IF NOT EXISTS upload_history (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    filename        TEXT NOT NULL,
    file_size_bytes BIGINT,
    date_range_start DATE,
    date_range_end  DATE,
    total_vouchers  INTEGER DEFAULT 0,
    new_inserted    INTEGER DEFAULT 0,
    updated         INTEGER DEFAULT 0,
    skipped         INTEGER DEFAULT 0,
    total_line_items INTEGER DEFAULT 0,
    new_products    INTEGER DEFAULT 0,
    status          TEXT DEFAULT 'Success',      -- 'Success', 'Partial', 'Failed', 'In Progress'
    error_message   TEXT,
    uploaded_at     TIMESTAMPTZ DEFAULT now()
);

-- ============================================
-- TABLE 2: vouchers (header-level transactions)
-- ============================================
CREATE TABLE IF NOT EXISTS vouchers (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    date            DATE NOT NULL,
    miti            TEXT,
    party_name      TEXT NOT NULL,
    voucher_type    TEXT NOT NULL,
    voucher_category TEXT NOT NULL,
    voucher_no      TEXT NOT NULL,                -- TEXT: handles both numeric (e.g. "626") and alphanumeric (e.g. "rara2603")
    debit_amount    NUMERIC(14,2) DEFAULT 0,
    credit_amount   NUMERIC(14,2) DEFAULT 0,
    narration       TEXT,
    month           TEXT,
    upload_id       BIGINT REFERENCES upload_history(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ DEFAULT now(),

    -- DEDUP KEY: date + type + number + party = truly unique voucher
    CONSTRAINT uq_voucher UNIQUE (date, voucher_type, voucher_no, party_name)
);
CREATE INDEX IF NOT EXISTS idx_vouchers_date ON vouchers(date);
CREATE INDEX IF NOT EXISTS idx_vouchers_party ON vouchers(party_name);
CREATE INDEX IF NOT EXISTS idx_vouchers_type ON vouchers(voucher_type);
CREATE INDEX IF NOT EXISTS idx_vouchers_month ON vouchers(month);
CREATE INDEX IF NOT EXISTS idx_vouchers_category ON vouchers(voucher_category);

-- ============================================
-- TABLE 3: line_items (product-level details)
-- ============================================
CREATE TABLE IF NOT EXISTS line_items (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    voucher_id      BIGINT REFERENCES vouchers(id) ON DELETE CASCADE,
    date            DATE NOT NULL,
    party_name      TEXT NOT NULL,
    voucher_type    TEXT NOT NULL,
    voucher_category TEXT NOT NULL,
    voucher_no      TEXT NOT NULL,
    product_name    TEXT NOT NULL,
    quantity        NUMERIC(12,2) DEFAULT 0,
    rate            NUMERIC(12,2) DEFAULT 0,
    amount          NUMERIC(14,2) DEFAULT 0,
    month           TEXT,
    product_group   TEXT DEFAULT 'Others',
    created_at      TIMESTAMPTZ DEFAULT now(),

    -- DEDUP KEY: same voucher identity + same product + same qty + same rate
    CONSTRAINT uq_line_item UNIQUE (date, voucher_type, voucher_no, party_name, product_name, quantity, rate)
);
CREATE INDEX IF NOT EXISTS idx_line_items_product ON line_items(product_name);
CREATE INDEX IF NOT EXISTS idx_line_items_group ON line_items(product_group);
CREATE INDEX IF NOT EXISTS idx_line_items_voucher ON line_items(voucher_id);
CREATE INDEX IF NOT EXISTS idx_line_items_month ON line_items(month);
CREATE INDEX IF NOT EXISTS idx_line_items_date ON line_items(date);

-- ============================================
-- TABLE 4: narrations
-- ============================================
CREATE TABLE IF NOT EXISTS narrations (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    voucher_id      BIGINT REFERENCES vouchers(id) ON DELETE CASCADE,
    narration_text  TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT uq_narration UNIQUE (voucher_id, narration_text)
);

-- ============================================
-- TABLE 5: supplier_products (auto-populated from purchase records)
-- ============================================
CREATE TABLE IF NOT EXISTS supplier_products (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    supplier_name       TEXT NOT NULL,
    product_name        TEXT NOT NULL,
    last_purchase_date  DATE,
    last_purchase_rate  NUMERIC(12,2),
    avg_purchase_rate   NUMERIC(12,2),
    total_qty_purchased NUMERIC(12,2) DEFAULT 0,
    purchase_count      INTEGER DEFAULT 0,
    is_preferred        BOOLEAN DEFAULT FALSE,
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT uq_supplier_product UNIQUE (supplier_name, product_name)
);
CREATE INDEX IF NOT EXISTS idx_sp_supplier ON supplier_products(supplier_name);
CREATE INDEX IF NOT EXISTS idx_sp_product ON supplier_products(product_name);

-- ============================================
-- TABLE 6: lead_time_config
-- ============================================
CREATE TABLE IF NOT EXISTS lead_time_config (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    config_type             TEXT NOT NULL,       -- 'supplier', 'product_group', 'default'
    config_key              TEXT NOT NULL,       -- supplier name, group name, or 'global'
    lead_time_days          INTEGER NOT NULL DEFAULT 7,
    safety_stock_days       INTEGER NOT NULL DEFAULT 3,
    min_order_qty           NUMERIC(12,2) DEFAULT 1,
    reorder_point_override  NUMERIC(12,2),
    notes                   TEXT,
    updated_at              TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT uq_lead_time UNIQUE (config_type, config_key)
);
-- Seed global default if not present
INSERT INTO lead_time_config (config_type, config_key, lead_time_days, safety_stock_days)
VALUES ('default', 'global', 7, 3)
ON CONFLICT (config_type, config_key) DO NOTHING;

-- ============================================
-- TABLE 7: purchase_orders
-- ============================================
CREATE TABLE IF NOT EXISTS purchase_orders (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    po_number       TEXT NOT NULL UNIQUE,
    supplier_name   TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'Draft',  -- 'Draft', 'Finalized', 'Sent', 'Received', 'Cancelled'
    total_amount    NUMERIC(14,2) DEFAULT 0,
    total_items     INTEGER DEFAULT 0,
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- ============================================
-- TABLE 8: po_line_items
-- ============================================
CREATE TABLE IF NOT EXISTS po_line_items (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    po_id           BIGINT REFERENCES purchase_orders(id) ON DELETE CASCADE,
    product_name    TEXT NOT NULL,
    suggested_qty   NUMERIC(12,2) NOT NULL,
    ordered_qty     NUMERIC(12,2) NOT NULL,
    estimated_rate  NUMERIC(12,2),
    estimated_amount NUMERIC(14,2),
    sales_velocity  NUMERIC(12,4),
    current_stock   NUMERIC(12,2),
    days_of_stock   NUMERIC(8,2),
    product_group   TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- ============================================
-- TABLE 9: product_supplier_mappings (Commercial Invoice RMB Prices & Pack Sizes)
-- ============================================
CREATE TABLE IF NOT EXISTS product_supplier_mappings (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_name        TEXT NOT NULL UNIQUE,
    supplier_name       TEXT NOT NULL,
    supplier_item_no    TEXT,
    supplier_desc       TEXT,
    rmb_price           NUMERIC(10,3),
    pcs_per_ctn         INTEGER,
    invoice_file        TEXT,
    matched_at          TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_psm_prod ON product_supplier_mappings(product_name);
CREATE INDEX IF NOT EXISTS idx_psm_sup ON product_supplier_mappings(supplier_name);

-- ============================================
-- TABLE 10: commercial_invoice_items (Extracted items from supplier invoices)
-- ============================================
CREATE TABLE IF NOT EXISTS commercial_invoice_items (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    item_key            TEXT NOT NULL UNIQUE,        -- e.g. "huabei::3398-1::inertial car"
    supplier_name       TEXT NOT NULL,
    supplier_item_no    TEXT,
    supplier_desc       TEXT,
    rmb_price           NUMERIC(10,3) NOT NULL,
    pcs_per_ctn         INTEGER DEFAULT 0,
    source_invoice      TEXT NOT NULL,
    extracted_at        TIMESTAMPTZ DEFAULT now(),
    tally_product_name  TEXT,
    is_matched          BOOLEAN DEFAULT FALSE,
    match_confidence    NUMERIC(5,2) DEFAULT 0.0,
    match_type          TEXT DEFAULT 'Unmatched',     -- 'Code Match', 'Auto Match', 'Manual', 'Saved Memory'
    matched_at          TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_cii_supplier ON commercial_invoice_items(supplier_name);
CREATE INDEX IF NOT EXISTS idx_cii_tally ON commercial_invoice_items(tally_product_name);
CREATE INDEX IF NOT EXISTS idx_cii_matched ON commercial_invoice_items(is_matched);

-- ============================================
-- TABLE 11: commercial_price_history (Price tracking across commercial invoices)
-- ============================================
CREATE TABLE IF NOT EXISTS commercial_price_history (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    supplier_name       TEXT NOT NULL,
    supplier_item_no    TEXT,
    supplier_desc       TEXT,
    old_rmb_price       NUMERIC(10,3) NOT NULL,
    new_rmb_price       NUMERIC(10,3) NOT NULL,
    source_invoice      TEXT NOT NULL,
    updated_at          TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_cph_item ON commercial_price_history(supplier_name, supplier_item_no);

-- ============================================
-- TABLE 12: opening_stock
-- ============================================
CREATE TABLE IF NOT EXISTS opening_stock (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_name        TEXT NOT NULL UNIQUE,
    opening_qty         NUMERIC(12,2) NOT NULL DEFAULT 0,
    unit                TEXT DEFAULT 'PCS',
    as_of_date          DATE DEFAULT '2024-04-01',
    updated_at          TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_os_prod ON opening_stock(product_name);

-- ============================================
-- TABLE 13: product_group_mappings
-- ============================================
CREATE TABLE IF NOT EXISTS product_group_mappings (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_name        TEXT NOT NULL UNIQUE,
    product_group       TEXT NOT NULL DEFAULT 'Others',
    updated_at          TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_pgm_prod ON product_group_mappings(product_name);
CREATE INDEX IF NOT EXISTS idx_pgm_group ON product_group_mappings(product_group);

-- ============================================
-- TABLE 14: hermes_items (AI Knowledge Base for Hermes Agent)
-- ============================================
CREATE TABLE IF NOT EXISTS hermes_items (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_name        TEXT NOT NULL UNIQUE,
    current_stock       NUMERIC(12,2) DEFAULT 0,
    selling_price       NUMERIC(12,2) DEFAULT 0,
    catalog_price       NUMERIC(12,2),
    rmb_price           NUMERIC(10,3),
    image_url           TEXT,
    tags                TEXT,
    last_sold_month     TEXT,
    product_group       TEXT DEFAULT 'Others',
    updated_at          TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_hermes_prod ON hermes_items(product_name);
CREATE INDEX IF NOT EXISTS idx_hermes_stock ON hermes_items(current_stock);
CREATE INDEX IF NOT EXISTS idx_hermes_tags ON hermes_items(tags);
CREATE INDEX IF NOT EXISTS idx_hermes_group ON hermes_items(product_group);

-- ============================================
-- TABLE 15: tiktok_credentials (OAuth Tokens & Account Info)
-- ============================================
CREATE TABLE IF NOT EXISTS tiktok_credentials (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    open_id             TEXT NOT NULL UNIQUE,
    union_id            TEXT,
    display_name        TEXT,
    avatar_url          TEXT,
    access_token        TEXT NOT NULL,
    refresh_token       TEXT NOT NULL,
    expires_at          TIMESTAMPTZ NOT NULL,
    refresh_expires_at  TIMESTAMPTZ NOT NULL,
    scope               TEXT,
    updated_at          TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_tiktok_openid ON tiktok_credentials(open_id);

-- ============================================
-- TABLE 16: tiktok_posts (Post Queue, Published History & Safety Audit)
-- ============================================
CREATE TABLE IF NOT EXISTS tiktok_posts (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    publish_id          TEXT,
    post_type           TEXT CHECK (post_type IN ('video', 'photo_carousel')),
    title               TEXT,
    caption             TEXT,
    hashtags            TEXT[],
    media_urls          TEXT[],
    privacy_level       TEXT DEFAULT 'PUBLIC_TO_EVERYONE',
    destination         TEXT DEFAULT 'DIRECT_POST', -- 'DIRECT_POST' or 'DRAFT_INBOX'
    safety_status       TEXT DEFAULT 'SAFE',        -- 'SAFE', 'WARNING', 'BLOCKED'
    safety_details      JSONB,
    status              TEXT DEFAULT 'draft',       -- 'draft', 'rendering', 'uploading', 'published', 'failed'
    error_message       TEXT,
    created_at          TIMESTAMPTZ DEFAULT now(),
    published_at        TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_tiktok_posts_status ON tiktok_posts(status);
CREATE INDEX IF NOT EXISTS idx_tiktok_posts_created ON tiktok_posts(created_at DESC);
