"""The runtime SQL adapter must preserve private string values verbatim."""

from backend.app.db.postgres.runtime import dialect_sql


def test_upsert_qualifies_columns_without_rewriting_literals_or_comments():
    source = """INSERT INTO ledger(id,count,note) VALUES(?,?,?) ON CONFLICT(id)
    DO UPDATE SET count=count+excluded.count,
      note=CASE WHEN note='count and note?' THEN 'note' ELSE excluded.note END
      /* count and note are private literal words */"""
    result = dialect_sql(source)
    assert "count=ledger.count+excluded.count" in result
    assert "WHEN ledger.note='count and note?' THEN 'note' ELSE excluded.note" in result
    assert "/* count and note are private literal words */" in result
    assert result.count("%s") == 3


def test_upsert_nested_function_commas_do_not_restart_assignment_state():
    result = dialect_sql("""INSERT INTO ledger(id,total,note) VALUES(?,?,?)
        ON CONFLICT(id) DO UPDATE SET total=coalesce(total,0)+excluded.total,
        note=coalesce(note,'total'), other='note'""")
    assert "total=coalesce(ledger.total,0)+excluded.total" in result
    assert "note=coalesce(ledger.note,'total')" in result
    assert "other='note'" in result
