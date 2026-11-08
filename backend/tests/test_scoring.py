from app.scoring import Features, score_features

def test_confirm_requires_price_and_two_supports():
    r=score_features(Features(.8,.9,.9,.8,1))
    assert r["confirmed_bottom"] is True
    r=score_features(Features(1,1,1,1,2/3))
    assert r["confirmed_bottom"] is False

def test_missing_data_not_zero():
    r=score_features(Features())
    assert r["score"] is None
    assert r["label"]=="insufficient_data"
