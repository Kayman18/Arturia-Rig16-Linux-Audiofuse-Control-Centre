"""Decorate verified routing IDs without changing cable addressing.

Analog output name-slot -> speaker/line/headphone mapping remains unverified.
"""
from routing_labels import SOURCE_LABELS,DESTINATION_LABELS

def named_label(cache,kind,code):
    native=(SOURCE_LABELS if kind=='source' else DESTINATION_LABELS).get(code,f'Unknown {code}')
    source=(code-63 if 64<=code<=95 else None) if kind=='source' else (code+65 if 12<=code<=27 else None)
    name=getattr(cache,'names',{}).get(source) if source is not None else None
    return native+' · '+name if name else native
