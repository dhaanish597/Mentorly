import { afterEach, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { DEFAULT_PRODUCT_STATE, loadProductState, saveProductState } from '../state/productState';
import { isProductLanguageMode, PRODUCT_LANGUAGES, recognitionLocale, resolveLanguageMode } from '../voice/languages';
import { FeedbackView } from '../StudioViews';

afterEach(cleanup);

it.each(PRODUCT_LANGUAGES)('preserves $code through reload and independent locale selection', ({ code }) => {
  let stored = '';
  const storage = {setItem: (_key: string, value: string) => { stored = value; }, getItem: () => stored};
  expect(saveProductState({...DEFAULT_PRODUCT_STATE, language:code},storage)).toBeNull();
  expect(loadProductState(storage).language).toBe(code);
  expect(resolveLanguageMode(recognitionLocale(code),code.includes(','))).toBe(code);
});

it('rejects unsupported modes rather than silently claiming code mixing', () => {
  expect(isProductLanguageMode('te-IN,en-IN')).toBe(false);
  expect(loadProductState({getItem: () => '{"language":"te-IN,en-IN"}'}).language).toBe('en-IN');
  expect(PRODUCT_LANGUAGES).toHaveLength(13);
});

it.each([
  ['MODEL_TIMEOUT','Model feedback timed out.'],
  ['MODEL_INVALID_RESPONSE','The model response could not be validated.'],
  ['MODEL_RATE_LIMITED','Model feedback capacity or budget is exhausted.'],
  ['MODEL_ASSISTED','Model-assisted feedback.'],
])('shows %s separately from unassessed correctness', (model_status, label) => {
  render(<FeedbackView value={{status:'unassessed', source:'deterministic_fallback', model_status, question:'Which input would you test?'}} />);
  expect(screen.getByRole('status').textContent).toBe(label);
  expect(screen.getByText('unassessed').textContent).toBe('unassessed');
  expect(screen.getByText('Which input would you test?')).toBeTruthy();
});
