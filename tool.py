#!/usr/bin/env python3
"""Offline, bounded contract audit. Python 3.12 standard library only."""
import argparse
import json
import math
import sys
from pathlib import Path

MAX_BYTES = 2 * 1024 * 1024
MAX_ITEMS = 10000
class BadInput(ValueError):
    pass
class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise BadInput("invalid command arguments")

def require(condition, message):
    if not condition:
        raise BadInput(message)

def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, "duplicate JSON object key")
        result[key] = value
    return result

def reject_constant(value):
    raise BadInput("nonfinite JSON number")

def read_text(path):
    require(Path(path).is_file(), "input must be a regular file")
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    require(len(raw) <= MAX_BYTES, "input exceeds 2 MiB limit")
    return raw.decode("utf-8-sig")

def finite_float(value):
    parsed = float(value)
    require(math.isfinite(parsed), "nonfinite JSON number")
    return parsed

def load_json(path):
    return json.loads(read_text(path), object_pairs_hook=pairs, parse_constant=reject_constant, parse_float=finite_float)

def report(findings, **summary):
    return {"schema_version": 1, "tool": TOOL, "status": "findings" if findings else "pass", "summary": summary, "findings": findings}

def finding(code, **where):
    return {"code": code, **where}

def run(build_parser, action):
    try:
        parser = Parser(description=__doc__)
        build_parser(parser)
        result = action(parser.parse_args())
        status = 1 if result["status"] == "findings" else 0
    except (ValueError, OSError, UnicodeError, RecursionError, OverflowError) as exc:
        message = str(exc) if isinstance(exc, BadInput) else "unreadable or malformed input"
        result = {"schema_version": 1, "tool": TOOL, "status": "error", "error": message}
        status = 2
    print(json.dumps(result, ensure_ascii=True, sort_keys=True, allow_nan=False))
    return status

import collections
import hashlib
import re
import string
TOOL = "translation-placeholder-contract"

def placeholders(text):
    require(isinstance(text, str) and len(text) <= 100000, "translation values must be bounded strings")
    counter, automatic, explicit, next_auto = collections.Counter(), False, False, 0
    def parse(value, depth=0):
        nonlocal automatic, explicit, next_auto
        require(depth <= 2, "format nesting exceeds supported depth")
        try:
            parts = list(string.Formatter().parse(value))
        except ValueError:
            raise BadInput("malformed format-style placeholder") from None
        for _, field, spec, conversion in parts:
            if field is None:
                continue
            require(conversion in (None, "s", "r", "a"), "unsupported format conversion")
            if field == "":
                automatic = True; name = str(next_auto); next_auto += 1
            else:
                require(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]{1,9}", field) is not None, "only simple named/indexed placeholders are supported")
                if field.isdecimal():
                    explicit = True; name = str(int(field))
                else:
                    name = field
            require(not (automatic and explicit), "cannot mix automatic and explicit numeric placeholders")
            # Preserve literal format specifications, and independently count nested fields.
            counter[(name, conversion or "", spec)] += 1
            if "{" in spec or "}" in spec:
                parse(spec, depth+1)
    parse(text)
    require(sum(counter.values()) <= 1000, "placeholder budget exceeded")
    return counter

def audit(data):
    require(isinstance(data, dict) and set(data) == {"source", "translations"}, "expected source/translations object")
    source, translations = data["source"], data["translations"]
    require(isinstance(source, dict) and 1 <= len(source) <= MAX_ITEMS, "source must be a nonempty bounded flat string map")
    require(isinstance(translations, dict) and 1 <= len(translations) <= 100, "translations needs 1..100 locale maps")
    require(all(isinstance(k, str) and 0 < len(k) <= 1024 for k in source), "source keys must be bounded strings")
    expected = {key: placeholders(value) for key, value in source.items()}
    findings, total = [], len(source)
    def key_id(key):
        return hashlib.sha256(key.encode()).hexdigest()
    for locale_index, (locale, values) in enumerate(translations.items()):
        require(isinstance(locale, str) and locale and isinstance(values, dict), "locale names need flat object maps")
        total += len(values); require(total <= 50000, "translation entry budget exceeded")
        require(all(isinstance(k, str) and 0 < len(k) <= 1024 for k in values), "translation keys must be bounded strings")
        actual = {key: placeholders(value) for key, value in values.items()}
        for key in sorted(source.keys() - values.keys()):
            findings.append(finding("missing_translation", locale_index=locale_index, key_sha256=key_id(key)))
        for key in sorted(values.keys() - source.keys()):
            findings.append(finding("extra_translation_key", locale_index=locale_index, key_sha256=key_id(key)))
        for key in sorted(source.keys() & values.keys()):
            if source[key] and not values[key]:
                findings.append(finding("empty_translation", locale_index=locale_index, key_sha256=key_id(key)))
            if expected[key] != actual[key]:
                findings.append(finding("placeholder_mismatch", locale_index=locale_index, key_sha256=key_id(key), source_fields=sum(expected[key].values()), translation_fields=sum(actual[key].values())))
    return report(findings, source_keys=len(source), locales=len(translations), entries=total)

def configure(parser):
    parser.add_argument("input", help="local flat translation contract JSON")
if __name__ == "__main__":
    sys.exit(run(configure, lambda args: audit(load_json(args.input))))
