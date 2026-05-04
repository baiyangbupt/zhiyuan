"""Province/city hierarchy data loading and formatting module."""

import json
from pathlib import Path


def load_province_city_hierarchy() -> dict:
    """Load province/city hierarchy data from JSON file.

    Returns:
        Parsed JSON data dict with 'data' key containing province list
    """
    data_path = Path(__file__).resolve().parent.parent.parent / "data" / "option" / "province_city.json"
    with open(data_path, "r", encoding="utf-8") as f:
        return json.load(f)


def format_province_city_hierarchy(data: dict) -> str:
    """Format province/city hierarchy as indented text for LLM prompt.

    Produces output like:
        安徽
          合肥
          芜湖
        北京
          北京市

    Args:
        data: Parsed JSON data dict with 'data' key

    Returns:
        Formatted hierarchy string with indentation
    """
    result: list[str] = []
    for province in data["data"]:
        result.append(province["label"])
        for city in province.get("children", []):
            result.append(f"  {city['label']}")
    return "\n".join(result)


def extract_all_provinces(data: dict) -> list[str]:
    """Get list of all province names.

    Args:
        data: Parsed JSON data dict

    Returns:
        List of province label strings
    """
    return [province["label"] for province in data["data"]]


def extract_all_cities(data: dict) -> list[str]:
    """Get list of all city names.

    Args:
        data: Parsed JSON data dict

    Returns:
        List of city label strings
    """
    cities: list[str] = []
    for province in data["data"]:
        for city in province.get("children", []):
            cities.append(city["label"])
    return cities


# Module-level initialization (singleton pattern)
_raw_data = load_province_city_hierarchy()
province_city_hierarchy_text = format_province_city_hierarchy(_raw_data)
all_provinces = extract_all_provinces(_raw_data)
all_cities = extract_all_cities(_raw_data)
