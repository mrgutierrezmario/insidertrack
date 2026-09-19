import logging

from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker
from config import settings

logger = logging.getLogger(__name__)

# pool_pre_ping recycles stale connections (e.g. after a Postgres restart)
# instead of returning them and erroring on first use. Pool sizing is generous
# because the app interleaves a scheduler (long-running jobs) with web
# requests — the default pool_size=5 + max_overflow=10 can starve under
# moderate load.
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_recycle=3600,  # safety net for idle connections
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _apply_migrations():
    """Additive schema migrations for columns added after initial create_all."""
    migrations = [
        "ALTER TABLE signal_outcomes ADD COLUMN IF NOT EXISTS politician_id INTEGER",
        "ALTER TABLE signal_outcomes ADD COLUMN IF NOT EXISTS politician_name VARCHAR(200)",
        # FK indexes that PostgreSQL does not create automatically
        "CREATE INDEX IF NOT EXISTS ix_trades_politician_id ON trades (politician_id)",
        "CREATE INDEX IF NOT EXISTS ix_whale_positions_holder_id ON whale_positions (holder_id)",
        "CREATE INDEX IF NOT EXISTS ix_fed_trades_official_id ON fed_trades (official_id)",
        # Idempotency guard for snapshot_signals — paired with ON CONFLICT DO NOTHING
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_signal_outcomes_ticker_date ON signal_outcomes (ticker, signal_date)",
        # FK for signal_outcomes.politician_id (column already existed; constraint promotes it).
        # DO block + NOT EXISTS is idempotent — re-running is a no-op.
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE table_name = 'signal_outcomes'
                  AND constraint_name = 'fk_signal_outcomes_politician_id'
            ) THEN
                ALTER TABLE signal_outcomes
                ADD CONSTRAINT fk_signal_outcomes_politician_id
                FOREIGN KEY (politician_id)
                REFERENCES politicians(id)
                ON DELETE SET NULL;
            END IF;
        END $$;
        """,
        "CREATE INDEX IF NOT EXISTS ix_signal_outcomes_politician_id ON signal_outcomes (politician_id)",
        # Cached risk_level for trades — populated by refresh_risk_levels(), indexed for filter
        "ALTER TABLE trades ADD COLUMN IF NOT EXISTS risk_level VARCHAR(8)",
        "CREATE INDEX IF NOT EXISTS ix_trades_risk_level ON trades (risk_level)",
        # Derived trade columns (see services/trade_semantics.py): parsed amount
        # bounds, filer relationship, asset kind, and the buy/sell direction.
        "ALTER TABLE trades ADD COLUMN IF NOT EXISTS amount_low INTEGER",
        "ALTER TABLE trades ADD COLUMN IF NOT EXISTS amount_high INTEGER",
        "ALTER TABLE trades ADD COLUMN IF NOT EXISTS owner VARCHAR(8)",
        "ALTER TABLE trades ADD COLUMN IF NOT EXISTS asset_type VARCHAR(8)",
        "ALTER TABLE trades ADD COLUMN IF NOT EXISTS direction VARCHAR(4)",
        "CREATE INDEX IF NOT EXISTS ix_trades_asset_type ON trades (asset_type)",
        "CREATE INDEX IF NOT EXISTS ix_trades_direction ON trades (direction)",
        # Member identity across name spellings (congress_fetcher._name_key)
        "ALTER TABLE politicians ADD COLUMN IF NOT EXISTS bioguide_id VARCHAR(12)",
        "ALTER TABLE politicians ADD COLUMN IF NOT EXISTS name_key VARCHAR(80)",
        "CREATE INDEX IF NOT EXISTS ix_politicians_bioguide_id ON politicians (bioguide_id)",
        "CREATE INDEX IF NOT EXISTS ix_politicians_name_key ON politicians (name_key)",
        # Member track-record weight (services.track_record.refresh_skill)
        "ALTER TABLE politicians ADD COLUMN IF NOT EXISTS skill_factor DOUBLE PRECISION NOT NULL DEFAULT 1.0",
        "ALTER TABLE politicians ADD COLUMN IF NOT EXISTS skill_n INTEGER",
        "ALTER TABLE politicians ADD COLUMN IF NOT EXISTS skill_beat_spy DOUBLE PRECISION",
        "ALTER TABLE politicians ADD COLUMN IF NOT EXISTS skill_as_of DATE",
        # Filing provenance + Senate amendment linkage
        "ALTER TABLE trades ADD COLUMN IF NOT EXISTS filing_id VARCHAR(64)",
        "ALTER TABLE trades ADD COLUMN IF NOT EXISTS amends DATE",
        "ALTER TABLE trades ADD COLUMN IF NOT EXISTS house_tx_id VARCHAR(12)",
        "CREATE INDEX IF NOT EXISTS ix_trades_house_tx_id ON trades (house_tx_id)",
        "CREATE INDEX IF NOT EXISTS ix_trades_filing_id ON trades (filing_id)",
        # raw_data is json.dumps output, so the cast is safe; rows written
        # after this column existed already have it set.
        """
        UPDATE trades SET filing_id = COALESCE(raw_data::jsonb->>'ptr_uuid', raw_data::jsonb->>'ptr_doc_id')
        WHERE filing_id IS NULL AND raw_data IS NOT NULL AND raw_data <> ''
        """,
        # Flag distinguishing live snapshots from retroactively-backfilled ones
        "ALTER TABLE signal_outcomes ADD COLUMN IF NOT EXISTS is_backfilled BOOLEAN NOT NULL DEFAULT FALSE",
        # Form 4 sub-score joined the composite in 2026-09
        "ALTER TABLE signal_outcomes ADD COLUMN IF NOT EXISTS corporate_score INTEGER",
        "ALTER TABLE signal_outcomes ADD COLUMN IF NOT EXISTS score_version INTEGER",
        # Everything snapshotted before the column existed used the original weights.
        "UPDATE signal_outcomes SET score_version = 1 WHERE score_version IS NULL",
        # Persistent L2 cache for market_data. Sweeper job in scheduler.py
        # deletes expired rows hourly.
        """
        CREATE TABLE IF NOT EXISTS market_cache (
            cache_key  TEXT PRIMARY KEY,
            value      JSONB NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_market_cache_expires ON market_cache (expires_at)",
        # Watchlist bearer-token table — replaces the prior "email as auth key" pattern.
        # Existing rows in watchlist_items have no owner row; their owners are seeded
        # below with token_hash='' so the first request triggers the recovery flow.
        """
        CREATE TABLE IF NOT EXISTS watchlist_owners (
            email        VARCHAR(255) PRIMARY KEY,
            token_hash   VARCHAR(64)  NOT NULL,
            created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            last_used_at TIMESTAMPTZ
        )
        """,
        """
        INSERT INTO watchlist_owners (email, token_hash)
        SELECT DISTINCT email, ''
        FROM   watchlist_items
        ON CONFLICT (email) DO NOTHING
        """,
        # Backfill politician_id/name for legacy signal_outcome rows that were
        # snapshotted before the column was added. Uses the most recent tracked
        # politician trade per ticker (DISTINCT ON, ordered by trade_date DESC).
        """
        UPDATE signal_outcomes so
        SET politician_id   = sub.pid,
            politician_name = sub.pname
        FROM (
            SELECT DISTINCT ON (t.ticker)
                   t.ticker,
                   p.id   AS pid,
                   p.name AS pname
            FROM   trades t
            JOIN   politicians p ON t.politician_id = p.id
            WHERE  p.is_tracked = true
            ORDER  BY t.ticker, t.trade_date DESC
        ) sub
        WHERE so.ticker        = sub.ticker
          AND so.politician_id IS NULL
        """,
    ]
    # Each statement runs in its own transaction so one failure can't poison
    # the rest, and every failure is logged: a typo here used to vanish
    # silently and surface later as a missing column.
    for sql in migrations:
        try:
            with engine.begin() as conn:
                conn.execute(text(sql))
        except Exception as exc:
            head = " ".join(sql.split())[:90]
            logger.error(f"Migration failed: {head!r}: {exc}")

    # One-shot data migrations: run exactly once per database, recorded in
    # app_settings so an admin's later edits are not overwritten on restart.
    one_shot = [
        # 2026-09: every member is tracked by default (was Pelosi-only). Flip the
        # existing rows once; untracking afterwards is a deliberate admin choice.
        ("migration:politicians_tracked_by_default",
         "UPDATE politicians SET is_tracked = TRUE WHERE is_tracked IS NOT TRUE"),
        ("migration:politicians_tracked_by_default",
         "ALTER TABLE politicians ALTER COLUMN is_tracked SET DEFAULT TRUE, ALTER COLUMN is_tracked SET NOT NULL"),
        # 2026-09: backfill the derived trade columns for rows ingested before
        # they existed. Owner is left NULL (unknown) — the old parsers dropped
        # it. Options recorded as "<TICKER> (option)" have no call/put, so
        # their direction stays NULL and they drop out of the score.
        ("migration:trades_derived_columns",
         """
         UPDATE trades SET
           amount_low  = NULLIF(regexp_replace(split_part(COALESCE(amount_range, ''), '-', 1), '[^0-9]', '', 'g'), '')::bigint,
           amount_high = CASE
                           WHEN position('-' in COALESCE(amount_range, '')) = 0 THEN
                             CASE WHEN amount_range ~* '([+]|over)' THEN NULL
                                  ELSE NULLIF(regexp_replace(COALESCE(amount_range, ''), '[^0-9]', '', 'g'), '')::bigint END
                           ELSE NULLIF(regexp_replace(split_part(amount_range, '-', 2), '[^0-9]', '', 'g'), '')::bigint
                         END,
           asset_type  = CASE WHEN COALESCE(raw_data, '') LIKE '%"asset_type": "option"%' THEN 'option' ELSE 'stock' END
         WHERE asset_type IS NULL
         """),
        # 2026-09: filer date typos. Trades dated in the future or after their
        # own disclosure can't be real — drop them. House rows whose PTR
        # "notification date" predates the STOCK Act get NULL; the sync now
        # stores the Clerk's filing date, and repair_house_disclosure_dates()
        # (run by every backfill) fills the NULLs from the index.
        ("migration:trades_implausible_dates",
         """
         DELETE FROM trades
         WHERE trade_date > CURRENT_DATE
            OR trade_date < DATE '2012-01-01'
            OR (disclosure_date >= DATE '2012-01-01' AND trade_date > disclosure_date + 1)
         """),
        ("migration:trades_implausible_dates",
         "UPDATE trades SET disclosure_date = NULL WHERE disclosure_date < DATE '2012-01-01'"),
        # 2026-09: six hand-entered seed trades from the project's first day
        # (empty raw_data, no filing, no matching EFD report) attributed to
        # "Mark Kelly" and a duplicate "Tommy Tuberville" record. Remove the
        # rows, fold the duplicate's party/state into the real record
        # ("Thomas H Tuberville", as the EFD names him), drop the duplicate.
        ("migration:remove_seed_trades",
         "DELETE FROM trades WHERE filing_id IS NULL AND COALESCE(raw_data, '') = ''"),
        ("migration:remove_seed_trades",
         """
         UPDATE politicians real SET
           party = COALESCE(NULLIF(real.party, ''), dup.party),
           state = COALESCE(NULLIF(real.state, ''), dup.state)
         FROM politicians dup
         WHERE real.name = 'Thomas H Tuberville' AND dup.name = 'Tommy Tuberville'
         """),
        ("migration:remove_seed_trades",
         """
         DELETE FROM politicians p
         WHERE p.name = 'Tommy Tuberville'
           AND NOT EXISTS (SELECT 1 FROM trades t WHERE t.politician_id = p.id)
           AND EXISTS (SELECT 1 FROM politicians r WHERE r.name = 'Thomas H Tuberville')
         """),
        # 2026-09: a holder's first loaded quarter has nothing to compare
        # against, so its positions read "new" — relabel them "initial".
        ("migration:whale_initial_quarter",
         """
         UPDATE whale_positions p SET change_type = 'initial'
         FROM (SELECT holder_id, min(quarter) AS q0 FROM whale_positions GROUP BY holder_id) f
         WHERE p.holder_id = f.holder_id AND p.quarter = f.q0 AND p.change_type = 'new'
         """),
        ("migration:trades_derived_columns",
         """
         UPDATE trades SET direction =
           CASE
             WHEN asset_type <> 'stock' THEN NULL
             WHEN transaction_type ILIKE '%purchase%' THEN 'buy'
             WHEN transaction_type ILIKE '%sale%' THEN 'sell'
             ELSE NULL
           END
         WHERE direction IS NULL
         """),
    ]
    with engine.begin() as conn:
        done = {
            k for (k,) in conn.execute(
                text("SELECT key FROM app_settings WHERE key LIKE 'migration:%'")
            ).all()
        }
        applied: set[str] = set()
        for key, sql in one_shot:
            if key in done:
                continue
            conn.execute(text(sql))
            applied.add(key)
        for key in applied:
            conn.execute(
                text("INSERT INTO app_settings (key, value) VALUES (:k, NOW()::text) ON CONFLICT (key) DO NOTHING"),
                {"k": key},
            )


def init_db():
    from models import trade, politician, whale, analysis, subscriber, app_setting, signal_outcome, access, alert, insider, watchlist, fed_official, filing_institution, market_cache, processed_filing  # noqa: F401
    Base.metadata.create_all(bind=engine)
    _apply_migrations()
