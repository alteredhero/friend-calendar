from passwords import ALGORITHM, hash_password, verify_password


def test_round_trip():
    stored = hash_password("correct horse battery")
    assert verify_password("correct horse battery", stored)
    assert not verify_password("wrong", stored)


def test_stored_format_and_unique_salts():
    first, second = hash_password("same"), hash_password("same")
    assert first.startswith(ALGORITHM + "$")
    assert first != second  # random salt
    assert verify_password("same", first) and verify_password("same", second)


def test_unicode_password():
    stored = hash_password("pässwörd-日本語")
    assert verify_password("pässwörd-日本語", stored)
    assert not verify_password("passwoerd", stored)


def test_malformed_hashes_never_match_or_crash():
    for bad in ("", "plaintext", "a$b$c", f"{ALGORITHM}$x$y$z", f"{ALGORITHM}$1$zz$zz", "md5$1$00$00"):
        assert verify_password("anything", bad) is False
