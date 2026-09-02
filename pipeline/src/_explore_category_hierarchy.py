"""Scratch exploration script (not part of the pipeline) to understand the
DVSA item hierarchy for the mechanical/consumable classification. Prints,
does not write."""
import duckdb
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WAREHOUSE = ROOT / "data" / "warehouse.duckdb"
LOOKUP = ROOT / "data" / "interim" / "dvsa_lookup"

con = duckdb.connect(str(WAREHOUSE), read_only=True)

print("=== distinct component_category count and top by failure volume ===")
rows = con.execute("""
    SELECT component_category, COUNT(*) n
    FROM mot_failures
    WHERE rfr_type_code IN ('F','P')
    GROUP BY 1 ORDER BY 2 DESC
""").fetchall()
print(f"distinct component_category values: {len(rows)}")
for name, n in rows[:30]:
    print(f"  {n:>10,}  {name}")

print("\n=== is component_category (item_name) ambiguous, i.e. same string different test_item_id? ===")
con.execute(f"""
    CREATE OR REPLACE TEMP TABLE ig AS
    SELECT CAST(test_item_id AS INTEGER) test_item_id, CAST(parent_id AS INTEGER) parent_id,
           CAST(test_item_set_section_id AS INTEGER) section_id, item_name
    FROM read_csv('{(LOOKUP / "item_group.csv").as_posix()}', delim='|', header=true)
    WHERE test_class_id = '4'
""")
con.execute(f"""
    CREATE OR REPLACE TEMP TABLE idet AS
    SELECT CAST(rfr_id AS INTEGER) rfr_id, CAST(test_item_id AS INTEGER) test_item_id,
           CAST(test_item_set_section_id AS INTEGER) section_id, rfr_deficiency_category, rfr_desc, minor_item
    FROM read_csv('{(LOOKUP / "item_detail.csv").as_posix()}', delim='|', header=true)
    WHERE test_class_id = '4'
""")

dup = con.execute("""
    SELECT item_name, COUNT(DISTINCT test_item_id) n_ids
    FROM ig
    WHERE test_item_id IN (SELECT DISTINCT test_item_id FROM idet)
    GROUP BY 1 HAVING COUNT(DISTINCT test_item_id) > 1
    ORDER BY 2 DESC
""").fetchall()
print(f"item_name strings (that are a leaf's immediate parent) appearing under >1 distinct test_item_id: {len(dup)}")
for name, n in dup[:40]:
    print(f"  {name}: {n} distinct test_item_id")

print("\n=== full ancestor chain builder ===")
id_to_row = {r[0]: r for r in con.execute("SELECT test_item_id, parent_id, section_id, item_name FROM ig").fetchall()}

def chain(tid):
    path = []
    seen = set()
    cur = tid
    while cur is not None and cur in id_to_row and cur not in seen:
        seen.add(cur)
        _, parent, section, name = id_to_row[cur]
        path.append((cur, name))
        if cur == 0:
            break
        cur = parent
    return path

print("\n--- chains for every test_item_id whose item_name == 'Condition' ---")
cond_ids = [tid for tid, (t, p, s, n) in id_to_row.items() if n == 'Condition']
for tid in cond_ids:
    c = chain(tid)
    print(f"  test_item_id={tid}: " + " -> ".join(n for _, n in c))

con.close()
