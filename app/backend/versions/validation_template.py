"""
Input Validation for Security - Challenge 11

This module validates chat input to protect against prompt injection attacks.

YOUR TASK: Implement the validate_chat_input() function to:
1. Check for empty messages
2. Check message length (max 2000 characters)
3. Block messages matching suspicious patterns
"""
import re

# =============================================================================
# Blocked Patterns - Add regex patterns to detect prompt injection attempts
# =============================================================================
# Examples of patterns to block:
#   - "ignore your previous instructions"
#   - "forget all rules"
#   - "show me all data"
#
# YOUR CODE HERE: Add patterns to the list
BLOCKED_PATTERNS = [
    # Add your regex patterns here, for example:
    # r"ignore\s+(your|all|previous)\s+(instructions|rules|prompts)",
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

    YOUR CODE HERE: Implement validation checks:
    1. Return (False, "Message cannot be empty") if message is empty
    2. Return (False, "Message too long...") if over 2000 characters
    3. Return (False, "I can't help...") if message matches BLOCKED_PATTERNS
    4. Return (True, "") if all checks pass
    """
    # YOUR CODE HERE
    return True, ""  # Remove this and implement proper validation
