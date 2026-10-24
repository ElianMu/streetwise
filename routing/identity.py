"""Conservative source-address equivalence; never infer an address from proximity."""
import re


def normalized_address(value):
    text = str(value or '').lower().replace('&', ' and ')
    text = re.sub(r'(?<=\d)(?:st|nd|rd|th)\b', '', text)
    text = re.sub(r'[^a-z0-9]+', ' ', text).strip()
    for word, short in [('street','st'),('avenue','av'),('ave','av'),('west','w'),('east','e'),('place','pl'),('road','rd')]:
        text = re.sub(r'\b'+word+r'\b', short, text)
    return text or None
