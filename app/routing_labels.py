"""Labels recovered from AFCC 2.5.0.1665's native routing tables.

These identify software source codes and native destination identifiers.
Unlisted codes are deliberately left unknown.
"""
AGENT_SHA256 = '7a6b805d11170c9f35731b40f83c48efacfd248edc95c7baf6c6e01faad13513'
SOURCE_LABELS = {
    **{64 + i: f'Analog {i + 1}' for i in range(16)},
    **{80 + i: f'ADAT {i + 1}' for i in range(16)},
    **{128 + i: f'USB {i + 1}' for i in range(32)},
    192: 'Main Mix L', 193: 'Main Mix R',
    **{194 + i: f'Aux {i + 1}' for i in range(4)},
}
DESTINATION_LABELS = {
    0: 'Speakers L', 1: 'Speakers R',
    **{2 + i: f'Analog{i + 1}' for i in range(8)},
    10: 'Phones L', 11: 'Phones R',
    **{12 + i: f'ADAT{i + 1}' for i in range(16)},
    **{28 + i: f'USB{i + 1}' for i in range(32)},
}


def describe_route(field, index, value):
    if field != 'output_source':
        return ''
    destination = DESTINATION_LABELS.get(index, f'Unmapped slot {index}')
    source = SOURCE_LABELS.get(value, f'Unmapped code {value}')
    return f'{destination} ← {source}'


def decoded_routes(values):
    result = []
    for index in range(62):
        key = f'output_source[{index}]'
        if key not in values:
            continue
        code = values[key]
        result.append({'index': index, 'source_code': code,
                       'destination_native_name': DESTINATION_LABELS.get(index),
                       'source_name': SOURCE_LABELS.get(code)})
    return result
