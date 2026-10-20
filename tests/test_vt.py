from mcp_interactive_terminal.vt import VirtualScreen


def test_simple_text():
    screen = VirtualScreen(40, 10)
    screen.feed("hello\r\nworld")
    assert screen.render() == "hello\nworld"
    assert screen.cursor == {"x": 6, "y": 2}


def test_cursor_positioning_overwrites():
    screen = VirtualScreen(40, 5)
    screen.feed("abcdef")
    screen.feed("\x1b[1;1HXY")
    assert screen.render() == "XYcdef"


def test_erase_line_clears_previous_content():
    screen = VirtualScreen(40, 5)
    screen.feed("garbage line\r\n")
    screen.feed("\x1b[2K\rclean")
    assert screen.render() == "garbage line\nclean"


def test_psreadline_repaint_fragments_render_cleanly():
    screen = VirtualScreen(120, 10)
    screen.feed("PS C:\\work> ")
    for typed in ["e", "ec", "ech", "echo"]:
        screen.feed(f"\x1b[1;13H{typed}\x1b[1;{12 + len(typed)}H")
    screen.feed("\r\nhi\r\nPS C:\\work> ")
    rendered = screen.render()
    assert rendered.count("echo") == 1
    assert rendered.splitlines()[-2] == "hi"


def test_resize_and_cursor_bounds():
    screen = VirtualScreen(20, 5)
    screen.feed("x" * 30)
    screen.resize(40, 10)
    assert screen.size == {"cols": 40, "rows": 10}
    assert screen.render()


def test_progress_bar_overwrite():
    screen = VirtualScreen(40, 5)
    screen.feed("progress 0%\r")
    screen.feed("progress 50%\r")
    screen.feed("progress 100%")
    assert screen.render() == "progress 100%"
