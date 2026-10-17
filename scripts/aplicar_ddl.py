"""Aplica en orden los .sql de bronze/sql/ contra Supabase. Idempotente.
Uso: python scripts/aplicar_ddl.py
"""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from common.db import conectar  # noqa: E402


def main() -> None:
    con = conectar()
    try:
        with con, con.cursor() as cur:
            cur.execute("SELECT version()")
            print("Conectado:", cur.fetchone()[0].split(",")[0])
            for archivo in sorted((RAIZ / "bronze" / "sql").glob("*.sql")):
                cur.execute(archivo.read_text(encoding="utf-8"))
                print("Aplicado:", archivo.name)
            cur.execute("SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema='bronze' ORDER BY 1")
            print("Tablas en bronze:", [r[0] for r in cur.fetchall()])
    finally:
        con.close()


if __name__ == "__main__":
    main()
