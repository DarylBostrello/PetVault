import tkinter as tk

def make_app_icon(size=64):
    """Draw the paw-print icon (coral paw on a peach tile) with plain code."""
    peach, paw = (255, 224, 204), (240, 138, 85)
    img = tk.PhotoImage(width=size, height=size)
    radius = size * 0.24                      # rounded corners of the tile
    scale, offset = size * 0.62 / 46, size * 0.19
    # one pad and four toes: (centre x, centre y, radius x, radius y) on a 46 x 46 grid
    parts = [(23, 34, 12, 10), (7, 23, 5, 6), (16.5, 12.5, 5.5, 7.5),
             (29.5, 12.5, 5.5, 7.5), (39, 23, 5, 6)]

    def on_paw(px, py):
        gx, gy = (px - offset) / scale, (py - offset) / scale
        return any(((gx - cx) / rx) ** 2 + ((gy - cy) / ry) ** 2 <= 1
                   for cx, cy, rx, ry in parts)

    for y in range(size):
        for x in range(size):
            dx = max(radius - x - 0.5, x + 0.5 - (size - radius), 0)
            dy = max(radius - y - 0.5, y + 0.5 - (size - radius), 0)
            if dx * dx + dy * dy > radius * radius:
                continue                      # outside the tile: stay transparent
            hits = sum(on_paw(x + (i + 0.5) / 3, y + (j + 0.5) / 3)
                       for i in range(3) for j in range(3))
            mix = hits / 9                    # smooth the paw's edges
            r, g, b = (round(peach[n] + (paw[n] - peach[n]) * mix)
                       for n in range(3))
            img.put(f"#{r:02x}{g:02x}{b:02x}", (x, y))
    return img


def set_window_icon(root):
    """Replace the default Tk 'X' icon in the title bar and taskbar."""
    try:
        root._app_icon = make_app_icon(64)    # keep a reference or Tk drops it
        root.iconphoto(True, root._app_icon)
    except tk.TclError:
        pass                                  # keep the default icon if this fails
