"""Small delimiter-search helper for the official AVIS Engine TCP API.

The upstream client imports a generic top-level module named utils.
This local namespaced helper avoids colliding with this project utils package.
"""
def KMPSearch(pattern, text):
    """Return the first byte/string index of pattern in text, or -1."""
    try:
        return text.find(pattern)
    except (AttributeError, TypeError):
        return -1
