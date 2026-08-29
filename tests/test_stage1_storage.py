

def test_paste_log_round_trip(tmp_path):
    from wordvault import DocumentStore

    store = DocumentStore(tmp_path / "paste.db")
    doc = store.create_document("Essay")
    store.log_paste(doc.id, 54, "For behold, the Lord",
                    "Isaiah 66 from Bible Search Lite")
    store.log_paste(doc.id, 30, "and the wall", "")
    rows = store.pastes_for_document(doc.id)
    assert len(rows) == 2
    created, words, snippet, comment = rows[0]
    assert words == 54 and "Isaiah 66" in comment
    assert rows[1][3] == ""                 # event logged, note empty
    other = store.create_document("Other")
    assert store.pastes_for_document(other.id) == []
