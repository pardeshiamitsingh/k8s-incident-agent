from guardrails.normalize import normalize


def test_strips_zero_width_and_control_characters():
    assert normalize("pa​yment\x00 down") == "payment down"


def test_nfkc_folds_fullwidth_characters():
    assert normalize("ＡＢＣ") == "ABC"


def test_collapses_whitespace():
    assert normalize("  orders   keep\t\tcrashing \n\n\n\nnow ") == "orders keep crashing\n\nnow"
