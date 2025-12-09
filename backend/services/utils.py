def safe_int(value, default: int = 0) -> int:
    """Safely convert a value to int, falling back to default on errors."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
