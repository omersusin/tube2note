from tube2note.export_txt import to_txt
from tube2note.links import linkify, thin_markers, to_single_line

def test_thin_every():
    t = "[00:05] a [00:10] b [00:40] c"
    assert thin_markers(t, 0) == t
    got = thin_markers(t, 30)
    assert "[00:05]" in got and "[00:40]" in got and "[00:10]" not in got

def test_thin_linked():
    t = linkify("[00:05] a [00:10] b", "VID12345678")
    got = thin_markers(t, 30)
    assert got.count("youtu.be") == 1 and "00:10" in got and "(https://youtu.be/VID12345678?t=10" not in got

def test_single_line():
    assert to_single_line("a\n\nb\n\nc") == "a b c"
    assert "[00:05]" in to_single_line("[00:05] a\n\n[00:10] b")

def test_txt():
    out = to_txt("## T\n\n[00:05] hi\n\n- a\n\n---\n")
    assert "T" in out and "[00:05] hi" in out and "##" not in out and "---" not in out
    linked = to_txt("[01:05](https://youtu.be/X?t=65s) hi")
    assert linked.strip() == "[01:05] hi"
