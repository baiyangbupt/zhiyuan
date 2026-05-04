from pandas import *
import os


BATCH_TITLE = ['本科', '专科', '特招', '一段', '二段']
SUBJECT_TITLE = dict(N='综合',W='文科',L='理科',WL='物理',LS='历史')
SUBJECT_TYPE = ['文科', '理科', '物理', '历史', '综合']
SUBJECT_CODE = dict(文科='N',理科='L',物理='WL',历史='LS',综合='N')

def load_area_year_batch_subject_mapping(csvfile_dir: str):
    """ csv文件格式:
    "id","area_id","subject","classify","batch","batch_title","year","score","pos","school_num","major_num","n1","n2","n3","n4","apply_scope","type","begin_time","end_time","level","batch_level","batch_level_cross","tenant_code","remark","created_by","create_time","plan_data_type"
    "12302203","120000","N","01","24","专科批",2023,"160","19037","20","6",,,,,,,,,"02",,,"0000",,,,"VOLUNTEER"
    "20232101","210000","LS","01","01","本科批",2023,"404","29816","0","112",,,,,,,,,"01",,,"0000",,,,"VOLUNTEER"
    Return:
    {'130000':{2024:['W':{'本科':['24']}]}}, {'130000':{2024: ['W','L']}}
    """
    current_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(current_dir, csvfile_dir)
    data = read_csv(file_path,dtype=str)
    area_ids = data['area_id'].tolist()
    subjects = data['subject'].tolist()
    batchs = data['batch'].tolist()
    batch_titles = data['batch_title'].tolist()
    years = data['year'].tolist()
    area_year_subjects = {}
    area_year_batches = {}
    for a, s, b, bt, y in zip(area_ids, subjects, batchs, batch_titles, years):
        if not area_year_batches.get(a):
            area_year_batches[a] = {}
        if not area_year_batches[a].get(y):
            area_year_batches[a][y] = {}
        # 归一到本科、专科、特招、一段、二段
        batch_nick = [t_batch for t_batch in BATCH_TITLE if t_batch in bt][0]
        if not area_year_batches[a][y].get(batch_nick):
            area_year_batches[a][y][batch_nick] = set()
            area_year_batches[a][y][batch_nick].add(b)
        else:
            area_year_batches[a][y][batch_nick].add(b)

        if not area_year_subjects.get(a):
            area_year_subjects[a] = {}
        if not area_year_subjects[a].get(y):
            area_year_subjects[a][y] = set()
        area_year_subjects[a][y].add(s)
    for a, i in area_year_subjects.items():
        for y, s in i.items():
            area_year_subjects[a][y] = list(area_year_subjects[a][y])
    for a, i in area_year_batches.items():
        for y, j in i.items():
            for bn, k in j.items():
                area_year_batches[a][y][bn] = list(area_year_batches[a][y][bn])
        
    return area_year_batches, area_year_subjects

area_year_batches, area_year_subjects = load_area_year_batch_subject_mapping('option/batch_subject_mapping_data.csv')


if __name__ == '__main__':
    # print(area_year_subject_batch_code['130000']['2024'])
    print(area_year_batches)
    print(area_year_subjects)