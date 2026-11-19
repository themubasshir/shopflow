import re

_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")


def phone_digits(value: str) -> str:
    return re.sub(r"[\s().-]", "", value.translate(_DIGITS))


def normalize_mobile(value: str) -> str:
    mobile = phone_digits(value)
    if re.fullmatch(r"(?:0|\+?880|00880)1[3-9][0-9]{8}", mobile) is None:
        raise ValueError("Enter a valid Bangladeshi mobile number")
    return "+880" + mobile[-10:]
