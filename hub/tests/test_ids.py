from hub.ids import new_invite_code


def test_invite_code_never_leads_with_dash_or_underscore():
    # A leading '-'/'_' breaks `printer-svc hub join <code>` (argparse parses it
    # as a flag) and is awkward in URLs. Over many draws, the first character
    # must always be in the base64url alnum set, never '-' or '_'.
    for _ in range(3000):
        code = new_invite_code()
        assert code, "empty code"
        assert code[0] not in "-_", f"code leads with {code[0]!r}: {code}"
        assert len(code) >= 8
