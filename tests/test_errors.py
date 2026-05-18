import pytest


def test_unclosed_code_block_raises(parse):
    with pytest.raises(ValueError, match="Unclosed code block"):
        parse("```python\nx = 1\n")


def test_unclosed_plot_block_raises(parse):
    with pytest.raises(ValueError, match="Unclosed fenced code block"):
        parse("```plot\nimport matplotlib.pyplot as plt\n")


def test_unclosed_schematic_block_raises(parse):
    with pytest.raises(ValueError, match="Unclosed fenced code block"):
        parse("```schematic\nimport matplotlib.pyplot as plt\n")


def test_closed_code_block_does_not_raise(parse):
    parse("```python\nx = 1\n```")  # must not raise


def test_closed_plot_block_does_not_raise(parse):
    parse("```plot\nimport matplotlib.pyplot as plt\n```")  # must not raise


def test_unclosed_code_block_in_slide_raises(parse):
    with pytest.raises(ValueError):
        parse("### Slide ###\n\n```python\nsome code\n")
