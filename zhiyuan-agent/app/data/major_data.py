"""Major data loading and processing module."""

import json
from pathlib import Path
from typing import Any


def load_major_hierarchy(json_path: Path) -> dict[str, Any]:
    """Load major hierarchy from JSON file.

    Args:
        json_path: Path to the major JSON file

    Returns:
        Dictionary containing the major hierarchy data

    Raises:
        FileNotFoundError: If the JSON file does not exist
        ValueError: If the JSON structure is invalid
    """
    if not json_path.exists():
        raise FileNotFoundError(
            f"Major data file not found: {json_path}. "
            f"Please ensure the file exists in the data/option directory."
        )

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Validate basic structure
        if not isinstance(data, dict):
            raise ValueError(f"Invalid JSON structure in {json_path}: expected dict, got {type(data)}")

        if 'data' not in data:
            raise ValueError(f"Invalid JSON structure in {json_path}: missing 'data' key")

        if not isinstance(data['data'], list):
            raise ValueError(f"Invalid JSON structure in {json_path}: 'data' must be a list")

        return data

    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse JSON file {json_path}: {e}") from e


def build_prefix_index(hierarchy: dict[str, Any]) -> dict[str, list[str]]:
    """Build prefix index for majors (first 2 characters -> major names).

    Only indexes level2 (subcategories) and level3 (specific majors) since
    level1 (categories) are not used in filtering.

    Args:
        hierarchy: Major hierarchy dictionary

    Returns:
        Dictionary mapping 2-char prefixes to list of major names
    """
    prefix_index: dict[str, list[str]] = {}
    major_data = hierarchy.get('data', [])

    for level1 in major_data:
        # Index level2 (subcategory)
        for level2 in level1.get('children', []):
            label = level2.get('label', '')
            if len(label) >= 2:
                prefix = label[:2]
                if prefix not in prefix_index:
                    prefix_index[prefix] = []
                prefix_index[prefix].append(label)

            # Index level3 (specific major)
            for level3 in level2.get('children', []):
                label = level3.get('label', '')
                if len(label) >= 2:
                    prefix = label[:2]
                    if prefix not in prefix_index:
                        prefix_index[prefix] = []
                    prefix_index[prefix].append(label)

    return prefix_index


def build_line_number_mappings(
    hierarchy: dict[str, Any]
) -> tuple[dict[str, list[int]], dict[str, list[int]], dict[str, list[int]]]:
    """Build line number mappings for each level.

    Args:
        hierarchy: Major hierarchy dictionary

    Returns:
        Tuple of (category_line_map, subcategory_line_map, major_line_map)
    """
    category_line_map: dict[str, list[int]] = {}
    subcategory_line_map: dict[str, list[int]] = {}
    major_line_map: dict[str, list[int]] = {}

    major_data = hierarchy.get('data', [])
    line_num = 0

    for level1 in major_data:
        label1 = level1.get('label', '')
        if label1 not in category_line_map:
            category_line_map[label1] = []
        category_line_map[label1].append(line_num)
        line_num += 1

        for level2 in level1.get('children', []):
            label2 = level2.get('label', '')
            if label2 not in subcategory_line_map:
                subcategory_line_map[label2] = []
            subcategory_line_map[label2].append(line_num)
            category_line_map[label1].append(line_num)
            line_num += 1

            for level3 in level2.get('children', []):
                label3 = level3.get('label', '')
                if label3 not in major_line_map:
                    major_line_map[label3] = []
                major_line_map[label3].append(line_num)
                subcategory_line_map[label2].append(line_num)
                category_line_map[label1].append(line_num)
                line_num += 1

    return category_line_map, subcategory_line_map, major_line_map


def flatten_hierarchy_to_lines(hierarchy: dict[str, Any]) -> list[str]:
    """Flatten hierarchy to indented text lines.

    Args:
        hierarchy: Major hierarchy dictionary

    Returns:
        List of text lines with indentation representing hierarchy
    """
    result: list[str] = []
    major_data = hierarchy.get('data', [])

    for level1 in major_data:
        result.append(level1.get('label', ''))
        for level2 in level1.get('children', []):
            result.append(f"  {level2.get('label', '')}")
            for level3 in level2.get('children', []):
                result.append(f"    {level3.get('label', '')}")

    return result


def build_label_and_id_maps(
    hierarchy: dict[str, Any],
) -> tuple[set[str], dict[str, str], set[str], dict[str, str]]:
    """Build label sets and name-to-id maps for level2 and level3.

    Args:
        hierarchy: Major hierarchy dictionary

    Returns:
        Tuple of (level3_labels, level3_id_map, level2_labels, level2_id_map)
    """
    level3_labels: set[str] = set()
    level3_id_map: dict[str, str] = {}
    level2_labels: set[str] = set()
    level2_id_map: dict[str, str] = {}

    for level1 in hierarchy.get('data', []):
        for level2 in level1.get('children', []):
            label2 = level2.get('label', '')
            id2 = level2.get('id', '')
            if label2:
                level2_labels.add(label2)
                level2_id_map[label2] = id2
            for level3 in level2.get('children', []):
                label3 = level3.get('label', '')
                id3 = level3.get('id', '')
                if label3:
                    level3_labels.add(label3)
                    level3_id_map[label3] = id3

    return level3_labels, level3_id_map, level2_labels, level2_id_map


def build_major_mappings(hierarchy: dict[str, Any]) -> dict[str, Any]:
    """Build various mappings from major hierarchy.

    Args:
        hierarchy: Major hierarchy dictionary

    Returns:
        Dictionary containing various mappings (level2_to_level1, level3_to_level2, etc.)
    """
    level2_to_level1: dict[str, str] = {}
    level3_to_level2: dict[str, str] = {}

    major_data = hierarchy.get('data', [])

    for level1 in major_data:
        label1 = level1.get('label', '')
        for level2 in level1.get('children', []):
            label2 = level2.get('label', '')
            level2_to_level1[label2] = label1
            for level3 in level2.get('children', []):
                label3 = level3.get('label', '')
                level3_to_level2[label3] = label2

    return {
        'level2_to_level1': level2_to_level1,
        'level3_to_level2': level3_to_level2,
    }


# Load data at module import time
_data_dir = Path(__file__).resolve().parent.parent.parent / "data" / "option"
_bachelor_json_path = _data_dir / "major_bachelor.json"
_associate_json_path = _data_dir / "major_associate.json"

# Bachelor major data
bachelor_major_hierarchy = load_major_hierarchy(_bachelor_json_path)
bachelor_major_lines = flatten_hierarchy_to_lines(bachelor_major_hierarchy)
(
    bachelor_category_line_map,
    bachelor_subcategory_line_map,
    bachelor_major_line_map,
) = build_line_number_mappings(bachelor_major_hierarchy)
prefix_to_bachelor_major = build_prefix_index(bachelor_major_hierarchy)
bachelor_major_mappings = build_major_mappings(bachelor_major_hierarchy)
(
    bachelor_level3_labels,
    bachelor_level3_id_map,
    bachelor_level2_labels,
    bachelor_level2_id_map,
) = build_label_and_id_maps(bachelor_major_hierarchy)

# Associate major data
associate_major_hierarchy = load_major_hierarchy(_associate_json_path)
associate_major_lines = flatten_hierarchy_to_lines(associate_major_hierarchy)
(
    associate_category_line_map,
    associate_subcategory_line_map,
    associate_major_line_map,
) = build_line_number_mappings(associate_major_hierarchy)
prefix_to_associate_major = build_prefix_index(associate_major_hierarchy)
associate_major_mappings = build_major_mappings(associate_major_hierarchy)

# Associate label/id maps
(
    associate_level3_labels,
    associate_level3_id_map,
    associate_level2_labels,
    associate_level2_id_map,
) = build_label_and_id_maps(associate_major_hierarchy)

