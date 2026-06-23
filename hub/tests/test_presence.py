"""Reference-counted presence: a printer is online while >=1 /inbox poll is
active, and only goes offline when the LAST poll releases."""

from hub.presence import Presence


def test_presence_online_while_any_poll_active():
    p = Presence()
    assert "pi" not in p

    p.add("pi")
    assert "pi" in p

    # A second overlapping poll for the same printer.
    p.add("pi")
    assert "pi" in p

    # The first poll finishing must NOT drop presence -- the second still holds it.
    p.release("pi")
    assert "pi" in p

    # Only when the last poll releases does the printer go offline.
    p.release("pi")
    assert "pi" not in p


def test_presence_release_below_zero_is_safe():
    # A stray release (never-added or double-released) must not underflow or crash.
    p = Presence()
    p.release("ghost")
    assert "ghost" not in p
    p.add("x")
    p.release("x")
    p.release("x")
    assert "x" not in p


def test_presence_independent_per_printer():
    p = Presence()
    p.add("a")
    p.add("b")
    p.release("a")
    assert "a" not in p
    assert "b" in p
