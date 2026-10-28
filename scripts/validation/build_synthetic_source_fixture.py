"""Build an offline synthetic source below the repository's ignored .runtime directory."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_ROOT = ROOT / '.runtime' / 'validation'


def build_fixture(session_id):
    if session_id <= 0:
        raise ValueError('session-id must identify an isolated synthetic test session')
    score = {
        'botId': 1, 'userName': 'SYNTHETIC ONLY', 'draft': True,
        'province': {'code': '11', 'name': '北京'}, 'examYear': 2026,
        'sex': {'code': 'male', 'name': '男'},
        'subjectType': {'code': 'WL', 'desc': '物理'},
        'subjectList': [{'value': code, 'name': name, 'isFirst': 1 if i == 0 else 0}
                        for i, (code, name) in enumerate([('04','物理'), ('05','化学'), ('06','生物')])],
        'subjectScoreList': [{'subject': c, 'subjectName': n, 'score': 90}
                             for c,n in [('04','物理'),('05','化学'),('06','生物')]],
        'strengthSubjectList': [], 'prepareType': {'code': 'PREDICT', 'desc': '模拟填报'},
        'batch': {'code': 'synthetic-batch', 'name': '合成本科批', 'level': '01', 'score': 400},
        'totalScore': 600, 'totalScorePos': 10000, 'targetType': 'SCHOOL_FIRST',
        'filterType': '2', 'volunteerModel': 'major', 'volunteerDetailModel': 'OTOO',
        'volunteerCount': {'schoolCount': 10, 'majorCount': 10},
        'strategyType': {'code': 'balanced', 'name': '均衡'},
        'specialPlan': False, 'ethnicity': {'code': '01', 'name': '汉族'},
        'colorSituation': ['normal'], 'acceptForeignSchool': True,
        'tuitionRange': {'min': 0, 'max': 200000},
    }
    rows = []
    # Catalog IDs supply descriptive dictionary lookups only. All plan IDs and admission values are fabricated.
    for i in range(12):
        tier, ratio = [('SPRINT', '30'), ('SAFE', '60'), ('PROTECT', '90')][i // 4]
        rows.append({
            'schoolId': str(i+1), 'schoolUnitName': 'SYNTHETIC_school_%02d' % (i+1),
            'schoolUnitCode': 'SYN%02d' % i,
            'planSchoolDataId': 'synthetic-%s-school-%02d' % (session_id,i),
            'planMajorDataId': 'synthetic-%s-major-%02d' % (session_id,i),
            'majorId': '233', 'majorUnitName': 'SYNTHETIC_哲学', 'majorUnitCode': '010101',
            'categoryId': '1', 'subCategoryId': '2',
            'volunteerLevel': {'code': tier, 'desc': tier}, 'enrollRatio': ratio,
            'schoolScore': '580', 'schoolPos': 15000, 'majorScore': '580', 'majorPos': 15000,
            'planNum': 10, 'planMoney': '5000', 'planDuration': '4', 'selectInfo': '不限',
            'majorIsNew': False, 'schoolIsNew': False,
            'area': {'key': '11', 'data': '北京'}, 'city': {'key': '1101', 'data': '北京'},
            'subVOList': [],
        })
    source = {'type': {'code': 'OTOO', 'desc': 'SYNTHETIC ONLY'}, 'policy': '02',
              'isLatestPolicy': True, 'model': {'majorTotalNum': 12, 'schoolTotalNum': 12,
              'majorSprintNum': 4, 'majorSafeNum': 4, 'majorProtectNum': 4,
              'schoolSprintNum': 4, 'schoolSafeNum': 4, 'schoolProtectNum': 4}, 'detailList': rows}
    return {f'session_volunteer_{session_id}.json': source, 'score-detail.json': score,
            'generate-request.json': {'forceRegenerate': True, 'refreshSourceData': False},
            'initial-plan-request.json': {'forceRegenerate': False, 'regroupByTier': True, 'overwriteExistingDraft': False}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session-id', type=int, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if args.session_id <= 0:
        parser.error('session-id must identify an isolated synthetic test session')
    output = args.output_dir.resolve()
    if EVIDENCE_ROOT.resolve() not in output.parents or output.is_symlink():
        parser.error('output-dir must be a new real directory below ignored .runtime/validation')
    if not args.apply:
        print('Dry run: would write four SYNTHETIC ONLY JSON files below ' + str(output))
        return
    output.mkdir(parents=True, exist_ok=False)
    for name, data in build_fixture(args.session_id).items():
        path = output / name
        with path.open('x', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, separators=(',', ':'))
        print(name, hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
