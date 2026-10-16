"""Drawing helpers: rounded rectangles and the paw print."""


def round_rect(canvas, x1, y1, x2, y2, radius, **kw):
    """Draw a rounded rectangle on a canvas (smoothed polygon)."""
    r = max(0, min(radius, (x2 - x1) / 2, (y2 - y1) / 2))
    points = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
              x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
              x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(points, smooth=True, **kw)


def draw_paw(canvas, x, y, size, color):
    """Paw print (one pad, four toes) inside a size x size box at (x, y)."""
    s = size / 46.0
    for x1, y1, x2, y2 in ((11, 24, 35, 44), (2, 17, 12, 29), (11, 5, 22, 20),
                           (24, 5, 35, 20), (34, 17, 44, 29)):
        canvas.create_oval(x + x1 * s, y + y1 * s, x + x2 * s, y + y2 * s,
                           fill=color, outline=color)
