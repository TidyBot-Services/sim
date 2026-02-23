"""Display control — TidyBot-compatible API (sim stubs).

The real display module sends images/text to a physical display on the robot.
In sim, these are no-ops that log to the console.
"""


def show_text(text):
    """Display text on the robot's screen. Prints to console in sim."""
    print(f"[display] {text}")


def show_face(expression):
    """Display a face expression on the robot's screen. Prints to console in sim."""
    print(f"[display] face: {expression}")


def show_image(image_bytes):
    """Display an image on the robot's screen. No-op in sim."""
    print("[display] show_image called (no-op in sim)")


def show_plot(fig):
    """Display a matplotlib figure on the robot's screen. No-op in sim."""
    print("[display] show_plot called (no-op in sim)")


def clear():
    """Clear the robot's display. No-op in sim."""
    pass
