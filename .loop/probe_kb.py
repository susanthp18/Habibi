import db
from sqlalchemy import text

with db.engine.connect() as c:
    rows = c.execute(text(
        "SELECT id, status, created_at, updated_at, left(coalesce(error, ''), 70) AS err "
        "FROM kb_index_jobs ORDER BY updated_at DESC LIMIT 8"
    )).fetchall()
    print("=== recent kb_index_jobs ===")
    for r in rows:
        print(r)
    print("=== active clients ===")
    cl = c.execute(text(
        "SELECT application_name, client_addr, state, count(*) "
        "FROM pg_stat_activity WHERE pid <> pg_backend_pid() "
        "GROUP BY 1, 2, 3 ORDER BY 4 DESC"
    )).fetchall()
    for r in cl:
        print(r)
