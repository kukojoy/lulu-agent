def setup_line_editing() -> None:
    try:
        import readline
    except ImportError:
        return

    try:
        readline.parse_and_bind("tab: complete")
        readline.parse_and_bind("set editing-mode emacs")
    except Exception:
        return


def read_user_input(prompt: str) -> str:
    return input(prompt)
