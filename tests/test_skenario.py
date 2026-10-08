from skenario import jt


def test_format_indonesia():
    assert jt(4_731_600) == "4,73"
    assert jt(12_345_678, 1) == "12,3"
