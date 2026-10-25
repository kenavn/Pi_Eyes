"""Small fail-closed interpreter for the vendored generated contract vocabulary."""
import json
import re
import uuid
from pathlib import Path


class Refusal(Exception):
    def __init__(self, reason, status=400):
        self.reason, self.status = reason, status
        super().__init__(reason)


def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise Refusal('malformed')
        result[key] = value
    return result


def decode(data):
    try:
        return json.loads(data.decode('utf-8'), object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(Refusal('malformed')))
    except (ValueError, UnicodeError, RecursionError):
        raise Refusal('malformed') from None


SCHEMAS = {name: json.loads((Path(__file__).parent / 'contracts' / (name + '.schema.json')).read_text())
           for name in ('head-control', 'device-content')}


def validate(name, value, family='head-control'):
    root = SCHEMAS[family]
    node = root['properties'][name]
    return check(node, value, root)


def check(node, value, root):
    if '$ref' in node:
        target = root
        for part in node['$ref'].split('/')[1:]:
            target = target[part]
        return check(target, value, root)
    if 'anyOf' in node:
        for variant in node['anyOf']:
            try:
                return check(variant, value, root)
            except Refusal:
                pass
        raise Refusal('malformed')
    kind = node.get('type')
    if isinstance(kind, list):
        if value is None and 'null' in kind:
            return value
        kind = next(k for k in kind if k != 'null')
    valid = {'object': type(value) is dict, 'array': type(value) is list,
             'string': type(value) is str, 'integer': type(value) is int,
             'number': type(value) in (int, float), 'boolean': type(value) is bool,
             'null': value is None}
    if kind and not valid.get(kind, False):
        raise Refusal('malformed')
    if 'enum' in node and value not in node['enum']:
        raise Refusal('malformed')
    if 'const' in node and value != node['const']:
        raise Refusal('malformed')
    if kind == 'object':
        props = node.get('properties', {})
        if set(node.get('required', [])) - value.keys():
            raise Refusal('malformed')
        if node.get('additionalProperties') is False and value.keys() - props.keys():
            raise Refusal('malformed')
        for key in value:
            if key in props:
                value[key] = check(props[key], value[key], root)
    elif kind == 'array':
        if len(value) < node.get('minItems', 0) or len(value) > node.get('maxItems', 100000):
            raise Refusal('malformed')
        for index, item in enumerate(value):
            value[index] = check(node['items'], item, root)
    elif kind == 'string':
        if len(value) < node.get('minLength', 0) or len(value) > node.get('maxLength', 131072):
            raise Refusal('malformed')
        if 'pattern' in node and not re.fullmatch(node['pattern'], value):
            raise Refusal('malformed')
        if node.get('format') == 'uuid':
            try:
                parsed = uuid.UUID(value)
                if parsed.int == 0:
                    raise ValueError()
            except ValueError:
                raise Refusal('malformed') from None
            return str(parsed)
        # Counter schemas encode syntax; numeric range additionally needs checking.
        if re.fullmatch(r'(0|[1-9][0-9]*)', value) and len(value) >= 19 and int(value) > 9223372036854775807:
            raise Refusal('malformed')
    elif kind in ('number', 'integer'):
        if value < node.get('minimum', value) or value > node.get('maximum', value):
            raise Refusal('malformed')

    if kind == 'object' and 'role_ids' in node.get('properties', {}):
        roles = value['role_ids']
        if not roles or len(roles) > 1024 or any(a >= b for a, b in zip(roles, roles[1:])):
            raise Refusal('malformed')
    if kind == 'object' and {'owner', 'role_id', 'occurrence'} <= node.get('properties', {}).keys():
        if value['role_id'] not in value['owner']['role_ids']:
            raise Refusal('wrong_activity', 409)
    return value
