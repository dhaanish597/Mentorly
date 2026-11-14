import { describe, expect, it } from 'vitest';
import { parsePrediction, formatPrediction } from '../catalog/prediction';

describe('Typed predictions preserve output shape', () => {
  it('accepts safe integers, booleans, quoted strings and scalar lists without coercion', () => {
    expect(parsePrediction('23')).toBe(23);
    expect(parsePrediction('true')).toBe(true);
    expect(parsePrediction('"hello"')).toBe('hello');
    expect(parsePrediction('[1, false, "x"]')).toEqual([1, false, 'x']);
    expect(formatPrediction('hello')).toBe('"hello"');
    expect(formatPrediction([1, true])).toBe('[1,true]');
  });
  it('rejects floats, unsafe integers, nested lists, objects, null and unquoted strings', () => {
    for (const value of ['1.2', '9007199254740992', '[[1]]', '{}', 'null', 'hello', '[null]']) expect(() => parsePrediction(value)).toThrow();
  });
  it('enforces bounded output lengths and declared shape', () => {
    expect(() => parsePrediction(JSON.stringify('x'.repeat(257)))).toThrow(/256/);
    expect(() => parsePrediction(JSON.stringify(Array(129).fill(1)))).toThrow(/128/);
    expect(() => parsePrediction('true', 'integer')).toThrow(/integer/);
    expect(() => parsePrediction('1', 'boolean')).toThrow(/boolean/);
    expect(parsePrediction('1', 'integer')).toBe(1);
  });
});
