from o2c_sim.identity import PREFIX_ACCOUNT, PREFIX_QUOTE, SequenceDesk, mint_document_id


def test_zero_padded_document_ids():
    assert mint_document_id(PREFIX_ACCOUNT, 1) == "ACC-2026-000001"
    assert mint_document_id(PREFIX_QUOTE, 42) == "QTE-2026-000042"
    desk = SequenceDesk()
    assert desk.next_id("SO") == "SO-2026-000001"
    assert desk.next_id("SO") == "SO-2026-000002"
