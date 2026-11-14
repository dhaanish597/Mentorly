import parser from '@typescript-eslint/parser';
import hooks from 'eslint-plugin-react-hooks';
import a11y from 'eslint-plugin-jsx-a11y';

export default [
  { ignores: ['node_modules/**', 'dist/**', 'coverage/**', 'src/types/**', 'src/__tests__/**'] },
  {
    files: ['src/**/*.{ts,tsx}'],
    languageOptions: { parser, parserOptions: { ecmaVersion: 'latest', sourceType: 'module', ecmaFeatures: { jsx: true } } },
    plugins: { 'react-hooks': hooks, 'jsx-a11y': a11y },
    rules: {
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'error',
      ...a11y.configs.recommended.rules,
    },
  },
];
