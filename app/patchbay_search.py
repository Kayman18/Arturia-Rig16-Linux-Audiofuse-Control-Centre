"""Literal, case-insensitive patch-bay label matching; no device operations."""
import unicodedata

def matches(query,*labels):
    normalize=lambda s:unicodedata.normalize('NFKC',str(s)).casefold()
    words=normalize(query).split()
    text=' '.join(normalize(s) for s in labels)
    return all(word in text for word in words)
