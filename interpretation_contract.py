"""Single interpretation contract and strict OpenAI wire adapter.

Only serialization changes: dimension definitions come from the routing engine.
The public API remains sparse weights/directions; wire preferences pair them.
"""
import math
from routing.engine import DIMENSIONS, MIN_WALK_MINUTES


def obj(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


def nullable(schema):
    return {'anyOf': [schema, {'type': 'null'}]}


def enum(values):
    return {'type': 'string', 'enum': list(values)}


def array(schema, limit):
    return {'type': 'array', 'items': schema, 'maxItems': limit}


def number(lo, hi=None, integer=False):
    s = {'type': 'integer' if integer else 'number', 'minimum': lo}
    if hi is not None:
        s['maximum'] = hi
    return s


TEXT = {'type': 'string', 'maxLength': 160}
BOOL = {'type': 'boolean'}
INTERESTS = ['famous', 'museums', 'historic', 'parks', 'shopping', 'culture']
CATEGORIES = ['cafes', 'restaurants', 'bakeries', 'bars']
SERVICES = ['pharmacies', 'groceries', 'health', 'banks', 'restrooms', 'luggage']
JOURNEY = obj({
    'interests': array(enum(INTERESTS), 6),
    'named_stops': array(obj({'name': TEXT, 'required': BOOL, 'order': nullable({'type': 'integer'})}), 8),
    'food': array(obj({'category': enum(CATEGORIES), 'item': nullable({'type': 'string', 'maxLength': 60}),
                       'cuisine': nullable({'type': 'string', 'maxLength': 40}), 'required': BOOL}), 4),
    'services': array(enum(SERVICES), 6),
    'service_scope': nullable(enum(['near_hotel', 'along_route', 'near_start'])),
    'hotel': nullable(obj({'name': TEXT, 'is_mine': BOOL})),
    'origin': nullable(TEXT), 'destination': nullable(TEXT),
    'end_mode': nullable(enum(['fixed', 'round', 'hotel', 'open'])),
    'walking_minutes': nullable(number(MIN_WALK_MINUTES, 1440)),
    'outing_minutes': nullable(number(10, 1440)), 'distance_km': nullable(number(.1, 100)),
    'more': obj({k: nullable(number(1, 5, True)) for k in INTERESTS + ['cafes', 'restaurants']}),
    'remove': array(TEXT, 5),
})
COMMON = {
    'time_minutes': nullable(number(MIN_WALK_MINUTES, integer=True)),
    'time_delta_minutes': nullable(number(-1440, 1440, True)),
    'max_detour_percent': nullable(number(0, 100, True)),
    'constraints': obj({k: nullable(BOOL) for k in ['avoidDetours', 'stepFree', 'avoidStairs']}),
    'weather': nullable(enum(['ask', 'cooler', 'consider'])),
    'journey': nullable(JOURNEY),
    'clarification': nullable({'type': 'string', 'maxLength': 300}),
}
WIRE_SCHEMA = obj({'preferences': array(obj({
    'dimension': enum(DIMENSIONS), 'weight': number(0, 100, True),
    'direction': enum(['high', 'low']),
}), 12), **COMMON})
RESPONSE_FORMAT = {'type': 'json_schema', 'json_schema': {
    'name': 'streetwise_interpretation', 'strict': True, 'schema': WIRE_SCHEMA,
}}


def validate(value, schema, path='output', required=True):
    """Validate the closed schema subset used above, without coercion or truncation."""
    if 'anyOf' in schema:
        for choice in schema['anyOf']:
            try:
                validate(value, choice, path, required)
                return
            except ValueError:
                pass
        raise ValueError(f'{path}: invalid nullable value')
    kind = schema['type']
    valid = {'null': value is None, 'object': isinstance(value, dict),
             'array': isinstance(value, list), 'string': isinstance(value, str),
             'boolean': type(value) is bool, 'integer': type(value) is int,
             'number': type(value) in (int, float)}[kind]
    if not valid:
        raise ValueError(f'{path}: expected {kind}')
    if kind == 'object':
        props = schema['properties']
        if set(value) - set(props):
            raise ValueError(f'{path}: unknown fields')
        if required and set(props) - set(value):
            raise ValueError(f'{path}: missing fields')
        for key, entry in value.items():
            validate(entry, props[key], path + '.' + key, required)
    elif kind == 'array':
        if len(value) > schema['maxItems']:
            raise ValueError(f'{path}: too many items')
        for entry in value:
            validate(entry, schema['items'], path + '[]', required)
    elif kind in ('integer', 'number'):
        if not math.isfinite(value) or value < schema.get('minimum', -math.inf) or value > schema.get('maximum', math.inf):
            raise ValueError(f'{path}: outside numeric range')
    elif kind == 'string':
        if len(value) > schema.get('maxLength', math.inf) or ('enum' in schema and value not in schema['enum']):
            raise ValueError(f'{path}: invalid string')


def normalize_wire(output):
    validate(output, WIRE_SCHEMA)
    weights, directions = {}, {}
    for p in output['preferences']:
        d = p['dimension']
        if d in weights:
            raise ValueError('Duplicate preference dimension')
        weights[d], directions[d] = p['weight'], p['direction']
    result = {k: output[k] for k in COMMON}
    result['weights'], result['directions'] = weights, directions
    result['constraints'] = {k: v for k, v in result['constraints'].items() if v is not None}
    if result['journey'] is not None:
        result['journey'] = dict(result['journey'])
        result['journey']['more'] = {k: v for k, v in result['journey']['more'].items() if v is not None}
    return result
