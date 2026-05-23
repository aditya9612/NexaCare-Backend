import re

PHONE_REGEX = re.compile(r"^\+?[1-9]\d{6,14}$")
MRN_REGEX = re.compile(r"^MRN-\d{8}$")


def is_valid_phone(phone: str) -> bool:
    return bool(PHONE_REGEX.match(phone))


def is_valid_mrn(mrn: str) -> bool:
    return bool(MRN_REGEX.match(mrn))
