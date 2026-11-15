"""Select hardware checks by case-insensitive name fragment."""


def case_selected(name, patterns):
    return not patterns or any(pattern.casefold() in name.casefold() for pattern in patterns)
