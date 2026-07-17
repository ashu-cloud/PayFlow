from uuid import uuid4

def generate_id() -> str:
    """Generates a UUID4 string representation."""
    return str(uuid4())
