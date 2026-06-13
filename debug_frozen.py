import sqlite3
from pathlib import Path

DB = Path(__file__).parent / "database" / "king_fund.db"
conn = sqlite3.connect(str(DB))
conn.row_factory = sqlite3.Row

print("=== DERNIERS TRADES — TRD03/05/07/08/13/18 ===")
rows = conn.execute("""
    SELECT trader_id, action, symbol, ROUND(price,4) as price,
           ROUND(amount,6) as amount, ROUND(portfolio_value,2) as pv,
           substr(timestamp,1,19) as ts
    FROM trades
    WHERE trader_id IN (3,5,7,8,13,18)
    ORDER BY trader_id, id DESC
    LIMIT 60
""").fetchall()
for r in rows:
    print(f"TRD{r['trader_id']:02d} | {r['action']:5s} | {r['symbol']:8s} | "
          f"price={r['price']:10.4f} | qty={r['amount']:10.6f} | "
          f"pv={r['pv']:7.2f} | {r['ts']}")

print("\n=== SNAPSHOT LE PLUS RÉCENT ===")
snaps = conn.execute("""
    SELECT trader_id, ROUND(portfolio_value,2) as pv, ROUND(cash,2) as cash,
           positions, substr(timestamp,1,19) as ts
    FROM snapshots
    WHERE id IN (SELECT MAX(id) FROM snapshots GROUP BY trader_id)
      AND trader_id IN (3,5,7,8,13,18)
    ORDER BY trader_id
""").fetchall()
for s in snaps:
    print(f"TRD{s['trader_id']:02d} | pv={s['pv']:7.2f} | cash={s['cash']:7.2f} | pos={s['positions']} | {s['ts']}")

conn.close()
