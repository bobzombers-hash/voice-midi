"""Spoken-number normalisation: 'one twenty eight' -> 128, 'pad three' -> 'pad 3'."""
import re

UNITS = {"zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
         "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
         "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
         "seventeen": 17, "eighteen": 18, "nineteen": 19}
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
        "seventy": 70, "eighty": 80, "ninety": 90}
ORDINALS = {"first": "one", "second": "two", "third": "three", "fourth": "four",
            "fifth": "five", "sixth": "six", "seventh": "seven", "eighth": "eight",
            "ninth": "nine", "tenth": "ten"}
# Common speech-recognition homophones in a command context
HOMOPHONES = {"to": None, "too": "two", "for": None, "won": "one", "ate": "eight"}
NUMBER_WORDS = set(UNITS) | set(TENS) | {"hundred"}


def _is_num_token(t):
    return t in NUMBER_WORDS or t.isdigit()


def _group_value(tokens):
    """Value of a run of number tokens. Handles 'one hundred twenty eight',
    'one twenty eight' (=128), 'eight oh eight' (=808), 'twenty five'."""
    if any(t == "hundred" for t in tokens):
        total, cur = 0, 0
        for t in tokens:
            if t == "hundred":
                cur = (cur or 1) * 100
            elif t.isdigit():
                cur += int(t)
            elif t in TENS:
                cur += TENS[t]
            else:
                cur += UNITS[t]
        return total + cur
    # Split into chunks: a TENS word may absorb a following unit 1-9
    chunks, i = [], 0
    while i < len(tokens):
        t = tokens[i]
        if t in TENS:
            v = TENS[t]
            if i + 1 < len(tokens) and tokens[i + 1] in UNITS and 0 < UNITS[tokens[i + 1]] < 10:
                v += UNITS[tokens[i + 1]]
                i += 1
            chunks.append(str(v))
        elif t.isdigit():
            chunks.append(t)
        else:
            chunks.append(str(UNITS[t]))
        i += 1
    return int("".join(chunks))


def normalize_numbers(text):
    """Lowercase, strip punctuation, convert number words to digits."""
    text = text.lower().replace("-", " ")
    text = re.sub(r"[^a-z0-9#. ]+", " ", text)
    tokens = [ORDINALS.get(t, t) for t in text.split()]
    out, run = [], []

    def flush():
        if run:
            out.append(str(_group_value(run)))
            run.clear()

    for t in tokens:
        if _is_num_token(t) and not (t == "oh" and not run):
            # 'hundred' cannot start a run on its own unless preceded by number
            run.append(t)
        else:
            flush()
            out.append(t)
    flush()
    return " ".join(out)
