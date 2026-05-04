"""School data loading and indexing module."""

import csv
from collections import defaultdict
from pathlib import Path

# Common school name keywords for filtering (from old CONSTANTS.py line 99)
SCHOOL_NAME_LIST = [
    '医', '药', '理', '工', '师', '政', '法', '农', '林', '财', '经', '语', '民', '体',
    '艺', '军', '卫', '交', '警', '信', '建', '科', '电', '旅', '铁', '教', '航', '海',
    '陆', '空', '传', '戏', '影', '视', '地', '邮', '石', '音', '美', '公', '矿', '城',
    '服', '联', '舞', '资', '印', '煤', '商', '职', '技', '安', '保', '女', '茶', '船',
    '漫', '金', '康', '软', '纺', '环', '腔', '劳', '培', '烹', '酒', '防', '武', '生',
    '网', '文', '数', '新', '制', '能'
]


def load_school_names(csv_path: str) -> list[str]:
    """Load school names from CSV file.

    Args:
        csv_path: Path to CSV file with '标准院校名称' column

    Returns:
        List of school names
    """
    schools = []
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            school_name = row.get('标准院校名称', '').strip()
            if school_name:
                schools.append(school_name)
    return schools


def load_school_names_and_ids(csv_path: str) -> tuple[list[str], set[str], dict[str, str]]:
    """Load school names and build name-to-id mapping from CSV.

    Args:
        csv_path: Path to CSV file with '标准院校id' and '标准院校名称' columns

    Returns:
        Tuple of (name_list, name_set, name_to_id_map)
    """
    names = []
    name_set: set[str] = set()
    name_to_id: dict[str, str] = {}
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            school_name = row.get('标准院校名称', '').strip()
            school_id = row.get('标准院校id', '').strip()
            if school_name:
                names.append(school_name)
                name_set.add(school_name)
                if school_id:
                    name_to_id[school_name] = school_id
    return names, name_set, name_to_id


def build_area_index(school_list: list[str]) -> dict[str, list[str]]:
    """Build area-based index for schools.

    Creates index by:
    - First character of school name
    - Keywords from SCHOOL_NAME_LIST contained in school name

    Args:
        school_list: List of school names

    Returns:
        Dictionary mapping area/keyword to list of schools
    """
    area_to_school: dict[str, list[str]] = defaultdict(list)

    for school in school_list:
        # Index by first character
        area_to_school[school[:1]].append(school)

        # Index by keywords
        for key in SCHOOL_NAME_LIST:
            if key in school:
                area_to_school[key].append(school)

    return dict(area_to_school)


def fuzzy_match_school_name(
    query: str,
    school_set: set[str],
    area_index: dict[str, list[str]],
    max_candidates: int = 10,
) -> list[str]:
    """Find candidate school names by keyword and substring matching.

    Args:
        query: User-typed school name
        school_set: Set of all standard school names
        area_index: The area/keyword-to-schools index
        max_candidates: Maximum number of candidates to return

    Returns:
        List of matching standard school name strings
    """
    if query in school_set:
        return [query]

    candidates: list[str] = []
    seen: set[str] = set()

    # Keyword match via area index
    for char in query:
        for name in area_index.get(char, []):
            if name not in seen:
                candidates.append(name)
                seen.add(name)

    # Substring match
    for name in school_set:
        if query in name or name in query:
            if name not in seen:
                candidates.append(name)
                seen.add(name)

    return candidates[:max_candidates]


# Initialize data at module load time
_data_dir = Path(__file__).resolve().parent.parent.parent / "data" / "option"
_bachelor_csv = _data_dir / "school_bachelor.csv"
_associate_csv = _data_dir / "school_associate.csv"

bachelor_schools, bachelor_school_set, bachelor_school_id_map = load_school_names_and_ids(str(_bachelor_csv))
associate_schools, associate_school_set, associate_school_id_map = load_school_names_and_ids(str(_associate_csv))

area_to_bachelor_schools = build_area_index(bachelor_schools)
area_to_associate_schools = build_area_index(associate_schools)
