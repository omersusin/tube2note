"""tube2note: YouTube channels, playlists and videos -> Markdown/PDF for NotebookLM and RAG."""
__version__ = "0.17.0"


def main(argv=None):
    """Console entry point (imported lazily so `import tube2note` stays cheap)."""
    from .cli import main as _main
    return _main(argv)
