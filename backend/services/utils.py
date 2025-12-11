import math
from typing import Any, Dict, List, Union

def safe_int(value, default: int = 0) -> int:
    """Safely convert a value to int, falling back to default on errors."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

def safe_float(value, default: float = 0.0) -> float:
    """Safely convert a value to float, handling NaN and infinity."""
    try:
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            return default
        return result
    except (TypeError, ValueError):
        return default

def sanitize_for_json(obj: Any) -> Any:
    """
    Recursively sanitize data structure to ensure JSON compatibility.
    Replaces NaN, Infinity with 0.0.
    """
    if isinstance(obj, dict):
        return {key: sanitize_for_json(value) for key, value in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [sanitize_for_json(item) for item in obj]
    elif isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return 0.0
        return obj
    elif isinstance(obj, (int, str, bool)) or obj is None:
        return obj
    else:
        # For any other type, try to convert to string
        try:
            return str(obj)
        except:
            return None
