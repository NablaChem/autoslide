def test_tracing_adds_tcolorbox(render):
    assert r"\begin{tcolorbox}" in render("### Slide ###\nHello world", tracing=True)


def test_no_tracing_omits_tcolorbox(render):
    assert r"\begin{tcolorbox}" not in render("### Slide ###\nHello world")


def test_tracing_wraps_list_block(render):
    latex = render("### Slide ###\n- item one\n- item two", tracing=True)
    assert r"\begin{tcolorbox}" in latex


def test_tracing_does_not_wrap_code_block(render):
    latex = render("### Slide ###\n```python\nprint('hi')\n```", tracing=True)
    assert r"\begin{tcolorbox}" not in latex


def test_tracing_includes_tcolorbox_package(render):
    assert r"\usepackage{tcolorbox}" in render("### Slide ###\nHi", tracing=True)


def test_no_tracing_omits_tcolorbox_package(render):
    assert r"\usepackage{tcolorbox}" not in render("### Slide ###\nHi")
