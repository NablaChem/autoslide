from autoslide.models import BlockType


def test_code_block_type(parse):
    slides = parse("```python\nx = 1\n```")
    assert slides[0][0].type == BlockType.CODE


def test_code_language_extracted(parse):
    slides = parse("```python\nx = 1\n```")
    assert slides[0][0].metadata["language"] == "python"


def test_code_content_extracted(parse):
    slides = parse("```python\nx = 1\ny = 2\n```")
    assert slides[0][0].content == "x = 1\ny = 2"


def test_code_different_language(parse):
    slides = parse("```javascript\nconsole.log('hello')\n```")
    assert slides[0][0].metadata["language"] == "javascript"


def test_code_multiline_content(parse):
    code = "def foo():\n    return 42"
    slides = parse(f"```python\n{code}\n```")
    assert slides[0][0].content == code


def test_code_no_metadata_generated_flag(parse):
    # Regular code blocks are not 'generated' figures
    slides = parse("```python\nx = 1\n```")
    assert slides[0][0].metadata.get("generated") is None
