"""Adjacent L/R route planning only; no device writes or link-bit changes."""
from routing_labels import SOURCE_LABELS,DESTINATION_LABELS


def source_pair(code):
    if type(code) is not int:raise ValueError('Invalid source')
    for low,high in ((64,79),(80,95),(128,159),(192,193)):
        if low<=code<=high:
            left=low+((code-low)//2)*2
            return left,left+1
    raise ValueError('Choose Main Mix, Analog, ADAT or USB for stereo patching. Aux buses remain mono; turn Stereo pairs off for Aux.')


def destination_pair(index):
    if type(index) is not int or index not in DESTINATION_LABELS:raise ValueError('Unknown output pair')
    return (index//2)*2,(index//2)*2+1


def plan(source,destination,routes):
    sources=source_pair(source);destinations=destination_pair(destination)
    result=[]
    for src,dst in zip(sources,destinations):
        current=routes.get(dst)
        if type(current) is not int or current not in SOURCE_LABELS:raise ValueError('Read both mapped output routes before patching this stereo pair.')
        result.append(dict(destination=dst,source_code=src,expected_source=current))
    # Include unchanged members so preflight checks both sides. The backend
    # already skips a write when expected_source equals source_code.
    return result


def reverse(confirmed):
    return [dict(destination=r['destination'],source_code=r['expected_source'],expected_source=r['source_code']) for r in confirmed]
