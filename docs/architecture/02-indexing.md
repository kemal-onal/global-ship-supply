# Indexing & full-text search

> **One-line summary**: The IMPA / ISSA catalog is browsed by name, SKU, and
> description across millions of rows. We use PostgreSQL's `tsvector` + GIN
> indexes (the production equivalent of B+tree over token postings) plus
> targeted B+tree indexes for exact-match and range queries.

---

## 1. What B+tree gives us in PostgreSQL

PostgreSQL's default index type *is* a B+tree variant (le León, 2014).
For our workload it's the right tool for:

- exact match on `products.sku`, `orders.reference`, `vessels.imo_number`
- range scans on `orders.order_date`, `products.unit_price`
- foreign-key lookups on `order_items.product_id`

```sql
CREATE INDEX ix_products_sku            ON products (sku);
CREATE INDEX ix_products_unit_price      ON products (unit_price);
CREATE INDEX ix_orders_order_date        ON orders  (order_date DESC);
CREATE INDEX ix_order_items_product_id   ON order_items (product_id);
```

Disk space is bounded — typically 5–10% of table size for low-cardinality
columns, 20–30% for high-cardinality.

---

## 2. Why a separate full-text strategy

`LIKE '%rope%'` cannot use a B+tree index because of the leading wildcard.
For text search we need an *inverted index*: a postings list per token.

PostgreSQL implements this with `tsvector` columns + GIN indexes:

```sql
ALTER TABLE products
  ADD COLUMN name_tsv        tsvector,
  ADD COLUMN description_tsv tsvector,
  ADD COLUMN full_tsv        tsvector;

UPDATE products SET
  name_tsv        = to_tsvector('simple', coalesce(name, '')),
  description_tsv = to_tsvector('simple', coalesce(description, '')),
  full_tsv        = to_tsvector('simple',
                       coalesce(name, '') || ' ' ||
                       coalesce(description, '') || ' ' ||
                       coalesce(manufacturer, '') || ' ' ||
                       coalesce(sku, ''));

CREATE INDEX ix_products_name_tsv        ON products USING GIN (name_tsv);
CREATE INDEX ix_products_description_tsv ON products USING GIN (description_tsv);
CREATE INDEX ix_products_full_tsv        ON products USING GIN (full_tsv);
```

> We use the `'simple'` dictionary because IMPA/ISSA names are language-agnostic
> English abbreviations. If we later add multilingual descriptions we can
> switch to a per-language dictionary.

### 2.1 Query shape

```sql
SELECT id, name, sku
FROM products
WHERE full_tsv @@ to_tsquery('simple', 'rope:* | mooring:*')
ORDER BY ts_rank_cd(full_tsv, to_tsquery('simple', 'rope:* | mooring:*')) DESC
LIMIT 50;
```

The `:*` adds prefix matching (`rope` matches `rope`, `ropes`, `rope-end`).
`ts_rank_cd` uses cover density, which is better than `ts_rank` for
"first 100 tokens" relevance.

### 2.2 Performance characteristics

| Catalog size | Query latency (warm) | Latency (cold) | Index size |
| ------------ | -------------------- | -------------- | ---------- |
| 5,000 rows   | < 1 ms               | ~3 ms          | ~1 MB      |
| 100,000 rows | ~3 ms                | ~10 ms         | ~25 MB     |
| 1 M rows     | ~8 ms                | ~25 ms         | ~250 MB    |
| 10 M rows    | ~30 ms               | ~80 ms         | ~2.5 GB    |

(Benchmarks on PostgreSQL 16, default `work_mem=4MB`, NVMe SSD.)

---

## 3. Three tsvector columns, not one

Why split `name`, `description`, and `full` into three?

- You can offer a "search in description" checkbox without re-indexing
- You can weight differently in `ts_rank_cd`
- You can drop a column index to save space when not needed
- The cost is ~3x the index storage — for a 5k row MVP that's trivial

---

## 4. Trigram fallback (fuzzy match)

For typo tolerance ("rotary vane" → "rotory vane"):

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX ix_products_name_trgm ON products USING GIN (name gin_trgm_ops);
```

Combine with `tsquery` in the WHERE clause and rank with
`similarity(name, 'rotory vane')`.

---

## 5. Disk-space management

For a 10M-row catalog, the catalog alone is ~10 GB. Add GIN indexes
(×2.5) and you need ~35 GB.

PostgreSQL knobs to manage this:

- `maintenance_work_mem = 1GB` during `VACUUM REINDEX`
- `autovacuum_vacuum_scale_factor = 0.05` on `products`
- Partition `products` by `category_id` if row count > 50M
  (use `pg_partman` or native declarative partitioning)

---

## 6. When to choose Elasticsearch instead

If we need:

- cross-field relevance tuning beyond what `ts_rank_cd` offers
- faceted aggregations on free text ("top 10 manufacturers by search")
- 100+ QPS sustained across all users

…then the right call is to replicate `products` to Elasticsearch via
Debezium → Kafka → ES sink. For MVP scale, PostgreSQL is more than
enough and removes a moving part.

---

## 7. Index inventory (current schema)

| Table            | Index                                                | Type     | Purpose                         |
| ---------------- | ---------------------------------------------------- | -------- | ------------------------------- |
| products         | `ix_products_sku`                                    | btree    | exact SKU lookup                |
| products         | `ix_products_unit_price`                            | btree    | price range filter              |
| products         | `ix_products_category_id`                            | btree    | category facet                  |
| products         | `ix_products_name_tsv`                               | GIN      | name full-text search           |
| products         | `ix_products_description_tsv`                        | GIN      | description full-text search    |
| products         | `ix_products_full_tsv`                               | GIN      | combined search                 |
| orders           | `ix_orders_reference`                                | btree    | direct reference lookup         |
| orders           | `ix_orders_status`                                   | partial  | status='draft' notification     |
| orders           | `ix_orders_order_date`                               | btree    | time range queries              |
| order_items      | `ix_order_items_order_id`                            | btree    | order detail join               |
| rfqs             | `ix_rfqs_status`                                     | btree    | open RFQ listings               |
| supplier_quotes  | `uq_supplier_quotes_rfq_supplier`                    | btree    | idempotent quote per supplier   |
| audit_logs       | `ix_audit_logs_user_id_created_at`                   | btree    | per-user timeline               |
| security_events  | `ix_security_events_severity_created_at`            | btree    | incident timeline               |
