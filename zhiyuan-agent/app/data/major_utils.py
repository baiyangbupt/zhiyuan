"""Major filtering utilities."""

import itertools

from app.data.major_aliases import resolve_major_alias_candidates_for_text


def _resolve_alias_major_names(chat_content: str) -> list[str]:
    return resolve_major_alias_candidates_for_text(chat_content)


def filter_major_hierarchy_by_prefix(
    chat_history: list[dict],
    prefix_index: dict[str, list[str]],
    major_lines: list[str],
    category_line_map: dict[str, list[int]],
    subcategory_line_map: dict[str, list[int]],
    major_line_map: dict[str, list[int]],
    subcategory_to_category: dict[str, str],
    major_to_subcategory: dict[str, str],
) -> str:
    """Filter major hierarchy by prefix found in chat history.

    Core logic:
    1. Extract all 2-character prefixes from chat content
    2. Find matching major names through prefix index
    3. Find line numbers for these majors and their parents through line maps
    4. Keep only these lines to maintain hierarchy structure
    5. Also check for level1 category names directly in chat content

    Args:
        chat_history: List of chat messages
        prefix_index: Mapping from 2-char prefix to major names
        major_lines: All major hierarchy lines (with indentation)
        category_line_map: Mapping from category name to line numbers (includes all descendant lines)
        subcategory_line_map: Mapping from subcategory name to line numbers (includes child major lines)
        major_line_map: Mapping from major name to line numbers
        subcategory_to_category: Mapping from subcategory to category
        major_to_subcategory: Mapping from major to subcategory

    Returns:
        Filtered hierarchy text with preserved structure
    """
    chat_content = '\n'.join([msg.get('content', '') for msg in chat_history])
    reserved_line_numbers: list[int] = []
    alias_included = _resolve_alias_major_names(chat_content)

    # Find categories (level1) mentioned in chat
    category_included = [cat for cat in category_line_map.keys() if cat in chat_content]
    category_included.extend([name for name in alias_included if name in category_line_map])
    for category in category_included:
        # category_line_map includes the category line and all its descendant lines
        reserved_line_numbers.extend(category_line_map[category])

    # Find subcategories (level2) mentioned in chat
    subcategory_included = list(
        itertools.chain.from_iterable(
            [value for key, value in prefix_index.items() if key in chat_content]
        )
    )

    # Filter to only subcategories that exist in subcategory_line_map
    subcategory_included.extend(alias_included)
    subcategory_included = [s for s in subcategory_included if s in subcategory_line_map]

    for subcategory in subcategory_included:
        # subcategory_line_map includes the subcategory line and all its child major lines
        reserved_line_numbers.extend(subcategory_line_map[subcategory])

    # Find majors (level3) mentioned in chat
    major_included = list(
        itertools.chain.from_iterable(
            [value for key, value in prefix_index.items() if key in chat_content]
        )
    )

    # Filter to only majors that exist in major_line_map
    major_included.extend(alias_included)
    major_included = [m for m in major_included if m in major_line_map]

    for major in major_included:
        reserved_line_numbers.extend(major_line_map[major])
        # Add first line of parent subcategory
        if major in major_to_subcategory:
            parent_subcategory = major_to_subcategory[major]
            if parent_subcategory in subcategory_line_map:
                reserved_line_numbers.append(subcategory_line_map[parent_subcategory][0])

    # Extract reserved lines and join
    reserved_line_set = sorted(set(reserved_line_numbers))
    reserved_lines = [major_lines[idx] for idx in reserved_line_set if idx < len(major_lines)]

    return '\n'.join(reserved_lines)


