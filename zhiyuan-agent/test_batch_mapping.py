from app.util.batch_subject_mapping import (
    get_area_subject_codes, get_area_batch_codes,
    resolve_subject_type, resolve_batch_codes, encode_subjects,
)

# 湖南 430000
area_id = '430000'
print('=== 湖南 2024 ===')
print('subjects:', get_area_subject_codes(area_id, '2024'))
print('batches:', get_area_batch_codes(area_id, '2024'))

subject_list = ['物理', '化学', '生物']
print('subject_type:', resolve_subject_type(area_id, subject_list))
print('encoded_subjects:', encode_subjects(subject_list))
print('batch_codes:', resolve_batch_codes(area_id, '本科'))

# 安徽 340000
area_id2 = '340000'
print()
print('=== 安徽 2024 ===')
print('subjects:', get_area_subject_codes(area_id2, '2024'))
print('batches:', get_area_batch_codes(area_id2, '2024'))
print('subject_type(理科):', resolve_subject_type(area_id2, ['理科']))

print()
print('encode 物化生:', encode_subjects(['物理', '化学', '生物']))
print('encode 史地政:', encode_subjects(['历史', '地理', '政治']))
