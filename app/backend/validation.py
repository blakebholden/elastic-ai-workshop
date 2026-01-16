"""
Input Validation for Security - Challenge 11

This module validates chat input to protect against prompt injection attacks.
"""
import re

# =============================================================================
# Blocked Patterns - Regex patterns to detect prompt injection attempts
# =============================================================================
BLOCKED_PATTERNS = [
    r"ignore\s+(your|all|previous)\s+(instructions|rules|prompts)",
    r"forget\s+(your|all|previous)\s+(instructions|rules|prompts)",
    r"disregard\s+(your|all|previous)",
    r"system\s*prompt",
    r"show\s+(me\s+)?(all|every)\s+(data|record|incident)",
    r"dump\s+(all|the)\s+(data|database)",
    r"reveal\s+(your|the)\s+(instructions|prompt)",
]


def validate_chat_input(message: str) -> tuple[bool, str]:
    """
    Validate chat input for potential prompt injection attacks.

    Args:
        message: The user's chat message

    Returns:
        Tuple of (is_valid, error_message)
        - If valid: (True, "")
        - If invalid: (False, "error description")
    """
    # Check for empty messages
    if not message or len(message.strip()) == 0:
        return False, "Message cannot be empty"

    # Check message length
    if len(message) > 2000:
        return False, "Message too long (max 2000 characters)"

    # Check for blocked patterns (potential injection attempts)
    message_lower = message.lower()
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, message_lower):
            return False, "I can't help with that request. Please ask about incident statistics, trends, or case information."

    return True, ""
