from scripts.eval.book import BookState
from scripts.eval.costs import load_costs


def test_load_costs_and_empty_equity():
    c = load_costs()
    assert c.cost_version == "v1"
    b = BookState(cash=c.initial_cash, last_equity=c.initial_cash)
    assert b.mtm({}) == c.initial_cash
